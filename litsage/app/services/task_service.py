from uuid import UUID

from app.models.schemas import TaskStatusResponse


class TaskService:
    async def get_status(self, task_id: UUID) -> TaskStatusResponse:
        return TaskStatusResponse(task_id=task_id, status="pending")

