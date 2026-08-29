from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user_id, get_db
from app.models.db import Paper
from app.models.schemas import (
    ImportPapersRequest,
    ImportPapersResponse,
    ImportPreviewResponse,
    ImportSelectedPapersRequest,
    PaperDeleteResponse,
    PaperListResponse,
    PaperRead,
    SummaryResponse,
)
from app.services.paper_catalog_service import PaperCatalogFilters, PaperCatalogService
from app.services.paper_cleanup_service import PaperCleanupService
from app.services.paper_importer import PaperImporter
from app.services.summary_service import SummaryService

router = APIRouter()


@router.post("/import", response_model=ImportPapersResponse, status_code=status.HTTP_200_OK)
async def import_papers(
    payload: ImportPapersRequest,
    user_id: str = Depends(get_current_user_id),
) -> ImportPapersResponse:
    return await PaperImporter().enqueue_import(payload=payload, user_id=user_id)


@router.post("/import/preview", response_model=ImportPreviewResponse, status_code=status.HTTP_200_OK)
async def preview_import_papers(
    payload: ImportPapersRequest,
    user_id: str = Depends(get_current_user_id),
) -> ImportPreviewResponse:
    return await PaperImporter().preview_import(payload=payload, user_id=user_id)


@router.post("/import/selected", response_model=ImportPapersResponse, status_code=status.HTTP_200_OK)
async def import_selected_papers(
    payload: ImportSelectedPapersRequest,
    user_id: str = Depends(get_current_user_id),
) -> ImportPapersResponse:
    return await PaperImporter().import_selected(payload=payload, user_id=user_id)


@router.get("", response_model=PaperListResponse)
def list_papers(
    q: str | None = Query(default=None, min_length=1),
    title: str | None = None,
    doi: str | None = None,
    author: str | None = None,
    source: str | None = None,
    source_id: str | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _: str = Depends(get_current_user_id),
) -> PaperListResponse:
    filters = PaperCatalogFilters(
        q=q,
        title=title,
        doi=doi,
        author=author,
        source=source,
        source_id=source_id,
        year_from=year_from,
        year_to=year_to,
    )
    papers, total = PaperCatalogService().list_papers(db=db, filters=filters, limit=limit, offset=offset)
    return PaperListResponse(total=total, limit=limit, offset=offset, results=papers)


@router.get("/{paper_id}", response_model=PaperRead)
def get_paper(paper_id: UUID, db: Session = Depends(get_db), _: str = Depends(get_current_user_id)) -> Paper:
    paper = db.get(Paper, paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
    return paper


@router.get("/{paper_id}/summary", response_model=SummaryResponse)
async def get_paper_summary(
    paper_id: UUID,
    db: Session = Depends(get_db),
    _: str = Depends(get_current_user_id),
) -> SummaryResponse:
    return await SummaryService().summarize_paper(db=db, paper_id=paper_id)


@router.delete("/{paper_id}", response_model=PaperDeleteResponse)
async def delete_paper(
    paper_id: UUID,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> PaperDeleteResponse:
    result = await PaperCleanupService().delete_paper(db=db, paper_id=paper_id, user_id=UUID(user_id))
    if result is None:
        raise HTTPException(status_code=404, detail="Paper not found")
    return result
