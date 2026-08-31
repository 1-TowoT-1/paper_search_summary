from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "LitSage"
    app_version: str = "0.1.0"
    environment: str = "dev"
    auto_create_tables: bool = True
    cors_origins: list[str] = Field(default_factory=lambda: ["*"])

    database_url: str = "postgresql+psycopg://litsage:12345678@localhost:5432/litsage"
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    milvus_uri: str = "http://localhost:19530"
    abstract_collection: str = "paper_abstracts"
    chunk_collection: str = "paper_chunks"
    embedding_dim: int = 1024
    milvus_metric_type: str = "COSINE"

    embedding_provider: str = "local_bge"
    bge_base_url: str = "http://localhost:8001"
    bge_embedding_path: str = "/embed"
    bge_request_format: str = "bge"
    bge_timeout_seconds: float = 60.0

    semantic_scholar_api_key: str | None = None
    pubmed_email: str | None = None
    pubmed_api_key: str | None = None
    external_api_timeout_seconds: float = 30.0
    pdf_max_size_mb: int = 30
    pdf_download_timeout_seconds: float = 30.0
    pdf_chunk_size: int = 1500
    pdf_chunk_overlap: int = 200

    llm_provider: str = "openai"
    openai_api_key: str | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    openai_api_mode: str = "responses"
    openai_model: str = "gpt-4.1-mini"
    embedding_model: str = "text-embedding-3-large"
    local_ollama_base_url: str = "http://localhost:11434"
    local_ollama_model: str = "qwen2.5:7b"
    llm_temperature: float = 0.2
    llm_timeout_seconds: float = 60.0
    llm_max_output_tokens: int = 1600

    search_cache_ttl_seconds: int = 600
    search_local_min_results: int = 5
    search_local_min_score: float = 0.4
    search_external_candidate_multiplier: int = 10
    paper_summary_ttl_seconds: int = 86400
    rate_limit_per_minute: int = 20


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
