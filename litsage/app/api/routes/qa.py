from fastapi import APIRouter, Depends

from app.api.dependencies import get_current_user_id
from app.models.schemas import QARequest, QAResponse
from app.services.rag_service import RAGService

router = APIRouter()


@router.post("", response_model=QAResponse)
async def ask_question(payload: QARequest, user_id: str = Depends(get_current_user_id)) -> QAResponse:
    return await RAGService().answer(payload=payload, user_id=user_id)

