from __future__ import annotations

from typing import Any

import httpx

from app.config import settings


class EmbeddingError(RuntimeError):
    pass


class EmbeddingService:
    async def embed_text(self, text: str) -> list[float]:
        text = text.strip()
        if not text:
            raise EmbeddingError("Cannot embed empty text")

        provider = settings.embedding_provider.lower().strip()
        if provider not in {"local_bge", "bge", "openai_compatible"}:
            raise EmbeddingError(f"Unsupported embedding provider: {settings.embedding_provider}")

        vector = await self._embed_with_bge(text)
        if len(vector) != settings.embedding_dim:
            raise EmbeddingError(
                f"Embedding dimension mismatch: expected {settings.embedding_dim}, got {len(vector)}"
            )
        return vector

    async def _embed_with_bge(self, text: str) -> list[float]:
        url = settings.bge_base_url.rstrip("/") + "/" + settings.bge_embedding_path.strip("/")
        request_format = settings.bge_request_format.lower().strip()
        if request_format in {"openai", "openai_compatible"}:
            payload: dict[str, Any] = {"model": settings.embedding_model, "input": [text]}
        else:
            payload = {"texts": [text]}

        try:
            async with httpx.AsyncClient(timeout=settings.bge_timeout_seconds) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPStatusError as exc:
            raise EmbeddingError(f"BGE embedding HTTP {exc.response.status_code}: {exc.response.text[:500]}") from exc
        except httpx.RequestError as exc:
            raise EmbeddingError(f"BGE embedding request failed: {exc}") from exc
        except ValueError as exc:
            raise EmbeddingError("BGE embedding service returned non-JSON response") from exc

        return self._extract_embedding(data)

    def _extract_embedding(self, data: Any) -> list[float]:
        candidate: Any = None

        if isinstance(data, list):
            candidate = data[0] if data else None
        elif isinstance(data, dict):
            if isinstance(data.get("embedding"), list):
                candidate = data["embedding"]
            elif isinstance(data.get("embeddings"), list):
                embeddings = data["embeddings"]
                candidate = embeddings[0] if embeddings else None
            elif isinstance(data.get("data"), list) and data["data"]:
                candidate = data["data"][0].get("embedding")
            elif isinstance(data.get("vectors"), list):
                vectors = data["vectors"]
                candidate = vectors[0] if vectors else None

        if not isinstance(candidate, list) or not candidate:
            raise EmbeddingError(f"Cannot find embedding vector in response: {data}")

        try:
            return [float(value) for value in candidate]
        except (TypeError, ValueError) as exc:
            raise EmbeddingError("Embedding vector contains non-numeric values") from exc
