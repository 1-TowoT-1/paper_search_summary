# LitSage

LitSage is a literature intelligent search and summarization agent designed from the provided project template. It exposes a FastAPI backend for natural-language literature retrieval, query rewriting, paper/project management, RAG question answering, and asynchronous summarization.

## Architecture

- FastAPI provides REST endpoints and the application entry point.
- PostgreSQL stores papers, users, projects, paper collections, and summary tasks.
- Redis is reserved for search caches, session memory, rate limiting, and Celery status.
- Celery handles long-running import and summarization jobs.
- Milvus is the vector store for abstract vectors and full-text chunk vectors.
- LLM and embedding calls are wrapped behind replaceable service adapters.

## Local Setup

```bash
cd litsage
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
docker compose up -d
uvicorn app.main:app --reload
```

The API will be available at `http://127.0.0.1:8000`, with OpenAPI docs at `/docs`.

In development, `AUTO_CREATE_TABLES=true` creates the PostgreSQL tables when FastAPI starts, so Swagger requests can be tested immediately. For production or migration-driven environments, set `AUTO_CREATE_TABLES=false` and run:

```bash
alembic upgrade head
```

You can also initialize and inspect tables without starting FastAPI:

```bash
python scripts/init_db.py
```

## Implemented Project Shape

```text
app/
  api/routes/          HTTP endpoints from the README API list
  core/                JWT, Redis, Celery infrastructure
  llm/                 LLM client, prompts, reranker boundary
  models/              SQLAlchemy and Pydantic models
  services/            search, RAG, summary, import, vector abstractions
  tasks/               Celery task definitions
migrations/            Alembic migration environment
tests/                 health-check test
```

## Next Engineering Steps

1. Replace placeholder `LLMClient` and `EmbeddingService` with OpenAI, Ollama, or BGE-M3 implementations.
2. Implement `VectorStore` with Milvus collections `paper_abstracts` and `paper_chunks`.
3. Hydrate vector search hits from PostgreSQL in `SearchService`.
4. Add concrete importers for arXiv, Semantic Scholar, and PubMed.
5. Generate the initial Alembic migration after PostgreSQL is running.
