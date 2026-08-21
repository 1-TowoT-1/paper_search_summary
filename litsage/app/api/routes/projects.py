from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user_id, get_db
from app.models.db import Project, ProjectPaper
from app.models.schemas import AddProjectPaperRequest, ProjectCreate, ProjectRead, SummaryTaskResponse
from app.services.summary_service import SummaryService

router = APIRouter()


@router.post("", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
def create_project(
    payload: ProjectCreate,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> Project:
    project = Project(id=uuid4(), user_id=UUID(user_id), name=payload.name, description=payload.description)
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@router.get("", response_model=list[ProjectRead])
def list_projects(db: Session = Depends(get_db), user_id: str = Depends(get_current_user_id)) -> list[Project]:
    return db.query(Project).filter(Project.user_id == UUID(user_id)).order_by(Project.created_at.desc()).all()


@router.post("/{project_id}/papers", status_code=status.HTTP_204_NO_CONTENT)
def add_paper_to_project(
    project_id: UUID,
    payload: AddProjectPaperRequest,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> None:
    project = db.query(Project).filter(Project.id == project_id, Project.user_id == UUID(user_id)).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    db.merge(ProjectPaper(project_id=project_id, paper_id=payload.paper_id))
    db.commit()


@router.post("/{project_id}/summary", response_model=SummaryTaskResponse, status_code=status.HTTP_202_ACCEPTED)
async def summarize_project(project_id: UUID, user_id: str = Depends(get_current_user_id)) -> SummaryTaskResponse:
    return await SummaryService().enqueue_project_summary(project_id=project_id, user_id=UUID(user_id))

