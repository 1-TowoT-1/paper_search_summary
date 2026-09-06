from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import inspect, or_, text
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user_id, get_db
from app.models.db import Paper, Project, ProjectPaper, ProjectQA
from app.models.schemas import (
    AddProjectPaperRequest,
    AddProjectPapersRequest,
    AddProjectPapersResponse,
    DeleteProjectQAsRequest,
    DeleteProjectQAsResponse,
    PaperRead,
    ProjectCreate,
    ProjectPapersResponse,
    ProjectQAListResponse,
    ProjectQARead,
    ProjectRead,
    ProjectSummaryRequest,
    ProjectSummaryResponse,
    RemoveProjectPapersRequest,
    RemoveProjectPapersResponse,
)
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


def _get_user_project(db: Session, project_id: UUID, user_id: UUID) -> Project:
    project = db.query(Project).filter(Project.id == project_id, Project.user_id == user_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def _project_qas_has_summary_context_columns(db: Session) -> bool:
    try:
        columns = {column["name"] for column in inspect(db.get_bind()).get_columns("project_qas")}
    except Exception:
        return False
    return {"include_in_summary_context", "summary_context_reason"}.issubset(columns)


@router.get("/{project_id}/papers", response_model=ProjectPapersResponse)
def list_project_papers(
    project_id: UUID,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> ProjectPapersResponse:
    user_uuid = UUID(user_id)
    _get_user_project(db=db, project_id=project_id, user_id=user_uuid)
    papers = (
        db.query(Paper)
        .join(ProjectPaper, ProjectPaper.paper_id == Paper.id)
        .filter(ProjectPaper.project_id == project_id)
        .filter(or_(Paper.visibility == "public", Paper.owner_user_id == user_uuid))
        .order_by(Paper.created_at.desc())
        .all()
    )
    return ProjectPapersResponse(
        project_id=project_id,
        total=len(papers),
        results=[PaperRead.model_validate(paper) for paper in papers],
    )


@router.delete("/{project_id}/papers/{paper_id}", response_model=RemoveProjectPapersResponse)
def remove_paper_from_project(
    project_id: UUID,
    paper_id: UUID,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> RemoveProjectPapersResponse:
    return remove_papers_from_project(
        project_id=project_id,
        payload=RemoveProjectPapersRequest(paper_ids=[paper_id]),
        db=db,
        user_id=user_id,
    )


@router.post("/{project_id}/papers/delete", response_model=RemoveProjectPapersResponse)
def remove_papers_from_project(
    project_id: UUID,
    payload: RemoveProjectPapersRequest,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> RemoveProjectPapersResponse:
    user_uuid = UUID(user_id)
    _get_user_project(db=db, project_id=project_id, user_id=user_uuid)
    requested_ids = list(dict.fromkeys(payload.paper_ids))
    removed = (
        db.query(ProjectPaper)
        .filter(ProjectPaper.project_id == project_id, ProjectPaper.paper_id.in_(requested_ids))
        .delete(synchronize_session=False)
    )
    db.commit()
    return RemoveProjectPapersResponse(
        project_id=project_id,
        requested=len(requested_ids),
        removed=removed,
        skipped=len(requested_ids) - removed,
    )


@router.get("/{project_id}/qas", response_model=ProjectQAListResponse)
def list_project_qas(
    project_id: UUID,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> ProjectQAListResponse:
    user_uuid = UUID(user_id)
    _get_user_project(db=db, project_id=project_id, user_id=user_uuid)

    if _project_qas_has_summary_context_columns(db):
        qas = (
            db.query(ProjectQA)
            .filter(ProjectQA.project_id == project_id, ProjectQA.user_id == user_uuid)
            .order_by(ProjectQA.created_at.desc())
            .all()
        )
        results = [
            ProjectQARead(
                id=qa.id,
                project_id=qa.project_id,
                user_id=qa.user_id,
                question=qa.question,
                answer=qa.answer,
                citations=qa.citations_json or [],
                include_in_summary_context=qa.include_in_summary_context,
                summary_context_reason=qa.summary_context_reason,
                created_at=qa.created_at,
            )
            for qa in qas
        ]
    else:
        rows = db.execute(
            text(
                """
                SELECT id, project_id, user_id, question, answer, citations, created_at
                FROM project_qas
                WHERE project_id = :project_id AND user_id = :user_id
                ORDER BY created_at DESC
                """
            ),
            {"project_id": project_id, "user_id": user_uuid},
        ).mappings()
        results = [
            ProjectQARead(
                id=row["id"],
                project_id=row["project_id"],
                user_id=row["user_id"],
                question=row["question"],
                answer=row["answer"],
                citations=row["citations"] or [],
                include_in_summary_context=True,
                summary_context_reason=None,
                created_at=row["created_at"],
            )
            for row in rows
        ]

    return ProjectQAListResponse(project_id=project_id, total=len(results), results=results)


@router.delete("/{project_id}/qas/{qa_id}", response_model=DeleteProjectQAsResponse)
def delete_project_qa(
    project_id: UUID,
    qa_id: UUID,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> DeleteProjectQAsResponse:
    return delete_project_qas(
        project_id=project_id,
        payload=DeleteProjectQAsRequest(qa_ids=[qa_id]),
        db=db,
        user_id=user_id,
    )


@router.post("/{project_id}/qas/delete", response_model=DeleteProjectQAsResponse)
def delete_project_qas(
    project_id: UUID,
    payload: DeleteProjectQAsRequest,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> DeleteProjectQAsResponse:
    user_uuid = UUID(user_id)
    _get_user_project(db=db, project_id=project_id, user_id=user_uuid)
    requested_ids = list(dict.fromkeys(payload.qa_ids))
    deleted = (
        db.query(ProjectQA)
        .filter(ProjectQA.project_id == project_id, ProjectQA.user_id == user_uuid, ProjectQA.id.in_(requested_ids))
        .delete(synchronize_session=False)
    )
    db.commit()
    return DeleteProjectQAsResponse(
        project_id=project_id,
        requested=len(requested_ids),
        deleted=deleted,
        skipped=len(requested_ids) - deleted,
    )


@router.post("/{project_id}/papers", status_code=status.HTTP_204_NO_CONTENT)
def add_paper_to_project(
    project_id: UUID,
    payload: AddProjectPaperRequest,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> None:
    user_uuid = UUID(user_id)
    project = db.query(Project).filter(Project.id == project_id, Project.user_id == UUID(user_id)).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    paper = (
        db.query(Paper)
        .filter(Paper.id == payload.paper_id)
        .filter(or_(Paper.visibility == "public", Paper.owner_user_id == user_uuid))
        .first()
    )
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
    db.merge(ProjectPaper(project_id=project_id, paper_id=payload.paper_id))
    db.commit()


@router.post("/{project_id}/papers/batch", response_model=AddProjectPapersResponse, status_code=status.HTTP_200_OK)
def add_papers_to_project(
    project_id: UUID,
    payload: AddProjectPapersRequest,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> AddProjectPapersResponse:
    user_uuid = UUID(user_id)
    project = db.query(Project).filter(Project.id == project_id, Project.user_id == user_uuid).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    requested_ids = list(dict.fromkeys(payload.paper_ids))
    accessible_rows = (
        db.query(Paper.id)
        .filter(Paper.id.in_(requested_ids))
        .filter(or_(Paper.visibility == "public", Paper.owner_user_id == user_uuid))
        .all()
    )
    accessible_ids = {row[0] for row in accessible_rows}
    existing_rows = (
        db.query(ProjectPaper.paper_id)
        .filter(ProjectPaper.project_id == project_id, ProjectPaper.paper_id.in_(accessible_ids))
        .all()
    )
    existing_ids = {row[0] for row in existing_rows}
    ids_to_add = [paper_id for paper_id in requested_ids if paper_id in accessible_ids and paper_id not in existing_ids]

    for paper_id in ids_to_add:
        db.add(ProjectPaper(project_id=project_id, paper_id=paper_id))
    db.commit()

    return AddProjectPapersResponse(
        project_id=project_id,
        requested=len(requested_ids),
        added=len(ids_to_add),
        already_linked=len(existing_ids),
        skipped_inaccessible=len(requested_ids) - len(accessible_ids),
    )


@router.post("/{project_id}/summary", response_model=ProjectSummaryResponse, status_code=status.HTTP_200_OK)
async def summarize_project(
    project_id: UUID,
    payload: ProjectSummaryRequest | None = None,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> ProjectSummaryResponse:
    return await SummaryService().summarize_project(
        db=db,
        project_id=project_id,
        user_id=UUID(user_id),
        summary_question=payload.question if payload else None,
    )
