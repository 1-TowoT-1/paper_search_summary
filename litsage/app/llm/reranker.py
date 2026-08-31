from app.models.schemas import SearchResult


def _tokens(text: str) -> set[str]:
    import re

    return {token.lower() for token in re.findall(r"[\w\u4e00-\u9fff]+", text) if len(token) >= 2}


class Reranker:
    async def rerank(self, query: str, results: list[SearchResult], limit: int) -> list[SearchResult]:
        query_tokens = _tokens(query)
        return sorted(results, key=lambda item: self._rerank_score(item, query_tokens), reverse=True)[:limit]

    def _rerank_score(self, item: SearchResult, query_tokens: set[str]) -> float:
        paper = item.paper
        title_tokens = _tokens(paper.title)
        abstract_tokens = _tokens(paper.abstract or "")
        author_tokens = _tokens(" ".join(str(author.get("name", "")) for author in paper.authors))

        title_overlap = len(query_tokens & title_tokens)
        abstract_overlap = len(query_tokens & abstract_tokens)
        author_overlap = len(query_tokens & author_tokens)
        citation_boost = min(paper.citation_count, 200) / 2000

        return item.score + title_overlap * 0.08 + abstract_overlap * 0.02 + author_overlap * 0.04 + citation_boost

