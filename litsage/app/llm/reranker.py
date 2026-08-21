from app.models.schemas import SearchResult


class Reranker:
    async def rerank(self, query: str, results: list[SearchResult], limit: int) -> list[SearchResult]:
        return sorted(results, key=lambda item: item.score, reverse=True)[:limit]

