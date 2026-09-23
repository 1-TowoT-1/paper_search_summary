from __future__ import annotations

import re
from typing import Any
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.llm.llm_client import LLMClient
from app.models.db import Paper, Project, ProjectPaper, ProjectQA
from app.models.schemas import Citation, QARequest, QAResponse, QAScope
from app.services.rag_service import RAGService


DIRECT_ANSWER = "direct_answer"
GET_PROJECT_STATS = "get_project_stats"
LIST_PROJECT_PAPERS = "list_project_papers"
SEARCH_PROJECT_EVIDENCE = "search_project_evidence"
ALLOWED_ACTIONS = {
    DIRECT_ANSWER,
    GET_PROJECT_STATS,
    LIST_PROJECT_PAPERS,
    SEARCH_PROJECT_EVIDENCE,
}


class ProjectAgentService:
    """A bounded, read-only agent router in front of the existing RAG service."""

    MAX_LISTED_PAPERS = 20

    def __init__(self, llm: LLMClient | None = None) -> None:
        self.llm = llm or LLMClient()
        self.rag = RAGService()
        self.rag.llm = self.llm

    async def answer(self, db: Session, payload: QARequest, user_id: str) -> QAResponse:
        if payload.scope != QAScope.project:
            return await self.rag.answer(db=db, payload=payload, user_id=user_id)
        if not payload.project_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="project_id is required for project QA")

        user_uuid = UUID(user_id)
        project = self._get_owned_project(db=db, project_id=payload.project_id, user_id=user_uuid)
        action = await self._decide_action(payload.question)

        if action == SEARCH_PROJECT_EVIDENCE:
            return await self.rag.answer(db=db, payload=payload, user_id=user_id)

        citations: list[Citation] = []
        if action == GET_PROJECT_STATS:
            tool_result = self._get_project_stats(db=db, project=project, user_id=user_uuid)
            answer = await self._answer_from_tool_with_fallback(
                question=payload.question,
                tool_name=GET_PROJECT_STATS,
                tool_result=tool_result,
                fallback=(
                    f"项目“{project.name}”目前收录 {tool_result['paper_count']} 篇文献，"
                    f"并保存了 {tool_result['qa_count']} 条历史问答。"
                ),
            )
        elif action == LIST_PROJECT_PAPERS:
            tool_result, citations = self._list_project_papers(db=db, project=project, user_id=user_uuid)
            fallback = self._format_paper_list_fallback(project.name, tool_result)
            answer = await self._answer_from_tool_with_fallback(
                question=payload.question,
                tool_name=LIST_PROJECT_PAPERS,
                tool_result=tool_result,
                fallback=fallback,
            )
        else:
            answer = await self._answer_general_with_fallback(payload.question)

        await self.rag._record_project_qa(
            db=db,
            project_id=project.id,
            user_id=user_uuid,
            question=payload.question,
            answer=answer,
            citations=citations,
        )
        return QAResponse(
            answer=answer,
            citations=citations,
            session_id=payload.session_id or str(uuid4()),
        )

    async def _decide_action(self, question: str) -> str:
        deterministic = self._high_confidence_action(question)
        if deterministic:
            return deterministic
        try:
            decision = await self.llm.plan_project_question(question)
            return self._enforce_policy(question=question, proposed_action=decision.get("action", ""))
        except Exception:
            return self._fallback_action(question)

    def _high_confidence_action(self, question: str) -> str | None:
        value = " ".join(question.lower().split())
        if re.search(r"(多少|几篇|数量|总数).{0,8}(文献|论文|资料)", value) or re.search(
            r"(文献|论文|资料).{0,8}(多少|几篇|数量|总数)", value
        ):
            return GET_PROJECT_STATS
        if re.search(r"(列出|查看|显示|有哪些|包含哪些).{0,8}(文献|论文|资料)", value):
            return LIST_PROJECT_PAPERS
        if value in {"你好", "您好", "hello", "hi", "你是谁", "你能做什么"}:
            return DIRECT_ANSWER
        return None

    def _enforce_policy(self, question: str, proposed_action: str) -> str:
        deterministic = self._high_confidence_action(question)
        if deterministic:
            return deterministic
        action = proposed_action if proposed_action in ALLOWED_ACTIONS else self._fallback_action(question)
        if action == DIRECT_ANSWER and self._requires_project_data(question):
            return SEARCH_PROJECT_EVIDENCE
        return action

    def _fallback_action(self, question: str) -> str:
        deterministic = self._high_confidence_action(question)
        if deterministic:
            return deterministic
        return SEARCH_PROJECT_EVIDENCE if self._requires_project_data(question) else DIRECT_ANSWER

    def _requires_project_data(self, question: str) -> bool:
        value = question.lower()
        markers = (
            "这个项目",
            "本项目",
            "当前项目",
            "项目中",
            "项目里",
            "项目内",
            "项目的文献",
            "收录的文献",
            "这些文献",
            "这些论文",
        )
        return any(marker in value for marker in markers)

    def _get_owned_project(self, db: Session, project_id: UUID, user_id: UUID) -> Project:
        project = db.query(Project).filter(Project.id == project_id, Project.user_id == user_id).first()
        if project is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
        return project

    def _accessible_project_papers_query(self, db: Session, project_id: UUID, user_id: UUID):
        return (
            db.query(Paper)
            .join(ProjectPaper, ProjectPaper.paper_id == Paper.id)
            .filter(ProjectPaper.project_id == project_id)
            .filter(or_(Paper.visibility == "public", Paper.owner_user_id == user_id))
        )

    def _get_project_stats(self, db: Session, project: Project, user_id: UUID) -> dict[str, Any]:
        paper_count = self._accessible_project_papers_query(db, project.id, user_id).count()
        qa_count = (
            db.query(ProjectQA)
            .filter(ProjectQA.project_id == project.id, ProjectQA.user_id == user_id)
            .count()
        )
        return {
            "project_id": str(project.id),
            "project_name": project.name,
            "paper_count": paper_count,
            "qa_count": qa_count,
        }

    def _list_project_papers(
        self,
        db: Session,
        project: Project,
        user_id: UUID,
    ) -> tuple[dict[str, Any], list[Citation]]:
        base_query = self._accessible_project_papers_query(db, project.id, user_id)
        total = base_query.count()
        papers = base_query.order_by(Paper.created_at.desc()).limit(self.MAX_LISTED_PAPERS).all()
        items = [
            {
                "paper_id": str(paper.id),
                "title": paper.title,
                "source": paper.source,
                "published_date": str(paper.published_date or ""),
                "doi": paper.doi or "",
            }
            for paper in papers
        ]
        citations = [
            Citation(paper_id=paper.id, title=paper.title, chunk_id=None, locator="project_library")
            for paper in papers
        ]
        return {
            "project_id": str(project.id),
            "project_name": project.name,
            "total": total,
            "returned": len(items),
            "papers": items,
        }, citations

    async def _answer_from_tool_with_fallback(
        self,
        question: str,
        tool_name: str,
        tool_result: dict[str, Any],
        fallback: str,
    ) -> str:
        try:
            return await self.llm.answer_from_project_tool(
                question=question,
                tool_name=tool_name,
                tool_result=tool_result,
            )
        except Exception:
            return fallback

    async def _answer_general_with_fallback(self, question: str) -> str:
        try:
            return await self.llm.answer_general_question(question)
        except Exception:
            return "当前通用问答模型暂时不可用，请稍后重试。"

    def _format_paper_list_fallback(self, project_name: str, tool_result: dict[str, Any]) -> str:
        papers = tool_result.get("papers") or []
        if not papers:
            return f"项目“{project_name}”当前没有已收录文献。"
        lines = [f"项目“{project_name}”当前收录 {tool_result['total']} 篇文献："]
        lines.extend(f"{index}. {paper['title']}" for index, paper in enumerate(papers, start=1))
        if tool_result["total"] > tool_result["returned"]:
            lines.append(f"当前仅展示前 {tool_result['returned']} 篇。")
        return "\n".join(lines)
