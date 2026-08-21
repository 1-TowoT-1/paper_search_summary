import hashlib
from dataclasses import dataclass

from app.config import settings
from app.llm.llm_client import LLMClient
from app.llm.reranker import Reranker
from app.models.schemas import SearchResponse
from app.services.embedding_service import EmbeddingService
from app.services.vector_store import VectorStore


@dataclass
class SearchFilters:
    year_from: int | None = None
    year_to: int | None = None
    author: str | None = None
    source: str | None = None


class SearchService:
    def __init__(self) -> None:
        self.llm = LLMClient()
        self.embeddings = EmbeddingService()
        self.vector_store = VectorStore()
        self.reranker = Reranker()

    async def rewrite_query(self, query: str) -> list[str]:
        variants = await self.llm.rewrite_query(query)
        return list(dict.fromkeys([query, *variants]))[:3]

    async def search(self, query: str, filters: SearchFilters, limit: int, user_id: str) -> SearchResponse:
        _ = (filters, user_id, settings.search_cache_ttl_seconds)
        rewritten_queries = await self.rewrite_query(query)
        merged_results = []

        for rewritten in rewritten_queries:
            vector = await self.embeddings.embed_text(rewritten)
            hits = await self.vector_store.search_abstracts(vector=vector, limit=100)
            merged_results.extend(hits)

        # Metadata hydration from PostgreSQL belongs here once Milvus is connected.
        cache_key = hashlib.sha256(query.encode("utf-8")).hexdigest()
        _ = cache_key
        ranked = await self.reranker.rerank(query=query, results=[], limit=limit)
        return SearchResponse(
            query=query,
            rewritten_queries=rewritten_queries,
            total=len(ranked),
            results=ranked,
            cache_hit=False,
        )

