from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.db import Paper, Project, ProjectPaper
from app.models.schemas import PaperDeleteResponse
from app.services.vector_store import VectorStore, VectorStoreError


class PaperCleanupService:
    def __init__(self) -> None:
        self._vector_store: VectorStore | None = None

    @property
    def vector_store(self) -> VectorStore:
        if self._vector_store is None:
            self._vector_store = VectorStore()
        return self._vector_store

    async def delete_paper(self, db: Session, paper_id: UUID, user_id: UUID) -> PaperDeleteResponse | None:
        paper = db.get(Paper, paper_id)
        if paper is None:
            return None

        self._ensure_user_can_delete(db=db, paper_id=paper_id, user_id=user_id)

        vector_delete_stats: dict[str, int | str] | None = None
        vector_delete_error: str | None = None
        try:
            vector_delete_stats = await self.vector_store.delete_paper_vectors(paper_id)
        except VectorStoreError as exc:
            vector_delete_error = str(exc)
            return PaperDeleteResponse(
                paper_id=paper_id,
                deleted=False,
                project_links_deleted=0,
                vector_deleted=False,
                vector_delete_stats=None,
                vector_delete_error=vector_delete_error,
            )

        project_links_deleted = (
            db.query(ProjectPaper)
            .filter(ProjectPaper.paper_id == paper_id)
            .delete(synchronize_session=False)
        )
        db.delete(paper)

        try:
            db.commit()
        except SQLAlchemyError:
            db.rollback()
            raise

        return PaperDeleteResponse(
            paper_id=paper_id,
            deleted=True,
            project_links_deleted=project_links_deleted,
            vector_deleted=True,
            vector_delete_stats=vector_delete_stats,
            vector_delete_error=vector_delete_error,
        )

    def _ensure_user_can_delete(self, db: Session, paper_id: UUID, user_id: UUID) -> None:
        linked_user_ids = [
            row[0]
            for row in (
                db.query(Project.user_id)
                .join(ProjectPaper, ProjectPaper.project_id == Project.id)
                .filter(ProjectPaper.paper_id == paper_id)
                .distinct()
                .all()
            )
        ]

        if not linked_user_ids:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "This paper is not in your project directory. "
                    "Only papers owned through your project directory can be deleted."
                ),
            )

        linked_user_id_set = set(linked_user_ids)
        if user_id not in linked_user_id_set:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only delete papers from your own project directory.",
            )

        if linked_user_id_set != {user_id}:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "This paper is also referenced by another user's project. "
                    "Global metadata and vectors were not deleted."
                ),
            )
