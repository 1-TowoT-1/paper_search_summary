from uuid import UUID, uuid4

from app.llm.llm_client import LLMClient
from app.models.schemas import SummaryResponse, SummaryTaskResponse


class SummaryService:
    def __init__(self) -> None:
        self.llm = LLMClient()

    async def summarize_paper(self, paper_id: UUID) -> SummaryResponse:
        markdown = await self.llm.summarize(f"paper_id={paper_id}")
        return SummaryResponse(paper_id=paper_id, markdown=markdown, cached=False)

    async def enqueue_project_summary(self, project_id: UUID, user_id: UUID) -> SummaryTaskResponse:
        _ = (project_id, user_id)
        return SummaryTaskResponse(task_id=uuid4(), status="pending")

