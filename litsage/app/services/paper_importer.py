from uuid import UUID, uuid4

from app.models.schemas import ImportPapersRequest, ImportPapersResponse


class PaperImporter:
    async def enqueue_import(self, payload: ImportPapersRequest, user_id: str) -> ImportPapersResponse:
        _ = (payload, user_id)
        task_id = uuid4()
        return ImportPapersResponse(
            task_id=task_id,
            status="pending",
            message="Import task accepted. Celery worker integration is scaffolded in app.tasks.",
        )

    async def import_from_sources(self, task_id: UUID, payload: ImportPapersRequest) -> None:
        _ = (task_id, payload)

