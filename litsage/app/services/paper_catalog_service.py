from dataclasses import dataclass

from sqlalchemy import String, cast, func, or_
from sqlalchemy.orm import Session

from app.models.db import Paper


@dataclass
class PaperCatalogFilters:
    q: str | None = None
    title: str | None = None
    doi: str | None = None
    author: str | None = None
    source: str | None = None
    source_id: str | None = None
    year_from: int | None = None
    year_to: int | None = None


class PaperCatalogService:
    def list_papers(
        self,
        db: Session,
        filters: PaperCatalogFilters,
        limit: int,
        offset: int,
    ) -> tuple[list[Paper], int]:
        query = db.query(Paper)

        if filters.q:
            value = self._like(filters.q)
            query = query.filter(
                or_(
                    Paper.title.ilike(value),
                    Paper.abstract.ilike(value),
                    Paper.doi.ilike(value),
                    Paper.source_id.ilike(value),
                    cast(Paper.authors, String).ilike(value),
                )
            )
        if filters.title:
            query = query.filter(Paper.title.ilike(self._like(filters.title)))
        if filters.doi:
            query = query.filter(Paper.doi.ilike(self._like(filters.doi)))
        if filters.author:
            query = query.filter(cast(Paper.authors, String).ilike(self._like(filters.author)))
        if filters.source:
            query = query.filter(Paper.source == filters.source)
        if filters.source_id:
            query = query.filter(Paper.source_id.ilike(self._like(filters.source_id)))
        if filters.year_from:
            query = query.filter(func.extract("year", Paper.published_date) >= filters.year_from)
        if filters.year_to:
            query = query.filter(func.extract("year", Paper.published_date) <= filters.year_to)

        total = query.count()
        papers = (
            query.order_by(Paper.published_date.desc().nullslast(), Paper.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return papers, total

    def _like(self, value: str) -> str:
        return f"%{value.strip()}%"
