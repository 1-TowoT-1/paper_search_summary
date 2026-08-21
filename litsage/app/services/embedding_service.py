import hashlib
import math

from app.config import settings


class EmbeddingService:
    async def embed_text(self, text: str) -> list[float]:
        """Return a deterministic local embedding placeholder.

        Replace this with BGE-M3, OpenAI embeddings, or an internal embedding gateway
        in production.
        """
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        values = [(digest[i % len(digest)] / 255.0) - 0.5 for i in range(settings.embedding_dim)]
        norm = math.sqrt(sum(value * value for value in values)) or 1.0
        return [value / norm for value in values]

