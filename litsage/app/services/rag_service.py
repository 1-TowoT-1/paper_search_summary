import json
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from sqlalchemy import inspect, or_, text
from sqlalchemy.orm import Session

from app.llm.llm_client import LLMClient
from app.models.db import Paper, PaperChunk, Project, ProjectPaper, ProjectQA
from app.models.schemas import Citation, QARequest, QAResponse, QAScope
from app.services.embedding_service import EmbeddingService
from app.services.vector_store import VectorHit, VectorStore


MAX_CONTEXT_CHUNKS = 10
MIN_CONTEXT_ITEMS = 4


class RAGService:
    def __init__(self) -> None:
        self.llm = LLMClient()
        self.embeddings = EmbeddingService()
        self.vector_store = VectorStore()

    async def answer(self, db: Session, payload: QARequest, user_id: str) -> QAResponse:
        user_uuid = UUID(user_id)
        paper_ids = self._resolve_scope_paper_ids(db=db, payload=payload, user_id=user_uuid)
        if not paper_ids:
            return QAResponse(
                answer="当前范围内没有可用于问答的文献。请先导入资料，或检查项目/文献选择。",
                citations=[],
                session_id=payload.session_id or str(uuid4()),
            )

        vector = await self.embeddings.embed_text(payload.question)
        hits = await self.vector_store.search_chunks(vector=vector, paper_ids=paper_ids, limit=MAX_CONTEXT_CHUNKS)
        evidence = self._load_evidence(db=db, hits=hits, user_id=user_uuid, allowed_paper_ids=set(paper_ids))
        if len(evidence) < MIN_CONTEXT_ITEMS:
            evidence.extend(
                self._load_abstract_evidence(
                    db=db,
                    user_id=user_uuid,
                    allowed_paper_ids=set(paper_ids),
                    existing_paper_ids={item["paper_id"] for item in evidence},
                    limit=MIN_CONTEXT_ITEMS - len(evidence),
                )
            )
        context = self._build_context(evidence)
        answer = await self.llm.answer(question=payload.question, context=context)
        citations = self._build_citations(evidence)
        if payload.scope == QAScope.project and payload.project_id:
            await self._record_project_qa(
                db=db,
                project_id=payload.project_id,
                user_id=user_uuid,
                question=payload.question,
                answer=answer,
                citations=citations,
            )
        return QAResponse(answer=answer, citations=citations, session_id=payload.session_id or str(uuid4()))

    def _resolve_scope_paper_ids(self, db: Session, payload: QARequest, user_id: UUID) -> list[UUID]:
        if payload.scope == QAScope.project:
            if not payload.project_id:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="project_id is required for project QA")
            project = db.query(Project).filter(Project.id == payload.project_id, Project.user_id == user_id).first()
            if not project:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
            rows = db.query(ProjectPaper.paper_id).filter(ProjectPaper.project_id == payload.project_id).all()
            return [row[0] for row in rows]

        if payload.scope == QAScope.paper:
            requested_ids = [payload.paper_id] if payload.paper_id else payload.paper_ids
            if not requested_ids:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="paper_id or paper_ids is required for paper QA")
            return self._filter_accessible_paper_ids(db=db, paper_ids=requested_ids, user_id=user_id)

        if payload.scope == QAScope.search_results:
            if not payload.paper_ids:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="paper_ids is required for search_results QA")
            return self._filter_accessible_paper_ids(db=db, paper_ids=payload.paper_ids, user_id=user_id)

        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported QA scope")

    def _filter_accessible_paper_ids(self, db: Session, paper_ids: list[UUID], user_id: UUID) -> list[UUID]:
        unique_ids = list(dict.fromkeys(paper_ids))
        if not unique_ids:
            return []
        rows = (
            db.query(Paper.id)
            .filter(Paper.id.in_(unique_ids))
            .filter(or_(Paper.visibility == "public", Paper.owner_user_id == user_id))
            .all()
        )
        accessible = {row[0] for row in rows}
        return [paper_id for paper_id in unique_ids if paper_id in accessible]

    def _load_evidence(
        self,
        db: Session,
        hits: list[VectorHit],
        user_id: UUID,
        allowed_paper_ids: set[UUID],
    ) -> list[dict]:
        chunk_ids: list[UUID] = []
        for hit in hits:
            if not hit.chunk_id:
                continue
            try:
                chunk_ids.append(UUID(hit.chunk_id))
            except ValueError:
                continue
        chunks_by_id: dict[str, tuple[PaperChunk, Paper]] = {}
        if chunk_ids:
            rows = (
                db.query(PaperChunk, Paper)
                .join(Paper, Paper.id == PaperChunk.paper_id)
                .filter(PaperChunk.id.in_(chunk_ids))
                .filter(Paper.id.in_(allowed_paper_ids))
                .filter(or_(Paper.visibility == "public", Paper.owner_user_id == user_id))
                .all()
            )
            chunks_by_id = {str(chunk.id): (chunk, paper) for chunk, paper in rows}

        evidence: list[dict] = []
        for hit in hits:
            if hit.paper_id not in allowed_paper_ids:
                continue
            chunk_paper = chunks_by_id.get(hit.chunk_id or "")
            if chunk_paper:
                chunk, paper = chunk_paper
                if self._is_unusable_evidence_text(chunk.text):
                    continue
                locator = self._format_locator(chunk=chunk, fallback=hit.locator)
                evidence.append(
                    {
                        "paper_id": paper.id,
                        "title": paper.title,
                        "chunk_id": str(chunk.id),
                        "locator": locator,
                        "text": chunk.text,
                        "score": hit.score,
                    }
                )
            elif hit.text:
                if self._is_unusable_evidence_text(hit.text):
                    continue
                paper = db.query(Paper).filter(Paper.id == hit.paper_id).first()
                if paper and (paper.visibility == "public" or paper.owner_user_id == user_id):
                    evidence.append(
                        {
                            "paper_id": paper.id,
                            "title": paper.title,
                            "chunk_id": hit.chunk_id,
                            "locator": hit.locator,
                            "text": hit.text,
                            "score": hit.score,
                        }
                    )
        return evidence

    def _load_abstract_evidence(
        self,
        db: Session,
        user_id: UUID,
        allowed_paper_ids: set[UUID],
        existing_paper_ids: set[UUID],
        limit: int,
    ) -> list[dict]:
        if limit <= 0:
            return []

        papers = (
            db.query(Paper)
            .filter(Paper.id.in_(allowed_paper_ids))
            .filter(~Paper.id.in_(existing_paper_ids) if existing_paper_ids else True)
            .filter(or_(Paper.visibility == "public", Paper.owner_user_id == user_id))
            .order_by(Paper.published_date.desc().nullslast(), Paper.created_at.desc())
            .limit(limit)
            .all()
        )

        evidence: list[dict] = []
        for paper in papers:
            text = self._paper_abstract_context(paper)
            if not text or self._is_unusable_evidence_text(text):
                continue
            evidence.append(
                {
                    "paper_id": paper.id,
                    "title": paper.title,
                    "chunk_id": None,
                    "locator": "abstract",
                    "text": text,
                    "score": 0.0,
                }
            )
        return evidence

    def _build_context(self, evidence: list[dict]) -> str:
        parts: list[str] = []
        for index, item in enumerate(evidence, start=1):
            locator = f"，位置：{item['locator']}" if item.get("locator") else ""
            parts.append(
                f"[来源 {index}] {item['title']}{locator}\n"
                f"paper_id={item['paper_id']} chunk_id={item.get('chunk_id') or ''}\n"
                f"{item['text']}"
            )
        return "\n\n".join(parts)

    def _build_citations(self, evidence: list[dict]) -> list[Citation]:
        citations: list[Citation] = []
        seen: set[tuple[UUID, str | None]] = set()
        for item in evidence:
            key = (item["paper_id"], item.get("chunk_id"))
            if key in seen:
                continue
            seen.add(key)
            citations.append(
                Citation(
                    paper_id=item["paper_id"],
                    title=item["title"],
                    chunk_id=item.get("chunk_id"),
                    locator=item.get("locator"),
                )
            )
        return citations

    async def _record_project_qa(
        self,
        db: Session,
        project_id: UUID,
        user_id: UUID,
        question: str,
        answer: str,
        citations: list[Citation],
    ) -> None:
        assessment = await self.llm.assess_project_qa_summary_context(question=question, answer=answer)
        citations_payload = [citation.model_dump(mode="json") for citation in citations]
        if self._project_qas_has_summary_context_columns(db):
            db.add(
                ProjectQA(
                    id=uuid4(),
                    project_id=project_id,
                    user_id=user_id,
                    question=question,
                    answer=answer,
                    citations_json=citations_payload,
                    include_in_summary_context=bool(assessment.get("include")),
                    summary_context_reason=str(assessment.get("reason") or ""),
                )
            )
        else:
            db.execute(
                text(
                    """
                    INSERT INTO project_qas (id, project_id, user_id, question, answer, citations, created_at)
                    VALUES (:id, :project_id, :user_id, :question, :answer, CAST(:citations AS jsonb), now())
                    """
                ),
                {
                    "id": uuid4(),
                    "project_id": project_id,
                    "user_id": user_id,
                    "question": question,
                    "answer": answer,
                    "citations": json.dumps(citations_payload),
                },
            )
        db.commit()

    def _project_qas_has_summary_context_columns(self, db: Session) -> bool:
        try:
            bind = db.get_bind()
            columns = {column["name"] for column in inspect(bind).get_columns("project_qas")}
        except Exception:
            return True
        return {"include_in_summary_context", "summary_context_reason"}.issubset(columns)

    def _format_locator(self, chunk: PaperChunk, fallback: str | None) -> str | None:
        if chunk.page_start and chunk.page_end and chunk.page_start != chunk.page_end:
            return f"pages:{chunk.page_start}-{chunk.page_end}"
        if chunk.page_start:
            return f"page:{chunk.page_start}"
        return fallback or f"chunk:{chunk.chunk_index}"

    def _paper_abstract_context(self, paper: Paper) -> str:
        parts = [f"标题：{paper.title}"]
        if paper.authors:
            authors = ", ".join(str(author.get("name", "")) for author in paper.authors if isinstance(author, dict))
            if authors:
                parts.append(f"作者：{authors}")
        if paper.published_date:
            parts.append(f"发表日期：{paper.published_date}")
        if paper.doi:
            parts.append(f"DOI：{paper.doi}")
        if paper.abstract:
            parts.append(f"摘要：{paper.abstract}")
        return "\n".join(parts)

    def _is_unusable_evidence_text(self, text: str | None) -> bool:
        value = str(text or "").strip()
        if not value:
            return True
        lowered = value.lower()
        markers = (
            "[unsupported image]",
            "unsupported image",
            "[无法识别]",
            "无法看到上传的图片内容",
            "图片显示为",
            "无法读取图片内容",
            "无法识别图片内容",
            "不能读取图片",
            "不支持图片",
            "图片格式不被支持",
            "未能成功上传",
            "重新上传",
            "直接上传可读取的 pdf",
            "收到可用的图片后",
        )
        if any(marker in lowered for marker in markers):
            return True
        return False
