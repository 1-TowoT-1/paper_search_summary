import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import date
from uuid import UUID

from app.config import settings
from app.core.redis_client import redis_client
from app.llm.llm_client import LLMClient
from app.llm.reranker import Reranker
from app.models.db import Paper, SessionLocal
from app.models.schemas import (
    ExternalSearchResult,
    ImportPapersRequest,
    LiteratureSource,
    PaperRead,
    SearchResponse,
    SearchResult,
)
from app.services.embedding_service import EmbeddingService
from app.services.paper_importer import ImportedPaper, ImportStats, PaperImporter
from app.services.vector_store import VectorHit, VectorStore
from sqlalchemy import String, cast
from sqlalchemy.orm import Session


@dataclass
class SearchFilters:
    year_from: int | None = None
    year_to: int | None = None
    author: str | None = None
    source: str | None = None
    journal: str | None = None
    citation_min: int | None = None
    citation_max: int | None = None
    external_sources: tuple[LiteratureSource, ...] = (LiteratureSource.pubmed, LiteratureSource.arxiv)


class SearchService:
    def __init__(self) -> None:
        self.llm = LLMClient()
        self.embeddings = EmbeddingService()
        self._vector_store: VectorStore | None = None
        self.importer = PaperImporter()
        self.reranker = Reranker()

    @property
    def vector_store(self) -> VectorStore:
        if self._vector_store is None:
            self._vector_store = VectorStore()
        return self._vector_store

    async def rewrite_query(self, query: str) -> list[str]:
        variants = await self.llm.rewrite_query(query)
        return list(dict.fromkeys([query, *variants]))[:3]

    async def search(self, query: str, filters: SearchFilters, limit: int, user_id: str) -> SearchResponse:
        cache_key = self._cache_key(query=query, filters=filters, limit=limit, user_id=user_id)
        cached = await self._get_cached(cache_key)
        if cached:
            response = SearchResponse.model_validate(cached)
            response.cache_hit = True
            return response

        rewritten_queries = await self.rewrite_query(query)
        merged_hits: dict[UUID, VectorHit] = {}

        for rewritten in rewritten_queries:
            vector = await self.embeddings.embed_text(rewritten)
            hits = await self.vector_store.search_abstracts(vector=vector, limit=100)
            self._merge_hits(merged_hits, hits)

        candidates = self._load_candidates(
            scores={paper_id: hit.score for paper_id, hit in merged_hits.items()},
            filters=filters,
            query=query,
        )
        filtered_candidates = self._filter_by_score_threshold(candidates)
        total = len(filtered_candidates)
        ranked = await self.reranker.rerank(query=query, results=filtered_candidates, limit=limit)
        external_results, external_stats = await self._external_fallback_if_needed(
            query=query,
            rewritten_queries=rewritten_queries,
            filters=filters,
            local_results=ranked,
            limit=limit,
        )

        response = SearchResponse(
            query=query,
            rewritten_queries=rewritten_queries,
            total=total,
            results=ranked,
            external_total=len(external_results),
            external_results=external_results,
            external_stats=external_stats,
            used_external_fallback=bool(external_results),
            cache_hit=False,
        )
        await self._set_cached(cache_key, response)
        return response

    def _merge_hits(self, merged: dict[UUID, VectorHit], hits: list[VectorHit]) -> None:
        for hit in hits:
            current = merged.get(hit.paper_id)
            if current is None or hit.score > current.score:
                merged[hit.paper_id] = hit

    def _load_candidates(self, scores: dict[UUID, float], filters: SearchFilters, query: str) -> list[SearchResult]:
        if not scores:
            return []

        db = SessionLocal()
        try:
            papers = self._query_papers(db=db, paper_ids=list(scores.keys()), filters=filters)
            return [
                SearchResult(
                    paper=PaperRead.model_validate(paper),
                    score=scores[paper.id],
                    highlights=self._build_highlights(query_text=query, paper=paper),
                )
                for paper in papers
            ]
        finally:
            db.close()

    def _query_papers(self, db: Session, paper_ids: list[UUID], filters: SearchFilters) -> list[Paper]:
        query = db.query(Paper).filter(Paper.id.in_(paper_ids))
        if filters.year_from:
            query = query.filter(Paper.published_date >= date(filters.year_from, 1, 1))
        if filters.year_to:
            query = query.filter(Paper.published_date <= date(filters.year_to, 12, 31))
        if filters.author:
            query = query.filter(cast(Paper.authors, String).ilike(f"%{filters.author}%"))
        if filters.source:
            query = query.filter(Paper.source == filters.source)
        if filters.journal:
            query = query.filter(cast(Paper.metadata_json, String).ilike(f"%{filters.journal}%"))
        if filters.citation_min is not None:
            query = query.filter(Paper.citation_count >= filters.citation_min)
        if filters.citation_max is not None:
            query = query.filter(Paper.citation_count <= filters.citation_max)
        return query.all()

    def _build_highlights(self, query_text: str, paper: Paper) -> list[str]:
        snippets: list[str] = []
        title = paper.title.strip()
        abstract = (paper.abstract or "").strip()
        if title:
            snippets.append(title[:220])
        if abstract:
            snippets.append(self._snippet(abstract, query_text))
        return snippets[:2]

    def _snippet(self, text: str, query: str, window: int = 220) -> str:
        terms = [term.lower() for term in re.findall(r"[\w\u4e00-\u9fff]+", query) if len(term) >= 2]
        lowered = text.lower()
        for term in terms:
            index = lowered.find(term)
            if index >= 0:
                start = max(0, index - 80)
                end = min(len(text), start + window)
                prefix = "..." if start else ""
                suffix = "..." if end < len(text) else ""
                return f"{prefix}{text[start:end]}{suffix}"
        return text[:window] + ("..." if len(text) > window else "")

    def _cache_key(self, query: str, filters: SearchFilters, limit: int, user_id: str) -> str:
        payload = {
            "query": query,
            "filters": self._filters_for_cache(filters),
            "limit": limit,
            "user_id": user_id,
            "local_min_results": settings.search_local_min_results,
            "local_min_score": settings.search_local_min_score,
            "external_candidate_multiplier": settings.search_external_candidate_multiplier,
        }
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()
        return f"search:{digest}"

    def _filters_for_cache(self, filters: SearchFilters) -> dict:
        data = asdict(filters)
        data["external_sources"] = [source.value for source in filters.external_sources]
        return data

    async def _external_fallback_if_needed(
        self,
        query: str,
        rewritten_queries: list[str],
        filters: SearchFilters,
        local_results: list[SearchResult],
        limit: int,
    ) -> tuple[list[ExternalSearchResult], dict[str, int | list[str]]]:
        external_stats: dict[str, int | list[str]] = {
            "needed": 0,
            "fetched": 0,
            "accepted": 0,
            "filtered_duplicate": 0,
            "filtered_year": 0,
            "filtered_author": 0,
            "filtered_source": 0,
            "filtered_journal": 0,
            "filtered_citation": 0,
            "errors": [],
        }
        if not self._needs_external_fallback(local_results=local_results, requested_limit=limit):
            return [], external_stats

        stats = ImportStats()
        external_limit = self._external_limit(local_count=len(local_results), requested_limit=limit)
        external_stats["needed"] = external_limit
        if external_limit <= 0:
            return [], external_stats

        imported = await self._fetch_external_for_queries(
            queries=self._external_queries(query=query, rewritten_queries=rewritten_queries),
            filters=filters,
            limit=external_limit,
            stats=stats,
        )
        external_stats["fetched"] = len(imported)
        external_stats["errors"] = stats.values.get("errors", [])
        local_keys = {
            (result.paper.source, result.paper.source_id)
            for result in local_results
        }
        external_results: list[ExternalSearchResult] = []
        for paper in imported:
            if (paper.source, paper.source_id) in local_keys:
                self._inc_external_stat(external_stats, "filtered_duplicate")
                continue
            reject_reason = self._external_candidate_reject_reason(paper=paper, filters=filters)
            if reject_reason:
                self._inc_external_stat(external_stats, reject_reason)
                continue
            candidate = self.importer._to_candidate(paper)
            external_results.append(
                ExternalSearchResult(
                    paper=candidate,
                    source=paper.source,
                    score=None,
                    reason="external fallback because local results were sparse or low confidence",
                )
            )
            if len(external_results) >= external_limit:
                break
        external_stats["accepted"] = len(external_results)
        return external_results, external_stats

    def _needs_external_fallback(self, local_results: list[SearchResult], requested_limit: int) -> bool:
        if len(local_results) < min(requested_limit, settings.search_local_min_results):
            return True
        top_score = max((result.score for result in local_results), default=0.0)
        return top_score < settings.search_local_min_score

    def _filter_by_score_threshold(self, results: list[SearchResult]) -> list[SearchResult]:
        return [result for result in results if result.score >= settings.search_local_min_score]

    def _external_sources_for_filters(self, filters: SearchFilters) -> list[LiteratureSource]:
        if filters.source:
            for source in LiteratureSource:
                if filters.source == source.value:
                    return [source]
        return list(filters.external_sources)

    def _external_limit(self, local_count: int, requested_limit: int) -> int:
        return max(0, requested_limit - local_count)

    async def _fetch_external_for_queries(
        self,
        queries: list[str],
        filters: SearchFilters,
        limit: int,
        stats: ImportStats,
    ) -> list[ImportedPaper]:
        imported: list[ImportedPaper] = []
        seen: set[tuple[str, str]] = set()
        per_query_limit = max(1, limit)
        for external_query in queries:
            payload = ImportPapersRequest(
                query=external_query,
                sources=self._external_sources_for_filters(filters),
                limit=per_query_limit,
                include_pdf=False,
            )
            papers = await self.importer.fetch_from_sources(
                payload=payload,
                stats=stats,
                year_from=filters.year_from,
                year_to=filters.year_to,
            )
            for paper in papers:
                key = (paper.source, paper.source_id)
                if key in seen:
                    continue
                seen.add(key)
                imported.append(paper)
        return self.importer._rank_external_candidates(query=queries[0], papers=imported)[:limit]

    def _external_queries(self, query: str, rewritten_queries: list[str]) -> list[str]:
        english_queries = [item for item in rewritten_queries if not self._contains_cjk(item)]
        selected = english_queries or rewritten_queries or [query]
        return list(dict.fromkeys(selected))[:3]

    def _contains_cjk(self, text: str) -> bool:
        return bool(re.search(r"[\u4e00-\u9fff]", text))

    def _external_candidate_reject_reason(self, paper: ImportedPaper, filters: SearchFilters) -> str | None:
        if filters.year_from and (paper.published_date is None or paper.published_date.year < filters.year_from):
            return "filtered_year"
        if filters.year_to and (paper.published_date is None or paper.published_date.year > filters.year_to):
            return "filtered_year"
        if filters.author:
            author_text = " ".join(str(author.get("name", "")) for author in paper.authors).lower()
            if filters.author.lower() not in author_text:
                return "filtered_author"
        if filters.source and paper.source != filters.source:
            return "filtered_source"
        if filters.journal:
            journal = str(paper.metadata.get("journal") or paper.metadata.get("journal_iso") or "").lower()
            if filters.journal.lower() not in journal:
                return "filtered_journal"
        if filters.citation_min is not None and paper.citation_count < filters.citation_min:
            return "filtered_citation"
        if filters.citation_max is not None and paper.citation_count > filters.citation_max:
            return "filtered_citation"
        return None

    def _inc_external_stat(self, stats: dict[str, int | list[str]], key: str) -> None:
        value = stats.get(key, 0)
        if isinstance(value, int):
            stats[key] = value + 1

    async def _get_cached(self, key: str) -> dict | None:
        try:
            cached = await redis_client.get_json(key)
            return cached if isinstance(cached, dict) else None
        except Exception:
            return None

    async def _set_cached(self, key: str, response: SearchResponse) -> None:
        try:
            await redis_client.set_json(key, response.model_dump(mode="json"), settings.search_cache_ttl_seconds)
        except Exception:
            return

