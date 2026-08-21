from uuid import UUID

from app.core.celery_app import celery_app


@celery_app.task(name="litsage.import_papers")
def import_papers_task(task_id: str, payload: dict) -> dict:
    _ = UUID(task_id)
    return {"status": "completed", "payload": payload}


@celery_app.task(name="litsage.summarize_project")
def summarize_project_task(task_id: str, project_id: str, user_id: str) -> dict:
    return {"task_id": task_id, "project_id": project_id, "user_id": user_id, "status": "completed"}

