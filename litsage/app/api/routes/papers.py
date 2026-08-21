from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user_id, get_db
from app.models.db import Paper
from app.models.schemas import ImportPapersRequest, ImportPapersResponse, PaperRead, SummaryResponse
from app.services.paper_importer import PaperImporter
from app.services.summary_service import SummaryService

router = APIRouter()


@router.post("/import", response_model=ImportPapersResponse, status_code=status.HTTP_202_ACCEPTED)
async def import_papers(
    payload: ImportPapersRequest,
    user_id: str = Depends(get_current_user_id),
) -> ImportPapersResponse:
    return await PaperImporter().enqueue_import(payload=payload, user_id=user_id)


@router.get("/{paper_id}", response_model=PaperRead)
def get_paper(paper_id: UUID, db: Session = Depends(get_db), _: str = Depends(get_current_user_id)) -> Paper:
    paper = db.get(Paper, paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
    return paper


@router.get("/{paper_id}/summary", response_model=SummaryResponse)
async def get_paper_summary(
    paper_id: UUID,
    _: str = Depends(get_current_user_id),
) -> SummaryResponse:
    return await SummaryService().summarize_paper(paper_id=paper_id)

