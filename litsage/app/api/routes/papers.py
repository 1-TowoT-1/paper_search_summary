from uuid import UUID
import re

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user_id, get_db
from app.llm.llm_client import LLMClient
from app.models.db import Paper
from app.models.schemas import (
    BatchUploadMaterialResponse,
    ImportPapersRequest,
    ImportPapersResponse,
    ImportPreviewResponse,
    ImportSelectedPapersRequest,
    ManualMaterialRequest,
    PaperDeleteResponse,
    PaperListResponse,
    PaperRead,
    PublicationStatus,
    SummaryResponse,
    UploadMaterialItemResult,
    UploadMaterialResponse,
    Visibility,
)
from app.services.paper_catalog_service import PaperCatalogFilters, PaperCatalogService
from app.services.paper_cleanup_service import PaperCleanupService
from app.services.paper_importer import PaperImporter
from app.services.summary_service import SummaryService
from app.services.user_material_importer import MaterialIngestionError, UserMaterialImporter, parse_authors_json

router = APIRouter()


def _contains_cjk(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", text))


async def _expand_catalog_query(q: str | None) -> list[str]:
    if not q or not _contains_cjk(q):
        return []
    try:
        return [term for term in await LLMClient().rewrite_query(q) if term != q]
    except Exception:
        return []


def _parse_optional_uuid(value: str | None, field_name: str) -> UUID | None:
    if value is None or not value.strip():
        return None
    try:
        return UUID(value.strip())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"{field_name} must be a valid UUID") from exc


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


@router.post("/upload", response_model=UploadMaterialResponse, status_code=status.HTTP_200_OK)
async def upload_material(
    file: UploadFile = File(...),
    project_id: str | None = Form(default=None),
    title: str | None = Form(default=None),
    abstract: str | None = Form(default=None),
    authors_json: str | None = Form(default=None),
    publication_status: PublicationStatus = Form(default=PublicationStatus.unpublished),
    visibility: Visibility = Form(default=Visibility.private),
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> UploadMaterialResponse:
    try:
        authors = parse_authors_json(authors_json)
        parsed_project_id = _parse_optional_uuid(project_id, "project_id")
        return await UserMaterialImporter().upload_material(
            db=db,
            file=file,
            user_id=UUID(user_id),
            project_id=parsed_project_id,
            title=title,
            abstract=abstract,
            authors=authors,
            publication_status=publication_status,
            visibility=visibility,
        )
    except MaterialIngestionError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Material upload failed: {exc}") from exc


@router.post("/upload/batch", response_model=BatchUploadMaterialResponse, status_code=status.HTTP_200_OK)
async def upload_material_batch(
    files: list[UploadFile] = File(...),
    project_id: str | None = Form(default=None),
    title: str | None = Form(default=None),
    abstract: str | None = Form(default=None),
    authors_json: str | None = Form(default=None),
    publication_status: PublicationStatus = Form(default=PublicationStatus.unpublished),
    visibility: Visibility = Form(default=Visibility.private),
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> BatchUploadMaterialResponse:
    if not files:
        raise HTTPException(status_code=400, detail="At least one file is required")

    try:
        authors = parse_authors_json(authors_json)
        parsed_project_id = _parse_optional_uuid(project_id, "project_id")
    except MaterialIngestionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    importer = UserMaterialImporter()
    user_uuid = UUID(user_id)
    allow_manual_overrides = len(files) == 1
    results: list[UploadMaterialItemResult] = []

    for file in files:
        filename = file.filename or "unknown"
        try:
            response = await importer.upload_material(
                db=db,
                file=file,
                user_id=user_uuid,
                project_id=parsed_project_id,
                title=title if allow_manual_overrides else None,
                abstract=abstract if allow_manual_overrides else None,
                authors=authors,
                publication_status=publication_status,
                visibility=visibility,
            )
            results.append(
                UploadMaterialItemResult(
                    filename=filename,
                    ok=True,
                    paper_id=response.paper_id,
                    status=response.status,
                    message=response.message,
                    stats=response.stats,
                )
            )
        except MaterialIngestionError as exc:
            db.rollback()
            results.append(
                UploadMaterialItemResult(
                    filename=filename,
                    ok=False,
                    status="failed",
                    message=str(exc),
                    error=str(exc),
                )
            )
        except Exception as exc:
            db.rollback()
            error = f"Material upload failed: {exc}"
            results.append(
                UploadMaterialItemResult(
                    filename=filename,
                    ok=False,
                    status="failed",
                    message=error,
                    error=error,
                )
            )

    succeeded = sum(1 for item in results if item.ok)
    failed = len(results) - succeeded
    response_status = "completed" if failed == 0 else "partial_failed"
    if succeeded == 0:
        response_status = "failed"

    return BatchUploadMaterialResponse(
        status=response_status,
        message=f"Uploaded {succeeded}/{len(results)} materials",
        total=len(results),
        succeeded=succeeded,
        failed=failed,
        results=results,
    )


@router.post("/manual", response_model=UploadMaterialResponse, status_code=status.HTTP_200_OK)
async def create_manual_material(
    payload: ManualMaterialRequest,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> UploadMaterialResponse:
    try:
        return await UserMaterialImporter().create_manual_material(db=db, payload=payload, user_id=UUID(user_id))
    except MaterialIngestionError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Manual material creation failed: {exc}") from exc


@router.get("", response_model=PaperListResponse)
async def list_papers(
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
    q_terms = await _expand_catalog_query(q)
    filters = PaperCatalogFilters(
        q=q,
        q_terms=q_terms,
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
