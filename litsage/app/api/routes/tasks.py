from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.dependencies import get_current_user_id
from app.models.schemas import TaskStatusResponse
from app.services.task_service import TaskService

router = APIRouter()


@router.get("/{task_id}", response_model=TaskStatusResponse)
async def get_task_status(task_id: UUID, _: str = Depends(get_current_user_id)) -> TaskStatusResponse:
    return await TaskService().get_status(task_id=task_id)

