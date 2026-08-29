from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.llm.llm_client import LLMClient
from app.models.db import Paper
from app.models.schemas import SummaryResponse, SummaryTaskResponse


class SummaryService:
    def __init__(self) -> None:
        self.llm = LLMClient()

    async def summarize_paper(self, db: Session, paper_id: UUID) -> SummaryResponse:
        paper = db.get(Paper, paper_id)
        if paper is None:
            raise HTTPException(status_code=404, detail="Paper not found")

        markdown = await self.llm.summarize(self._paper_to_summary_text(paper))
        return SummaryResponse(paper_id=paper_id, markdown=markdown, cached=False)

    async def enqueue_project_summary(self, project_id: UUID, user_id: UUID) -> SummaryTaskResponse:
        _ = (project_id, user_id)
        return SummaryTaskResponse(task_id=uuid4(), status="pending")

    def _paper_to_summary_text(self, paper: Paper) -> str:
        authors = ", ".join(str(author.get("name", "")) for author in paper.authors if isinstance(author, dict))
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
            f"Title: {paper.title}\n"
            f"Authors: {authors or 'Unknown'}\n"
            f"{metadata}\n\n"
            f"Abstract:\n{paper.abstract or 'No abstract available.'}"
        ).strip()

