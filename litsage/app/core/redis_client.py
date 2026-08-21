import json
from typing import Any

import redis.asyncio as redis

from app.config import settings


class RedisClient:
    def __init__(self) -> None:
        self._client = redis.from_url(settings.redis_url, decode_responses=True)

    async def get_json(self, key: str) -> Any | None:
        value = await self._client.get(key)
        return json.loads(value) if value else None

    async def set_json(self, key: str, value: Any, ttl_seconds: int) -> None:
        await self._client.setex(key, ttl_seconds, json.dumps(value, default=str))

    async def close(self) -> None:
        await self._client.aclose()


redis_client = RedisClient()

