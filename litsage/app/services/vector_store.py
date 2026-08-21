from dataclasses import dataclass
from uuid import UUID


@dataclass
class VectorHit:
    paper_id: UUID
    score: float
    chunk_id: str | None = None
    text: str | None = None
    locator: str | None = None


class VectorStore:
    async def upsert_paper_abstract(self, paper_id: UUID, vector: list[float], metadata: dict) -> None:
        """Persist abstract vectors in Milvus in production."""

    async def upsert_chunk(self, paper_id: UUID, chunk_id: str, vector: list[float], text: str, metadata: dict) -> None:
        """Persist full-text chunk vectors in Milvus in production."""

    async def search_abstracts(self, vector: list[float], limit: int) -> list[VectorHit]:
        return []

    async def search_chunks(self, vector: list[float], paper_ids: list[UUID], limit: int = 10) -> list[VectorHit]:
        return []

