from fastapi import APIRouter, Depends, Query

from app.api.dependencies import get_current_user_id
from app.models.schemas import QueryRewriteResponse, SearchResponse
from app.services.search_service import SearchFilters, SearchService

router = APIRouter()


@router.get("", response_model=SearchResponse)
async def semantic_search(
    q: str = Query(..., min_length=2),
    year_from: int | None = None,
    year_to: int | None = None,
    author: str | None = None,
    source: str | None = None,
    journal: str | None = None,
    citation_min: int | None = Query(default=None, ge=0),
    citation_max: int | None = Query(default=None, ge=0),
    limit: int = Query(default=20, ge=1, le=50),
    user_id: str = Depends(get_current_user_id),
) -> SearchResponse:
    filters = SearchFilters(
        year_from=year_from,
        year_to=year_to,
        author=author,
        source=source,
        journal=journal,
        citation_min=citation_min,
        citation_max=citation_max,
    )
    return await SearchService().search(query=q, filters=filters, limit=limit, user_id=user_id)


@router.post("/rewrite", response_model=QueryRewriteResponse)
async def rewrite_query(q: str = Query(..., min_length=2)) -> QueryRewriteResponse:
    variants = await SearchService().rewrite_query(q)
    return QueryRewriteResponse(original=q, variants=variants)

