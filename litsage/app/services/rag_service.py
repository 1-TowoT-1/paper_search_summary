from uuid import uuid4

from app.llm.llm_client import LLMClient
from app.models.schemas import Citation, QARequest, QAResponse
from app.services.embedding_service import EmbeddingService
from app.services.vector_store import VectorStore


class RAGService:
    def __init__(self) -> None:
        self.llm = LLMClient()
        self.embeddings = EmbeddingService()
        self.vector_store = VectorStore()

    async def answer(self, payload: QARequest, user_id: str) -> QAResponse:
        _ = user_id
        paper_ids = payload.paper_ids
        if payload.paper_id:
            paper_ids = [payload.paper_id]

        vector = await self.embeddings.embed_text(payload.question)
        hits = await self.vector_store.search_chunks(vector=vector, paper_ids=paper_ids, limit=10)
        context = "\n\n".join(hit.text or "" for hit in hits)
        answer = await self.llm.answer(question=payload.question, context=context)
        citations = [
            Citation(paper_id=hit.paper_id, title="Unknown paper", chunk_id=hit.chunk_id, locator=hit.locator)
            for hit in hits
        ]
        return QAResponse(answer=answer, citations=citations, session_id=payload.session_id or str(uuid4()))

