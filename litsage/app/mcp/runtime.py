from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.llm.llm_client import LLMClient
from app.models.db import SessionLocal


class MCPLLMConfig(BaseModel):
    provider: str = "openai_compatible"
    api_key: str | None = Field(default=None, description="User-owned LLM API key.")
    base_url: str = "https://api.openai.com/v1"
    api_mode: str = "responses"
    model: str
    vision_model: str | None = None
    temperature: float = 0.2
    timeout_seconds: float = 60.0
    max_output_tokens: int = 10000
    ollama_base_url: str | None = None
    ollama_model: str | None = None


def require_user_uuid(user_id: str) -> UUID:
    return UUID(str(user_id).strip())


def build_user_llm(config: dict[str, Any] | MCPLLMConfig | None) -> LLMClient:
    if config is None:
        raise ValueError("MCP LLM tools require `llm_config`; use the caller user's API key, not the server .env key.")
    llm_config = config if isinstance(config, MCPLLMConfig) else MCPLLMConfig.model_validate(config)
    provider = llm_config.provider.lower().strip()
    if provider != "ollama" and not llm_config.api_key:
        raise ValueError("llm_config.api_key is required for remote LLM providers.")
    return LLMClient(
        provider=provider,
        openai_api_key=llm_config.api_key,
        openai_base_url=llm_config.base_url,
        openai_api_mode=llm_config.api_mode,
        openai_model=llm_config.model,
        vision_model=llm_config.vision_model,
        ollama_base_url=llm_config.ollama_base_url,
        ollama_model=llm_config.ollama_model,
        temperature=llm_config.temperature,
        timeout_seconds=llm_config.timeout_seconds,
        max_output_tokens=llm_config.max_output_tokens,
    )


@contextmanager
def db_session() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def model_dump_jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return [model_dump_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [model_dump_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: model_dump_jsonable(item) for key, item in value.items()}
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value
