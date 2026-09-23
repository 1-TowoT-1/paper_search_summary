from __future__ import annotations

import base64
import os
from io import BytesIO
from typing import Any
from uuid import UUID

from fastapi import UploadFile
from mcp.server.fastmcp import FastMCP

from app.api.routes import projects as project_routes
from app.llm.llm_client import LLMClient
from app.mcp.runtime import build_user_llm, db_session, model_dump_jsonable, require_user_uuid
from app.models.schemas import (
    AddProjectPapersRequest,
    DeleteProjectQAsRequest,
    ImportCandidatePaper,
    ImportPapersRequest,
    ImportSelectedPapersRequest,
    LiteratureSource,
    ManualMaterialRequest,
    PaperRead,
    PublicationStatus,
    ProjectRead,
    RemoveProjectPapersRequest,
    Visibility,
)
from app.services.paper_catalog_service import PaperCatalogFilters, PaperCatalogService
from app.services.paper_cleanup_service import PaperCleanupService
from app.services.paper_importer import PaperImporter
from app.services.project_agent_service import ProjectAgentService
from app.services.summary_service import SummaryService
from app.services.user_material_importer import UserMaterialImporter, parse_authors_json

def _mcp_port() -> int:
    return int(os.getenv("MCP_PORT", "9000"))


mcp = FastMCP(
    "LitSage",
    host=os.getenv("MCP_HOST", "127.0.0.1"),
    port=_mcp_port(),
    sse_path=os.getenv("MCP_SSE_PATH", "/sse"),
    message_path=os.getenv("MCP_MESSAGE_PATH", "/messages/"),
    streamable_http_path=os.getenv("MCP_HTTP_PATH", "/mcp"),
)


def _llm(config: dict[str, Any] | None) -> LLMClient:
    return build_user_llm(config)


def _sources(values: list[str] | None) -> list[LiteratureSource]:
    if not values:
        return [LiteratureSource.pubmed]
    return [LiteratureSource(value) for value in values]


def _uuid_or_none(value: str | None) -> UUID | None:
    return UUID(value) if value else None


@mcp.tool()
def list_projects(user_id: str) -> dict[str, Any]:
    """List projects owned by the LitSage user."""
    with db_session() as db:
        projects = project_routes.list_projects(db=db, user_id=str(require_user_uuid(user_id)))
        return {"projects": model_dump_jsonable([ProjectRead.model_validate(project) for project in projects])}


@mcp.tool()
def create_project(user_id: str, name: str, description: str | None = None) -> dict[str, Any]:
    """Create a research project for the LitSage user."""
    from app.models.schemas import ProjectCreate

    with db_session() as db:
        project = project_routes.create_project(
            payload=ProjectCreate(name=name, description=description),
            db=db,
            user_id=str(require_user_uuid(user_id)),
        )
        return {"project": model_dump_jsonable(ProjectRead.model_validate(project))}


@mcp.tool()
def list_project_papers(user_id: str, project_id: str) -> dict[str, Any]:
    """List papers bound to a project."""
    with db_session() as db:
        response = project_routes.list_project_papers(
            project_id=UUID(project_id),
            db=db,
            user_id=str(require_user_uuid(user_id)),
        )
        return model_dump_jsonable(response)


@mcp.tool()
def list_project_qas(user_id: str, project_id: str) -> dict[str, Any]:
    """List historical questions and answers recorded for a project."""
    with db_session() as db:
        response = project_routes.list_project_qas(
            project_id=UUID(project_id),
            db=db,
            user_id=str(require_user_uuid(user_id)),
        )
        return model_dump_jsonable(response)


@mcp.tool()
def bind_papers_to_project(user_id: str, project_id: str, paper_ids: list[str]) -> dict[str, Any]:
    """Bind existing papers to a project."""
    with db_session() as db:
        response = project_routes.add_papers_to_project(
            project_id=UUID(project_id),
            payload=AddProjectPapersRequest(paper_ids=[UUID(paper_id) for paper_id in paper_ids]),
            db=db,
            user_id=str(require_user_uuid(user_id)),
        )
        return model_dump_jsonable(response)


@mcp.tool()
def remove_project_papers(user_id: str, project_id: str, paper_ids: list[str]) -> dict[str, Any]:
    """Remove paper bindings from a project without deleting the papers from the library."""
    with db_session() as db:
        response = project_routes.remove_papers_from_project(
            project_id=UUID(project_id),
            payload=RemoveProjectPapersRequest(paper_ids=[UUID(paper_id) for paper_id in paper_ids]),
            db=db,
            user_id=str(require_user_uuid(user_id)),
        )
        return model_dump_jsonable(response)


@mcp.tool()
def delete_project_qas(user_id: str, project_id: str, qa_ids: list[str]) -> dict[str, Any]:
    """Delete selected project Q&A records."""
    with db_session() as db:
        response = project_routes.delete_project_qas(
            project_id=UUID(project_id),
            payload=DeleteProjectQAsRequest(qa_ids=[UUID(qa_id) for qa_id in qa_ids]),
            db=db,
            user_id=str(require_user_uuid(user_id)),
        )
        return model_dump_jsonable(response)


@mcp.tool()
async def search_literature(
    user_id: str,
    query: str,
    llm_config: dict[str, Any],
    sources: list[str] | None = None,
    limit: int = 10,
    year_from: int | None = None,
    year_to: int | None = None,
    include_pdf: bool = False,
) -> dict[str, Any]:
    """Search external literature sources. PubMed is preferred by default."""
    _ = require_user_uuid(user_id)
    importer = PaperImporter()
    importer.llm = _llm(llm_config)
    payload = ImportPapersRequest(query=query, sources=_sources(sources), limit=limit, include_pdf=include_pdf)
    response = await importer.preview_import(payload=payload, user_id=user_id)
    return model_dump_jsonable(response)


@mcp.tool()
async def import_literature_candidates(
    user_id: str,
    papers: list[dict[str, Any]],
    llm_config: dict[str, Any],
    include_pdf: bool = True,
    project_id: str | None = None,
) -> dict[str, Any]:
    """Import selected candidate papers and optionally fetch full text."""
    importer = PaperImporter()
    importer.llm = _llm(llm_config)
    payload = ImportSelectedPapersRequest(
        papers=[ImportCandidatePaper.model_validate(paper) for paper in papers],
        include_pdf=include_pdf,
        project_id=_uuid_or_none(project_id),
    )
    response = await importer.import_selected(payload=payload, user_id=str(require_user_uuid(user_id)))
    return model_dump_jsonable(response)


@mcp.tool()
async def search_my_library(
    user_id: str,
    query: str | None = None,
    llm_config: dict[str, Any] | None = None,
    title: str | None = None,
    doi: str | None = None,
    author: str | None = None,
    source: str | None = None,
    source_id: str | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
    limit: int = 20,
    offset: int = 0,
) -> dict[str, Any]:
    """Search the LitSage paper library."""
    _ = require_user_uuid(user_id)
    q_terms: list[str] = []
    if query and llm_config:
        try:
            q_terms = [term for term in await _llm(llm_config).rewrite_query(query) if term != query]
        except Exception:
            q_terms = []
    with db_session() as db:
        papers, total = PaperCatalogService().list_papers(
            db=db,
            filters=PaperCatalogFilters(
                q=query,
                q_terms=q_terms,
                title=title,
                doi=doi,
                author=author,
                source=source,
                source_id=source_id,
                year_from=year_from,
                year_to=year_to,
            ),
            limit=limit,
            offset=offset,
        )
        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "results": model_dump_jsonable([PaperRead.model_validate(paper) for paper in papers]),
        }


@mcp.tool()
async def ask_project_knowledge_base(
    user_id: str,
    project_id: str,
    question: str,
    llm_config: dict[str, Any],
) -> dict[str, Any]:
    """Ask questions against a project's knowledge base."""
    from app.models.schemas import QARequest, QAScope

    service = ProjectAgentService(llm=_llm(llm_config))
    payload = QARequest(scope=QAScope.project, project_id=UUID(project_id), question=question)
    with db_session() as db:
        response = await service.answer(db=db, payload=payload, user_id=str(require_user_uuid(user_id)))
        return model_dump_jsonable(response)


@mcp.tool()
async def summarize_project_stage(
    user_id: str,
    project_id: str,
    question: str,
    llm_config: dict[str, Any],
) -> dict[str, Any]:
    """Generate a stage summary for a research project."""
    service = SummaryService()
    service.llm = _llm(llm_config)
    with db_session() as db:
        response = await service.summarize_project(
            db=db,
            project_id=UUID(project_id),
            user_id=require_user_uuid(user_id),
            summary_question=question,
        )
        return model_dump_jsonable(response)


@mcp.tool()
async def create_manual_material(
    user_id: str,
    title: str,
    abstract: str,
    llm_config: dict[str, Any],
    content: str | None = None,
    project_id: str | None = None,
    authors: list[dict[str, Any]] | None = None,
    publication_status: str = "unpublished",
    visibility: str = "private",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a manual research material record."""
    importer = UserMaterialImporter()
    importer.llm = _llm(llm_config)
    importer.multimodal.llm = importer.llm
    payload = ManualMaterialRequest(
        title=title,
        abstract=abstract,
        content=content,
        authors=authors or [],
        project_id=_uuid_or_none(project_id),
        publication_status=PublicationStatus(publication_status),
        visibility=Visibility(visibility),
        metadata=metadata or {},
    )
    with db_session() as db:
        response = await importer.create_manual_material(db=db, payload=payload, user_id=require_user_uuid(user_id))
        return model_dump_jsonable(response)


@mcp.tool()
async def upload_user_material(
    user_id: str,
    filename: str,
    llm_config: dict[str, Any],
    file_base64: str | None = None,
    local_file_path: str | None = None,
    project_id: str | None = None,
    title: str | None = None,
    abstract: str | None = None,
    authors_json: str | None = None,
    publication_status: str = "unpublished",
    visibility: str = "private",
) -> dict[str, Any]:
    """Upload PDF, DOCX, or Markdown material. Use the caller's LLM config for multimodal PDF parsing."""
    if not file_base64 and not local_file_path:
        raise ValueError("Provide either file_base64 or local_file_path.")
    if file_base64:
        content = base64.b64decode(file_base64)
    else:
        from pathlib import Path

        content = Path(str(local_file_path)).read_bytes()

    importer = UserMaterialImporter()
    importer.llm = _llm(llm_config)
    importer.multimodal.llm = importer.llm
    upload = UploadFile(file=BytesIO(content), filename=filename)
    with db_session() as db:
        response = await importer.upload_material(
            db=db,
            file=upload,
            user_id=require_user_uuid(user_id),
            project_id=_uuid_or_none(project_id),
            title=title,
            abstract=abstract,
            authors=parse_authors_json(authors_json),
            publication_status=PublicationStatus(publication_status),
            visibility=Visibility(visibility),
        )
        return model_dump_jsonable(response)


@mcp.tool()
async def delete_paper(user_id: str, paper_id: str, confirm: bool = False) -> dict[str, Any]:
    """Delete a paper from the library and clean project links/vector data. Requires confirm=true."""
    if not confirm:
        return {"deleted": False, "message": "Set confirm=true to delete the paper."}
    with db_session() as db:
        result = await PaperCleanupService().delete_paper(
            db=db,
            paper_id=UUID(paper_id),
            user_id=require_user_uuid(user_id),
        )
        return model_dump_jsonable(result) if result else {"deleted": False, "message": "Paper not found."}


def main() -> None:
    transport = os.getenv("MCP_TRANSPORT", "stdio").strip().lower()
    mount_path = os.getenv("MCP_MOUNT_PATH") or None
    if transport not in {"stdio", "sse", "streamable-http"}:
        raise ValueError("MCP_TRANSPORT must be one of: stdio, sse, streamable-http")
    mcp.run(transport=transport, mount_path=mount_path)


if __name__ == "__main__":
    main()
