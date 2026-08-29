from __future__ import annotations

import asyncio
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
        if provider not in {"local_bge", "bge", "openai_compatible", "ollama"}:
            raise EmbeddingError(f"Unsupported embedding provider: {settings.embedding_provider}")

        if provider == "ollama":
            vector = await self._embed_with_ollama(text)
        else:
            vector = await self._embed_with_bge(text)

        if len(vector) != settings.embedding_dim:
            raise EmbeddingError(
                f"Embedding dimension mismatch: expected {settings.embedding_dim}, got {len(vector)}"
            )
        return vector

    async def _embed_with_ollama(self, text: str) -> list[float]:
        url = settings.bge_base_url.rstrip("/") + "/" + settings.bge_embedding_path.strip("/")
        payload: dict[str, Any] = {"model": settings.embedding_model, "input": text}
        data = await self._post_embedding_json(url=url, payload=payload, provider_name="Ollama")
        return self._extract_embedding(data)

    async def _embed_with_bge(self, text: str) -> list[float]:
        url = settings.bge_base_url.rstrip("/") + "/" + settings.bge_embedding_path.strip("/")
        request_format = settings.bge_request_format.lower().strip()
        if request_format in {"openai", "openai_compatible"}:
            payload: dict[str, Any] = {"model": settings.embedding_model, "input": [text]}
        else:
            payload = {"texts": [text]}

        data = await self._post_embedding_json(url=url, payload=payload, provider_name="BGE embedding")
        return self._extract_embedding(data)

    async def _post_embedding_json(self, url: str, payload: dict[str, Any], provider_name: str) -> Any:
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=settings.bge_timeout_seconds, trust_env=False) as client:
                    response = await client.post(url, json=payload)
                    response.raise_for_status()
                    return response.json()
            except httpx.HTTPStatusError as exc:
                last_error = exc
                if exc.response.status_code not in {502, 503, 504} or attempt == 2:
                    detail = exc.response.text[:500]
                    raise EmbeddingError(f"{provider_name} HTTP {exc.response.status_code}: {detail}") from exc
            except httpx.RequestError as exc:
                last_error = exc
                if attempt == 2:
                    raise EmbeddingError(f"{provider_name} request failed: {exc}") from exc
            except ValueError as exc:
                raise EmbeddingError(f"{provider_name} returned non-JSON response") from exc

            await asyncio.sleep(0.5 * (attempt + 1))

        raise EmbeddingError(f"{provider_name} request failed: {last_error}")

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
