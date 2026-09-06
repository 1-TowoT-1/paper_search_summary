from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import inspect
from sqlalchemy.orm import Session

from app.llm.llm_client import LLMClient
from app.models.db import Paper, Project, ProjectPaper, ProjectQA
from app.models.schemas import ProjectSummaryResponse, SummaryResponse


class SummaryService:
    MAX_PROJECT_PAPERS = 20
    MAX_PROJECT_QAS = 20
    MAX_PAPER_ABSTRACT_CHARS = 600
    MAX_QA_ANSWER_CHARS = 700
    MAX_PROJECT_CONTEXT_CHARS = 18000

    def __init__(self) -> None:
        self.llm = LLMClient()

    async def summarize_paper(self, db: Session, paper_id: UUID) -> SummaryResponse:
        paper = db.get(Paper, paper_id)
        if paper is None:
            raise HTTPException(status_code=404, detail="Paper not found")

        markdown = await self.llm.summarize(self._paper_to_summary_text(paper))
        return SummaryResponse(paper_id=paper_id, markdown=markdown, cached=False)

    async def summarize_project(
        self,
        db: Session,
        project_id: UUID,
        user_id: UUID,
        summary_question: str | None = None,
    ) -> ProjectSummaryResponse:
        project = db.query(Project).filter(Project.id == project_id, Project.user_id == user_id).first()
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")

        papers = (
            db.query(Paper)
            .join(ProjectPaper, ProjectPaper.paper_id == Paper.id)
            .filter(ProjectPaper.project_id == project_id)
            .order_by(Paper.created_at.desc())
            .limit(self.MAX_PROJECT_PAPERS)
            .all()
        )
        qas = self._load_summary_qas(db=db, project_id=project_id, user_id=user_id)

        markdown = await self._generate_project_summary(
            project=project,
            papers=papers,
            qas=qas,
            summary_question=summary_question,
        )
        return ProjectSummaryResponse(
            project_id=project.id,
            project_name=project.name,
            markdown=markdown,
            paper_count=len(papers),
            qa_count=len(qas),
            summary_question=self._safe_text(summary_question) or None,
            cached=False,
        )

    def _paper_to_summary_text(self, paper: Paper) -> str:
        authors_data = paper.authors if isinstance(paper.authors, list) else []
        authors = ", ".join(str(author.get("name", "")) for author in authors_data if isinstance(author, dict))
        metadata_items = {
            "system_id": str(paper.id),
            "doi": paper.doi or "",
            "source": paper.source,
            "source_id": paper.source_id,
            "published_date": str(paper.published_date or ""),
            "pdf_url": paper.pdf_url or "",
            "citation_count": str(paper.citation_count),
        }
        metadata = "\n".join(f"{key}: {value}" for key, value in metadata_items.items() if value)
        return (
            f"Title: {self._safe_text(paper.title, fallback='Untitled paper')}\n"
            f"Authors: {authors or 'Unknown'}\n"
            f"{metadata}\n\n"
            f"Abstract:\n{paper.abstract or 'No abstract available.'}"
        ).strip()

    def _load_summary_qas(self, db: Session, project_id: UUID, user_id: UUID) -> list[object]:
        if self._project_qas_has_summary_context_columns(db):
            return (
                db.query(ProjectQA)
                .filter(ProjectQA.project_id == project_id, ProjectQA.user_id == user_id)
                .filter(ProjectQA.include_in_summary_context.is_(True))
                .order_by(ProjectQA.created_at.desc())
                .limit(self.MAX_PROJECT_QAS)
                .all()
            )

        return (
            db.query(ProjectQA.question, ProjectQA.answer, ProjectQA.created_at)
            .filter(ProjectQA.project_id == project_id, ProjectQA.user_id == user_id)
            .order_by(ProjectQA.created_at.desc())
            .limit(self.MAX_PROJECT_QAS)
            .all()
        )

    def _project_qas_has_summary_context_columns(self, db: Session) -> bool:
        try:
            bind = db.get_bind()
            columns = {column["name"] for column in inspect(bind).get_columns("project_qas")}
        except Exception:
            return False
        return {"include_in_summary_context", "summary_context_reason"}.issubset(columns)

    async def _generate_project_summary(
        self,
        project: Project,
        papers: list[Paper],
        qas: list[ProjectQA],
        summary_question: str | None = None,
    ) -> str:
        if not papers and not qas:
            return "当前项目还没有可用于总结的文献或问答记录。"

        paper_text = self._format_project_papers(papers)
        qa_text = self._format_project_qas(qas)
        summary_question_text = self._safe_text(
            summary_question,
            fallback="请基于当前项目资料和高价值历史问答，生成阶段性研究总结。",
        )
        system_prompt = (
            "你是科研项目阶段性总结助手。请基于项目文献摘要和项目问答记录生成中文 Markdown 总结。"
            "用户会给出本阶段想复盘的问题或目标。"
            "不要编造未提供的信息；如果证据不足，请明确指出。"
        )
        user_prompt = (
            f"项目名称：{self._safe_text(project.name, fallback='未命名项目')}\n"
            f"项目描述：{self._safe_text(project.description, fallback='无')}\n\n"
            f"本阶段总结问题：\n{summary_question_text}\n\n"
            "请按以下结构输出：\n"
            "## 阶段性结论\n"
            "## 已覆盖的研究主题\n"
            "## 关键证据与依据\n"
            "## 仍待澄清的问题\n"
            "## 下一步建议\n\n"
            f"项目文献摘要：\n{paper_text or '暂无'}\n\n"
            f"历史问答记录：\n{qa_text or '暂无'}"
        )
        user_prompt = self._truncate_text(user_prompt, self.MAX_PROJECT_CONTEXT_CHARS)

        try:
            return await self.llm._generate(system_prompt=system_prompt, user_prompt=user_prompt, max_output_tokens=1800)
        except Exception as exc:
            return self._fallback_project_summary(
                project=project,
                papers=papers,
                qas=qas,
                summary_question=summary_question,
                error=str(exc),
            )

    def _format_project_papers(self, papers: list[Paper]) -> str:
        parts: list[str] = []
        for index, paper in enumerate(papers, start=1):
            title = self._safe_text(paper.title, fallback="未命名文献")
            abstract = self._truncate_text(
                self._safe_text(paper.abstract, fallback="暂无摘要"),
                self.MAX_PAPER_ABSTRACT_CHARS,
            )
            source = self._safe_text(paper.source, fallback="unknown")
            source_id = self._safe_text(paper.source_id)
            doi = self._safe_text(paper.doi)
            meta = "；".join(item for item in [source, source_id, f"DOI: {doi}" if doi else ""] if item)
            parts.append(f"{index}. {title}\n来源：{meta or '未知'}\n摘要：{abstract}")
        return self._truncate_text("\n\n".join(parts), self.MAX_PROJECT_CONTEXT_CHARS // 2)

    def _format_project_qas(self, qas: list[ProjectQA]) -> str:
        parts: list[str] = []
        for index, qa in enumerate(qas, start=1):
            question = self._safe_text(qa.question, fallback="未记录问题")
            answer = self._truncate_text(
                self._safe_text(qa.answer, fallback="未记录回答"),
                self.MAX_QA_ANSWER_CHARS,
            )
            parts.append(f"{index}. Q: {question}\nA: {answer}")
        return self._truncate_text("\n\n".join(parts), self.MAX_PROJECT_CONTEXT_CHARS // 2)

    def _safe_text(self, value: object, fallback: str = "") -> str:
        text = str(value or "").strip()
        return text if text else fallback

    def _truncate_text(self, text: str, limit: int) -> str:
        value = str(text or "").strip()
        if len(value) <= limit:
            return value
        return value[:limit].rstrip() + "\n\n[内容过长，已截断]"

    def _fallback_project_summary(
        self,
        *,
        project: Project,
        papers: list[Paper],
        qas: list[ProjectQA],
        summary_question: str | None,
        error: str,
    ) -> str:
        paper_titles = [self._safe_text(paper.title, fallback="未命名文献") for paper in papers[:10]]
        qa_questions = [self._safe_text(qa.question, fallback="未记录问题") for qa in qas[:10]]
        paper_lines = "\n".join(f"- {title}" for title in paper_titles) or "- 暂无文献"
        qa_lines = "\n".join(f"- {question}" for question in qa_questions) or "- 暂无历史问答"
        return (
            f"## 阶段性结论\n"
            f"项目“{self._safe_text(project.name, fallback='未命名项目')}”当前包含 {len(papers)} 篇文献和 {len(qas)} 条历史问答记录。"
            f"本次大模型生成失败，以下为系统根据现有记录生成的兜底摘要。\n\n"
            f"本阶段问题：{self._safe_text(summary_question, fallback='未提供')}\n\n"
            f"## 已覆盖的研究主题\n{paper_lines}\n\n"
            f"## 关键证据与依据\n"
            f"当前兜底总结只列出已绑定文献和历史问题，未对证据强度做进一步判断。\n\n"
            f"## 仍待澄清的问题\n{qa_lines}\n\n"
            f"## 下一步建议\n"
            f"- 检查该项目是否存在超长问答记录、空回答或异常文献字段。\n"
            f"- 如需更完整总结，可在全文分块入库完成后重新生成。\n\n"
            f"调试信息：{self._truncate_text(error, 500)}"
        )
