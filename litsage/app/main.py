from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.routes import auth, papers, projects, qa, search, tasks
from app.config import settings
from app.models.db import Base, engine


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="Literature intelligent search and summarization agent.",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
    app.include_router(search.router, prefix="/api/search", tags=["search"])
    app.include_router(papers.router, prefix="/api/papers", tags=["papers"])
    app.include_router(projects.router, prefix="/api/projects", tags=["projects"])
    app.include_router(qa.router, prefix="/api/qa", tags=["qa"])
    app.include_router(tasks.router, prefix="/api/tasks", tags=["tasks"])

    generated_image_dir = Path(settings.generated_image_dir)
    generated_image_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/generated_images", StaticFiles(directory=str(generated_image_dir)), name="generated_images")

    @app.on_event("startup")
    def create_dev_tables() -> None:
        if settings.auto_create_tables and settings.environment == "dev":
            Base.metadata.create_all(bind=engine)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
