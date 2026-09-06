from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.parse import urlparse
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import fitz
import httpx
from sqlalchemy import or_
from sqlalchemy.exc import SQLAlchemyError

from app.config import settings
from app.llm.llm_client import LLMClient
from app.models.db import Paper, PaperChunk, Project, ProjectPaper, SessionLocal
from app.models.schemas import (
    ImportCandidatePaper,
    ImportPapersRequest,
    ImportPapersResponse,
    ImportPreviewResponse,
    ImportSelectedPapersRequest,
    LiteratureSource,
)
from app.services.embedding_service import EmbeddingError, EmbeddingService
from app.services.pdf_resolver import PDFResolver, StructuredFullTextResult
from app.services.vector_store import VectorStore, VectorStoreError

ATOM_NS = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
ARXIV_API_URL = "https://export.arxiv.org/api/query"
PUBMED_ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
PUBMED_EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"


@dataclass
class ImportedPaper:
    title: str
    authors: list[dict]
    abstract: str
    doi: str | None
    source: str
    source_id: str
    published_date: date | None
    pdf_url: str | None
    citation_count: int
    metadata: dict


@dataclass
class PDFProcessResult:
    success: bool
    chunk_count: int = 0
    error: str | None = None
    extraction_method: str | None = None
    final_pdf_url: str | None = None
    structured_fulltext_url: str | None = None
    manual_pdf_required: bool = False


@dataclass
class PDFDownloadResult:
    content: bytes
    final_url: str


class ImportStats:
    def __init__(self) -> None:
        self.values: dict[str, int | list[str]] = {
            "fetched": 0,
            "created": 0,
            "updated": 0,
            "skipped_duplicate": 0,
            "skipped_no_abstract": 0,
            "skipped_embedding_failed": 0,
            "abstract_vectorized": 0,
            "pdf_retried": 0,
            "pdf_already_processed": 0,
            "pdf_resolved": 0,
            "pdf_unresolved": 0,
            "pdf_processed": 0,
            "pdf_skipped": 0,
            "structured_fulltext_resolved": 0,
            "structured_fulltext_failed": 0,
            "manual_pdf_required": 0,
            "manual_pdf_required_papers": [],
            "project_linked": 0,
            "project_already_linked": 0,
            "failed": 0,
            "errors": [],
        }

    def inc(self, key: str, value: int = 1) -> None:
        current = self.values.get(key, 0)
        if isinstance(current, int):
            self.values[key] = current + value

    def error(self, message: str) -> None:
        self.inc("failed")
        self.append_error(message)

    def append_error(self, message: str) -> None:
        errors = self.values.setdefault("errors", [])
        if isinstance(errors, list):
            errors.append(message[:500])

    def append_manual_pdf_required(self, message: str) -> None:
        papers = self.values.setdefault("manual_pdf_required_papers", [])
        if isinstance(papers, list):
            papers.append(message[:500])


class PaperImporter:
    def __init__(self) -> None:
        self.embeddings = EmbeddingService()
        self.llm = LLMClient()
        self.pdf_resolver = PDFResolver()
        self._vector_store: VectorStore | None = None

    @property
    def vector_store(self) -> VectorStore:
        if self._vector_store is None:
            self._vector_store = VectorStore()
        return self._vector_store

    async def enqueue_import(self, payload: ImportPapersRequest, user_id: str) -> ImportPapersResponse:
        _ = user_id
        task_id = uuid4()
        stats = ImportStats()
        papers = await self.fetch_from_sources(payload=payload, stats=stats)
        await self.import_papers(papers=papers, include_pdf=payload.include_pdf, stats=stats)

        return ImportPapersResponse(
            task_id=task_id,
            status="completed",
            message=self._build_message(stats),
            stats=stats.values,
        )

    async def preview_import(self, payload: ImportPapersRequest, user_id: str) -> ImportPreviewResponse:
        _ = user_id
        stats = ImportStats()
        papers = await self.fetch_from_sources(payload=payload, stats=stats)
        candidates = [self._to_candidate(paper) for paper in papers]
        return ImportPreviewResponse(
            query=payload.query,
            total=len(candidates),
            candidates=candidates,
            stats=stats.values,
        )

    async def import_selected(
        self,
        payload: ImportSelectedPapersRequest,
        user_id: str,
    ) -> ImportPapersResponse:
        task_id = uuid4()
        stats = ImportStats()
        papers = [self._from_candidate(candidate) for candidate in payload.papers]
        stats.inc("fetched", len(papers))
        await self.import_papers(
            papers=papers,
            include_pdf=payload.include_pdf,
            stats=stats,
            project_id=payload.project_id,
            user_id=UUID(user_id),
        )
        return ImportPapersResponse(
            task_id=task_id,
            status="completed",
            message=self._build_message(stats),
            stats=stats.values,
        )

    async def import_from_sources(self, task_id: UUID, payload: ImportPapersRequest) -> dict[str, int | list[str]]:
        _ = task_id
        stats = ImportStats()
        papers = await self.fetch_from_sources(payload=payload, stats=stats)
        await self.import_papers(papers=papers, include_pdf=payload.include_pdf, stats=stats)
        return stats.values

    async def fetch_from_sources(
        self,
        payload: ImportPapersRequest,
        stats: ImportStats,
        year_from: int | None = None,
        year_to: int | None = None,
    ) -> list[ImportedPaper]:
        imported: list[ImportedPaper] = []
        for source in self._ordered_sources(payload.sources):
            try:
                if source == LiteratureSource.arxiv:
                    imported.extend(await self.fetch_arxiv(payload.query, payload.limit, stats, year_from, year_to))
                elif source == LiteratureSource.semantic_scholar:
                    stats.error("Semantic Scholar importer is reserved but not implemented yet.")
                elif source == LiteratureSource.pubmed:
                    imported.extend(await self.fetch_pubmed(payload.query, payload.limit, stats, year_from, year_to))
            except Exception as exc:
                stats.error(f"{source.value} fetch failed: {exc}")
        return self._dedupe_imported(self._rank_external_candidates(query=payload.query, papers=imported))[: payload.limit]

    def _ordered_sources(self, sources: list[LiteratureSource]) -> list[LiteratureSource]:
        priority = {
            LiteratureSource.pubmed: 0,
            LiteratureSource.arxiv: 1,
            LiteratureSource.semantic_scholar: 2,
        }
        unique_sources = list(dict.fromkeys(sources))
        return sorted(unique_sources, key=lambda source: priority.get(source, 99))

    async def fetch_arxiv(
        self,
        query: str,
        limit: int,
        stats: ImportStats,
        year_from: int | None = None,
        year_to: int | None = None,
    ) -> list[ImportedPaper]:
        params = {
            "search_query": self._build_arxiv_query(query, year_from, year_to),
            "start": 0,
            "max_results": self._external_candidate_limit(limit),
            "sortBy": "relevance",
            "sortOrder": "descending",
        }
        async with httpx.AsyncClient(timeout=settings.external_api_timeout_seconds) as client:
            response = await client.get(ARXIV_API_URL, params=params)
            response.raise_for_status()

        root = ET.fromstring(response.text)
        papers: list[ImportedPaper] = []
        for entry in root.findall("atom:entry", ATOM_NS):
            paper = self._parse_arxiv_entry(entry)
            stats.inc("fetched")
            if not paper.abstract.strip():
                stats.inc("skipped_no_abstract")
                continue
            papers.append(paper)
        return self._rank_external_candidates(query=query, papers=papers)[:limit]

    async def fetch_pubmed(
        self,
        query: str,
        limit: int,
        stats: ImportStats,
        year_from: int | None = None,
        year_to: int | None = None,
    ) -> list[ImportedPaper]:
        ids = await self._search_pubmed_ids(
            query=query,
            limit=self._external_candidate_limit(limit),
            year_from=year_from,
            year_to=year_to,
        )
        if not ids:
            return []

        params = {
            "db": "pubmed",
            "id": ",".join(ids),
            "retmode": "xml",
            "tool": settings.app_name,
        }
        if settings.pubmed_email:
            params["email"] = settings.pubmed_email
        if settings.pubmed_api_key:
            params["api_key"] = settings.pubmed_api_key

        async with httpx.AsyncClient(timeout=settings.external_api_timeout_seconds) as client:
            response = await client.get(PUBMED_EFETCH_URL, params=params)
            response.raise_for_status()

        root = ET.fromstring(response.text)
        papers: list[ImportedPaper] = []
        for article in root.findall(".//PubmedArticle"):
            paper = self._parse_pubmed_article(article)
            stats.inc("fetched")
            if not paper.abstract.strip():
                stats.inc("skipped_no_abstract")
                continue
            papers.append(paper)
        return self._rank_external_candidates(query=query, papers=papers)[:limit]

    async def _search_pubmed_ids(
        self,
        query: str,
        limit: int,
        year_from: int | None = None,
        year_to: int | None = None,
    ) -> list[str]:
        params = {
            "db": "pubmed",
            "term": self._build_pubmed_query(query, year_from, year_to),
            "retmode": "json",
            "retmax": limit,
            "sort": "relevance",
            "tool": settings.app_name,
        }
        if settings.pubmed_email:
            params["email"] = settings.pubmed_email
        if settings.pubmed_api_key:
            params["api_key"] = settings.pubmed_api_key

        async with httpx.AsyncClient(timeout=settings.external_api_timeout_seconds) as client:
            response = await client.get(PUBMED_ESEARCH_URL, params=params)
            response.raise_for_status()
        payload = response.json()
        ids = payload.get("esearchresult", {}).get("idlist", [])
        if ids:
            return [str(item) for item in ids]
        if params["term"] == query:
            return []
        params["term"] = self._build_pubmed_native_query(query, year_from, year_to)
        async with httpx.AsyncClient(timeout=settings.external_api_timeout_seconds) as client:
            response = await client.get(PUBMED_ESEARCH_URL, params=params)
            response.raise_for_status()
        payload = response.json()
        return [str(item) for item in payload.get("esearchresult", {}).get("idlist", [])]

    async def import_papers(
        self,
        papers: list[ImportedPaper],
        include_pdf: bool,
        stats: ImportStats,
        project_id: UUID | None = None,
        user_id: UUID | None = None,
    ) -> None:
        db = SessionLocal()
        try:
            if project_id and user_id:
                self._ensure_project_owned(db=db, project_id=project_id, user_id=user_id)
            for imported in papers:
                try:
                    paper = await self._import_one(db=db, imported=imported, include_pdf=include_pdf, stats=stats)
                    if paper and project_id and user_id:
                        self._link_project(db=db, project_id=project_id, paper_id=paper.id, stats=stats)
                        db.commit()
                except (EmbeddingError, VectorStoreError) as exc:
                    db.rollback()
                    stats.inc("skipped_embedding_failed")
                    stats.append_error(f"{imported.source}:{imported.source_id} skipped: {exc}")
                except SQLAlchemyError as exc:
                    db.rollback()
                    stats.error(f"{imported.source}:{imported.source_id} database failed: {exc}")
                except Exception as exc:
                    db.rollback()
                    stats.error(f"{imported.source}:{imported.source_id} import failed: {exc}")
        finally:
            db.close()

    async def _import_one(self, db, imported: ImportedPaper, include_pdf: bool, stats: ImportStats) -> Paper | None:
        if include_pdf:
            await self._resolve_pdf_for_import(imported, stats)

        paper = self._find_existing_paper(db, imported)
        if paper is not None:
            if imported.pdf_url and not paper.pdf_url:
                paper.pdf_url = imported.pdf_url
            if include_pdf and imported.pdf_url:
                if (
                    self._pdf_completed(paper)
                    and await self.vector_store.has_paper_chunks(paper.id)
                    and self._postgres_has_paper_chunks(db, paper.id)
                ):
                    stats.inc("pdf_already_processed")
                else:
                    stats.inc("pdf_retried")
                    await self.vector_store.delete_paper_chunks(paper.id)
                    db.query(PaperChunk).filter(PaperChunk.paper_id == paper.id).delete(synchronize_session=False)
                    pdf_result = await self._try_process_pdf(db=db, paper_id=paper.id, imported=imported, stats=stats)
                    self._set_pdf_metadata(paper, pdf_result)
                    db.commit()
            stats.inc("skipped_duplicate")
            return paper

        abstract_text = f"{imported.title}\n\n{imported.abstract}".strip()
        abstract_vector = await self.embeddings.embed_text(abstract_text)

        paper = Paper(id=uuid4())
        db.add(paper)

        self._apply_imported_fields(paper, imported)
        await self.vector_store.upsert_paper_abstract(
            paper_id=paper.id,
            vector=abstract_vector,
            metadata={
                "title": imported.title,
                "source": imported.source,
                "source_id": imported.source_id,
                "published_date": imported.published_date,
            },
        )
        stats.inc("abstract_vectorized")

        if include_pdf and imported.pdf_url:
            pdf_result = await self._try_process_pdf(db=db, paper_id=paper.id, imported=imported, stats=stats)
            self._set_pdf_metadata(paper, pdf_result)

        db.commit()
        stats.inc("created")
        return paper

    def _ensure_project_owned(self, db, project_id: UUID, user_id: UUID) -> None:
        project = db.query(Project).filter(Project.id == project_id, Project.user_id == user_id).first()
        if not project:
            raise ValueError("Project not found or not owned by current user")

    def _link_project(self, db, project_id: UUID, paper_id: UUID, stats: ImportStats) -> None:
        existing = db.get(ProjectPaper, {"project_id": project_id, "paper_id": paper_id})
        if existing:
            stats.inc("project_already_linked")
            return
        db.add(ProjectPaper(project_id=project_id, paper_id=paper_id))
        stats.inc("project_linked")

    def _find_existing_paper(self, db, imported: ImportedPaper) -> Paper | None:
        filters = [(Paper.source == imported.source) & (Paper.source_id == imported.source_id)]
        if imported.doi:
            filters.append(Paper.doi == imported.doi)
        return db.query(Paper).filter(or_(*filters)).first()

    def _apply_imported_fields(self, paper: Paper, imported: ImportedPaper) -> None:
        paper.title = imported.title
        paper.authors = imported.authors
        paper.abstract = imported.abstract
        paper.doi = imported.doi
        paper.source = imported.source
        paper.source_id = imported.source_id
        paper.published_date = imported.published_date
        paper.pdf_url = imported.pdf_url
        paper.citation_count = imported.citation_count
        paper.metadata_json = imported.metadata

    async def _resolve_pdf_for_import(self, imported: ImportedPaper, stats: ImportStats) -> None:
        if imported.pdf_url:
            return
        if imported.source != LiteratureSource.pubmed.value:
            return

        result = await self.pdf_resolver.resolve_pubmed_pdf(
            doi=imported.doi,
            pmc_id=str(imported.metadata.get("pmc_id") or ""),
            pmid=imported.source_id,
        )
        metadata = dict(imported.metadata or {})
        metadata["pdf_resolver"] = result.source
        metadata["doi_landing_url"] = result.landing_url
        metadata["resolved_pdf_url"] = result.pdf_url
        metadata["pdf_resolve_error"] = result.error
        imported.metadata = metadata
        imported.pdf_url = result.pdf_url
        if result.pdf_url:
            stats.inc("pdf_resolved")
        else:
            stats.inc("pdf_unresolved")
            stats.append_error(f"{imported.source}:{imported.source_id} PDF unresolved: {result.error}")

    async def _try_process_pdf(self, db, paper_id: UUID, imported: ImportedPaper, stats: ImportStats) -> PDFProcessResult:
        try:
            structured = await self._resolve_structured_full_text_for_import(imported=imported, stats=stats)
            if structured and structured.text:
                return await self._process_text_chunks(
                    db=db,
                    paper_id=paper_id,
                    imported=imported,
                    text=structured.text,
                    extraction_method=structured.source,
                    stats=stats,
                    structured_fulltext_url=structured.url,
                )

            download = await self._download_pdf(imported.pdf_url)
            pdf_bytes = download.content
            self._record_final_pdf_url(db=db, paper_id=paper_id, imported=imported, final_url=download.final_url)
            text, extraction_method = await self._extract_pdf_text(
                pdf_bytes=pdf_bytes,
                filename=f"{imported.source}-{imported.source_id}.pdf",
            )
            return await self._process_text_chunks(
                db=db,
                paper_id=paper_id,
                imported=imported,
                text=text,
                extraction_method=extraction_method,
                stats=stats,
                final_pdf_url=download.final_url,
            )
        except Exception as exc:
            stats.inc("pdf_skipped")
            manual_pdf_required = self._is_manual_pdf_required_error(exc)
            if manual_pdf_required:
                stats.inc("manual_pdf_required")
                stats.append_manual_pdf_required(
                    f"{imported.source}:{imported.source_id} {imported.title} | pdf_url={imported.pdf_url or ''}"
                )
            stats.append_error(f"{imported.source}:{imported.source_id} PDF skipped: {exc}")
            return PDFProcessResult(success=False, error=str(exc), manual_pdf_required=manual_pdf_required)

    async def _process_text_chunks(
        self,
        db,
        paper_id: UUID,
        imported: ImportedPaper,
        text: str,
        extraction_method: str,
        stats: ImportStats,
        final_pdf_url: str | None = None,
        structured_fulltext_url: str | None = None,
    ) -> PDFProcessResult:
            if self._is_unusable_extracted_text(text):
                stats.inc("pdf_skipped")
                return PDFProcessResult(
                    success=False,
                    error="PDF text extraction produced unusable text",
                    extraction_method=extraction_method,
                )
            chunks = self._chunk_text(text)
            if not chunks:
                stats.inc("pdf_skipped")
                return PDFProcessResult(
                    success=False,
                    error="PDF text extraction produced no chunks",
                    extraction_method=extraction_method,
                )

            for index, chunk in enumerate(chunks):
                chunk_id = self._chunk_id(paper_id, index)
                db.add(
                    PaperChunk(
                        id=chunk_id,
                        paper_id=paper_id,
                        chunk_index=index,
                        text=chunk,
                        chunk_type="body",
                        metadata_json={
                            "source": imported.source,
                            "source_id": imported.source_id,
                            "extraction_method": extraction_method,
                            "structured_fulltext_url": structured_fulltext_url,
                            "final_pdf_url": final_pdf_url,
                        },
                    )
                )
                vector = await self.embeddings.embed_text(chunk)
                await self.vector_store.upsert_chunk(
                    paper_id=paper_id,
                    chunk_id=str(chunk_id),
                    vector=vector,
                    text=chunk,
                    metadata={
                        "title": imported.title,
                        "source": imported.source,
                        "source_id": imported.source_id,
                        "locator": f"chunk:{index}",
                        "extraction_method": extraction_method,
                    },
                )
            stats.inc("pdf_processed")
            return PDFProcessResult(
                success=True,
                chunk_count=len(chunks),
                extraction_method=extraction_method,
                final_pdf_url=final_pdf_url,
                structured_fulltext_url=structured_fulltext_url,
            )

    async def _resolve_structured_full_text_for_import(
        self,
        imported: ImportedPaper,
        stats: ImportStats,
    ) -> StructuredFullTextResult | None:
        pmc_id = str(imported.metadata.get("pmc_id") or "").strip()
        if not pmc_id:
            pmc_id = self._pmc_id_from_url(imported.pdf_url) or ""
        if not pmc_id:
            return None

        result = await self.pdf_resolver.resolve_pmc_full_text(pmc_id)
        metadata = dict(imported.metadata or {})
        metadata["structured_fulltext_source"] = result.source
        metadata["structured_fulltext_url"] = result.url
        metadata["structured_fulltext_error"] = result.error
        imported.metadata = metadata
        if result.text:
            stats.inc("structured_fulltext_resolved")
            return result
        stats.inc("structured_fulltext_failed")
        return None

    def _pdf_completed(self, paper: Paper) -> bool:
        metadata = paper.metadata_json if isinstance(paper.metadata_json, dict) else {}
        return metadata.get("pdf_status") == "completed" and int(metadata.get("pdf_chunk_count") or 0) > 0

    def _postgres_has_paper_chunks(self, db, paper_id: UUID) -> bool:
        return db.query(PaperChunk.id).filter(PaperChunk.paper_id == paper_id).first() is not None

    def _set_pdf_metadata(self, paper: Paper, result: PDFProcessResult) -> None:
        metadata = dict(paper.metadata_json or {})
        metadata["pdf_status"] = "completed" if result.success else "failed"
        metadata["pdf_chunk_count"] = result.chunk_count
        metadata["pdf_last_error"] = result.error
        metadata["pdf_text_extraction_method"] = result.extraction_method
        metadata["manual_pdf_required"] = result.manual_pdf_required
        if result.structured_fulltext_url:
            metadata["structured_fulltext_url"] = result.structured_fulltext_url
        if result.final_pdf_url:
            metadata["final_pdf_url"] = result.final_pdf_url
        paper.metadata_json = metadata

    def _record_final_pdf_url(self, db, paper_id: UUID, imported: ImportedPaper, final_url: str | None) -> None:
        if not final_url or final_url == imported.pdf_url:
            return
        requested_url = imported.pdf_url
        imported.pdf_url = final_url
        paper = db.get(Paper, paper_id) if hasattr(db, "get") else None
        if not paper:
            return
        metadata = dict(paper.metadata_json or {})
        metadata["requested_pdf_url"] = requested_url
        metadata["final_pdf_url"] = final_url
        paper.pdf_url = final_url
        paper.metadata_json = metadata

    async def _download_pdf(self, pdf_url: str | None) -> PDFDownloadResult:
        if not pdf_url:
            raise ValueError("PDF URL is empty")

        max_bytes = settings.pdf_max_size_mb * 1024 * 1024
        async with httpx.AsyncClient(timeout=settings.pdf_download_timeout_seconds, follow_redirects=True) as client:
            response = await client.get(pdf_url, headers=self._pdf_download_headers(pdf_url))
            response.raise_for_status()
            content_length = response.headers.get("content-length")
            if content_length and int(content_length) > max_bytes:
                raise ValueError(f"PDF is larger than {settings.pdf_max_size_mb}MB")
            content = response.content
            if self._looks_like_html_response(content=content, content_type=response.headers.get("content-type")):
                resolved_url = self.pdf_resolver.extract_pdf_url_from_html(
                    content.decode("utf-8", errors="replace"),
                    base_url=str(response.url),
                )
                if not resolved_url:
                    pmc_id = self._pmc_id_from_url(str(response.url)) or self._pmc_id_from_url(pdf_url)
                    if pmc_id:
                        resolved = await self.pdf_resolver.resolve_pmc_pdf(pmc_id)
                        resolved_url = resolved.pdf_url
                if self._should_retry_pdf_url(current_url=str(response.url), resolved_url=resolved_url):
                    response = await client.get(resolved_url, headers=self._pdf_download_headers(resolved_url))
                    response.raise_for_status()
                    content_length = response.headers.get("content-length")
                    if content_length and int(content_length) > max_bytes:
                        raise ValueError(f"PDF is larger than {settings.pdf_max_size_mb}MB")
                    content = response.content
            if len(content) > max_bytes:
                raise ValueError(f"PDF is larger than {settings.pdf_max_size_mb}MB")
            self._validate_pdf_response(content=content, content_type=response.headers.get("content-type"), url=pdf_url)
            return PDFDownloadResult(content=content, final_url=str(response.url))

    def _pdf_download_headers(self, pdf_url: str) -> dict[str, str]:
        parsed = urlparse(pdf_url)
        referer = pdf_url[:-4] if parsed.path.lower().endswith(".pdf") else pdf_url
        return {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0 Safari/537.36"
            ),
            "Accept": "application/pdf,application/octet-stream;q=0.9,text/html;q=0.8,*/*;q=0.7",
            "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "Referer": referer,
        }

    def _looks_like_html_response(self, content: bytes, content_type: str | None) -> bool:
        if content.lstrip().startswith(b"%PDF-"):
            return False
        lowered_type = (content_type or "").lower()
        if "html" in lowered_type:
            return True
        preview = content[:200].lower()
        return b"<html" in preview or b"<!doctype html" in preview

    def _should_retry_pdf_url(self, current_url: str, resolved_url: str | None) -> bool:
        if not resolved_url or resolved_url == current_url:
            return False
        current_is_pdf = current_url.lower().split("?", 1)[0].endswith(".pdf")
        resolved_is_pdf = resolved_url.lower().split("?", 1)[0].endswith(".pdf")
        return not current_is_pdf or resolved_is_pdf

    def _pmc_id_from_url(self, url: str | None) -> str | None:
        if not url:
            return None
        match = re.search(r"\bPMC\d+\b", url, flags=re.IGNORECASE)
        return match.group(0).upper() if match else None

    def _validate_pdf_response(self, content: bytes, content_type: str | None, url: str) -> None:
        if content.lstrip().startswith(b"%PDF-"):
            return
        preview = content[:200].decode("utf-8", errors="replace").replace("\n", " ")
        lowered = preview.lower()
        if "recaptcha" in lowered or "challengepage" in lowered:
            raise ValueError(
                "Downloaded file is blocked by reCAPTCHA instead of a PDF. "
                f"url={url}, content_type={content_type or 'unknown'}, bytes={len(content)}, preview={preview}"
            )
        raise ValueError(
            "Downloaded file is not a PDF. "
            f"url={url}, content_type={content_type or 'unknown'}, bytes={len(content)}, preview={preview}"
        )

    def _is_manual_pdf_required_error(self, exc: Exception) -> bool:
        lowered = str(exc).lower()
        return any(
            marker in lowered
            for marker in (
                "blocked by recaptcha",
                "recaptcha",
                "challengepage",
                "not a pdf",
                "pdf unresolved",
                "no pdf link",
            )
        )

    async def _extract_pdf_text(self, pdf_bytes: bytes, filename: str) -> tuple[str, str]:
        native_text = self._extract_pdf_text_native(pdf_bytes)
        errors: list[str] = []

        if settings.pdf_multimodal_enabled:
            try:
                images = self._render_pdf_page_images(pdf_bytes, max_pages=settings.pdf_multimodal_max_pages)
                if settings.pdf_multimodal_image_transport.lower().strip() == "url":
                    try:
                        image_urls = self._write_pdf_page_image_urls(
                            images=images,
                            namespace=f"external_pdf_{uuid4().hex}",
                        )
                        multimodal_text = (
                            await self.llm.extract_text_from_image_urls(image_urls=image_urls, filename=filename)
                        ).strip()
                    except Exception:
                        multimodal_text = (
                            await self.llm.extract_text_from_images(images=images, filename=filename)
                        ).strip()
                else:
                    multimodal_text = (await self.llm.extract_text_from_images(images=images, filename=filename)).strip()
                if multimodal_text:
                    combined = self._combine_extracted_text(
                        primary_text=multimodal_text,
                        secondary_text=native_text,
                        marker="NATIVE_TEXT_FALLBACK",
                    )
                    method = "multimodal+native" if native_text else "multimodal"
                    return combined, method
            except Exception as exc:
                errors.append(str(exc))

        if native_text and not self._is_unusable_extracted_text(native_text):
            return native_text, "native"
        detail = " | ".join(errors) if errors else "no readable text"
        raise ValueError(f"PDF text extraction failed: {detail}")

    def _extract_pdf_text_native(self, pdf_bytes: bytes) -> str:
        with fitz.open(stream=pdf_bytes, filetype="pdf") as document:
            return "\n".join(page.get_text("text") for page in document).strip()

    def _render_pdf_page_images(self, pdf_bytes: bytes, max_pages: int) -> list[bytes]:
        images: list[bytes] = []
        matrix = fitz.Matrix(settings.pdf_render_zoom, settings.pdf_render_zoom)
        with fitz.open(stream=pdf_bytes, filetype="pdf") as document:
            page_count = min(max_pages, document.page_count)
            for page_index in range(page_count):
                page = document.load_page(page_index)
                pixmap = page.get_pixmap(matrix=matrix, alpha=False)
                images.append(pixmap.tobytes("png"))
        return images

    def _render_pdf_page_image_urls(self, pdf_bytes: bytes, max_pages: int, namespace: str) -> list[str]:
        images = self._render_pdf_page_images(pdf_bytes, max_pages=max_pages)
        return self._write_pdf_page_image_urls(images=images, namespace=namespace)

    def _write_pdf_page_image_urls(self, images: list[bytes], namespace: str) -> list[str]:
        output_dir = Path(settings.generated_image_dir) / namespace
        output_dir.mkdir(parents=True, exist_ok=True)
        base_url = settings.generated_image_base_url.rstrip("/")
        urls: list[str] = []
        for index, image_bytes in enumerate(images, start=1):
            filename = f"page_{index}.png"
            (output_dir / filename).write_bytes(image_bytes)
            urls.append(f"{base_url}/{namespace}/{filename}")
        return urls

    def _combine_extracted_text(self, primary_text: str, secondary_text: str, marker: str) -> str:
        primary_text = primary_text.strip()
        secondary_text = secondary_text.strip()
        if not primary_text:
            return secondary_text
        if not secondary_text:
            return primary_text
        if secondary_text in primary_text:
            return primary_text
        return f"{primary_text}\n\n[{marker}]\n\n{secondary_text}"

    def _is_unusable_extracted_text(self, text: str | None) -> bool:
        value = str(text or "").strip()
        if not value:
            return True
        lowered = value.lower()
        markers = (
            "[unsupported image]",
            "unsupported image",
            "[无法识别]",
            "无法看到上传的图片内容",
            "图片显示为",
            "无法读取图片内容",
            "无法识别图片内容",
            "不能读取图片",
            "不支持图片",
            "图片格式不被支持",
            "未能成功上传",
            "重新上传",
            "直接上传可读取的 pdf",
            "收到可用的图片后",
        )
        if any(marker in lowered for marker in markers):
            return True
        meaningful = "".join(ch for ch in value if ch.isalnum() or "\u4e00" <= ch <= "\u9fff")
        return len(meaningful) < 80

    def _chunk_text(self, text: str) -> list[str]:
        normalized = re.sub(r"\s+", " ", text).strip()
        if not normalized:
            return []

        chunk_size = settings.pdf_chunk_size
        overlap = min(settings.pdf_chunk_overlap, chunk_size // 2)
        chunks: list[str] = []
        start = 0
        while start < len(normalized):
            end = min(start + chunk_size, len(normalized))
            chunk = normalized[start:end].strip()
            if chunk:
                chunks.append(chunk)
            if end >= len(normalized):
                break
            start = max(0, end - overlap)
        return chunks

    def _parse_arxiv_entry(self, entry: ET.Element) -> ImportedPaper:
        raw_id = self._text(entry, "atom:id")
        arxiv_id_with_version = raw_id.rsplit("/", 1)[-1]
        source_id = re.sub(r"v\d+$", "", arxiv_id_with_version)
        title = self._clean_text(self._text(entry, "atom:title"))
        abstract = self._clean_text(self._text(entry, "atom:summary"))
        published_date = self._parse_date(self._text(entry, "atom:published"))
        doi = self._text(entry, "arxiv:doi") or None
        categories = [
            category.attrib.get("term")
            for category in entry.findall("atom:category", ATOM_NS)
            if category.attrib.get("term")
        ]

        return ImportedPaper(
            title=title,
            authors=[
                {"name": self._clean_text(self._text(author, "atom:name"))}
                for author in entry.findall("atom:author", ATOM_NS)
            ],
            abstract=abstract,
            doi=doi,
            source=LiteratureSource.arxiv.value,
            source_id=source_id,
            published_date=published_date,
            pdf_url=self._extract_arxiv_pdf_url(entry, source_id),
            citation_count=0,
            metadata={
                "arxiv_id": source_id,
                "arxiv_versioned_id": arxiv_id_with_version,
                "entry_id": raw_id,
                "updated": self._text(entry, "atom:updated"),
                "categories": categories,
                "primary_category": categories[0] if categories else None,
            },
        )

    def _parse_pubmed_article(self, article: ET.Element) -> ImportedPaper:
        pmid = self._text(article, ".//MedlineCitation/PMID")
        title = self._clean_text(self._iter_text(article.find(".//ArticleTitle")))
        abstract = self._clean_text(
            " ".join(
                self._abstract_text_with_label(node)
                for node in article.findall(".//Abstract/AbstractText")
                if self._iter_text(node)
            )
        )
        journal = self._clean_text(self._text(article, ".//Journal/Title"))
        journal_iso = self._clean_text(self._text(article, ".//Journal/ISOAbbreviation"))
        doi = self._pubmed_doi(article)
        pmc_id = self._pubmed_article_id(article, "pmc")
        pii = self._pubmed_article_id(article, "pii")
        published_date = self._parse_pubmed_date(article)

        return ImportedPaper(
            title=title or f"PubMed {pmid}",
            authors=self._parse_pubmed_authors(article),
            abstract=abstract,
            doi=doi,
            source=LiteratureSource.pubmed.value,
            source_id=pmid,
            published_date=published_date,
            pdf_url=None,
            citation_count=0,
            metadata={
                "pmid": pmid,
                "pmc_id": pmc_id,
                "pii": pii,
                "journal": journal,
                "journal_iso": journal_iso,
                "publication_types": [
                    self._clean_text(self._iter_text(node))
                    for node in article.findall(".//PublicationTypeList/PublicationType")
                ],
            },
        )

    def _to_candidate(self, paper: ImportedPaper) -> ImportCandidatePaper:
        return ImportCandidatePaper(
            title=paper.title,
            authors=paper.authors,
            abstract=paper.abstract,
            doi=paper.doi,
            source=paper.source,
            source_id=paper.source_id,
            published_date=paper.published_date,
            pdf_url=paper.pdf_url,
            citation_count=paper.citation_count,
            metadata=paper.metadata,
        )

    def _from_candidate(self, candidate: ImportCandidatePaper) -> ImportedPaper:
        return ImportedPaper(
            title=candidate.title,
            authors=candidate.authors,
            abstract=candidate.abstract,
            doi=candidate.doi,
            source=candidate.source,
            source_id=candidate.source_id,
            published_date=candidate.published_date,
            pdf_url=candidate.pdf_url,
            citation_count=candidate.citation_count,
            metadata=candidate.metadata,
        )

    def _extract_arxiv_pdf_url(self, entry: ET.Element, source_id: str) -> str:
        for link in entry.findall("atom:link", ATOM_NS):
            if link.attrib.get("title") == "pdf" and link.attrib.get("href"):
                return link.attrib["href"]
        return f"https://arxiv.org/pdf/{source_id}"

    def _text(self, element: ET.Element, path: str) -> str:
        child = element.find(path, ATOM_NS)
        return child.text.strip() if child is not None and child.text else ""

    def _iter_text(self, element: ET.Element | None) -> str:
        return "".join(element.itertext()).strip() if element is not None else ""

    def _abstract_text_with_label(self, element: ET.Element) -> str:
        text = self._clean_text(self._iter_text(element))
        label = element.attrib.get("Label")
        return f"{label}: {text}" if label else text

    def _clean_text(self, text: str) -> str:
        return re.sub(r"\s+", " ", text).strip()

    def _parse_date(self, value: str) -> date | None:
        if not value:
            return None
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None

    def _parse_pubmed_date(self, article: ET.Element) -> date | None:
        article_date = article.find(".//ArticleDate")
        parsed = self._parse_pubmed_date_node(article_date)
        if parsed:
            return parsed
        return self._parse_pubmed_date_node(article.find(".//JournalIssue/PubDate"))

    def _parse_pubmed_date_node(self, node: ET.Element | None) -> date | None:
        if node is None:
            return None
        year = self._node_child_text(node, "Year")
        month = self._node_child_text(node, "Month")
        day = self._node_child_text(node, "Day")
        if not year or not year.isdigit():
            medline_date = self._node_child_text(node, "MedlineDate")
            year_match = re.search(r"\d{4}", medline_date)
            year = year_match.group(0) if year_match else ""
        if not year:
            return None
        return date(int(year), self._pubmed_month_to_int(month), int(day) if day.isdigit() else 1)

    def _pubmed_month_to_int(self, value: str) -> int:
        if not value:
            return 1
        if value.isdigit():
            return max(1, min(int(value), 12))
        months = {
            "jan": 1,
            "feb": 2,
            "mar": 3,
            "apr": 4,
            "may": 5,
            "jun": 6,
            "jul": 7,
            "aug": 8,
            "sep": 9,
            "oct": 10,
            "nov": 11,
            "dec": 12,
        }
        return months.get(value[:3].lower(), 1)

    def _node_child_text(self, node: ET.Element, child_name: str) -> str:
        child = node.find(child_name)
        return child.text.strip() if child is not None and child.text else ""

    def _chunk_id(self, paper_id: UUID, index: int) -> UUID:
        return uuid5(NAMESPACE_URL, f"litsage:paper:{paper_id}:chunk:{index}")

    def _build_arxiv_query(self, query: str, year_from: int | None = None, year_to: int | None = None) -> str:
        terms = self._query_terms(query)
        if not terms:
            clauses = [f"all:{query}"]
        else:
            clauses = [f"(ti:{term} OR abs:{term})" for term in terms[:8]]
        if year_from or year_to:
            start_year = year_from or 1900
            end_year = year_to or 2100
            clauses.append(f"submittedDate:[{start_year}01010000 TO {end_year}12312359]")
        return " AND ".join(clauses)

    def _build_pubmed_query(self, query: str, year_from: int | None = None, year_to: int | None = None) -> str:
        terms = self._query_terms(query)
        if not terms:
            return self._build_pubmed_native_query(query, year_from, year_to)
        clauses = [f'("{term}"[Title/Abstract])' for term in terms[:8]]
        if year_from or year_to:
            clauses.append(self._pubmed_date_clause(year_from, year_to))
        return " AND ".join(clauses)

    def _build_pubmed_native_query(self, query: str, year_from: int | None = None, year_to: int | None = None) -> str:
        if not year_from and not year_to:
            return query
        return f"({query}) AND {self._pubmed_date_clause(year_from, year_to)}"

    def _pubmed_date_clause(self, year_from: int | None, year_to: int | None) -> str:
        start_year = year_from or 1900
        end_year = year_to or 2100
        return f'("{start_year}/01/01"[Date - Publication] : "{end_year}/12/31"[Date - Publication])'

    def _parse_pubmed_authors(self, article: ET.Element) -> list[dict]:
        authors: list[dict] = []
        for author in article.findall(".//AuthorList/Author"):
            collective = self._node_child_text(author, "CollectiveName")
            if collective:
                authors.append({"name": collective})
                continue
            last_name = self._node_child_text(author, "LastName")
            fore_name = self._node_child_text(author, "ForeName")
            initials = self._node_child_text(author, "Initials")
            name = self._clean_text(" ".join(part for part in [fore_name or initials, last_name] if part))
            if name:
                authors.append({"name": name})
        return authors

    def _pubmed_doi(self, article: ET.Element) -> str | None:
        for node in article.findall(".//ArticleIdList/ArticleId"):
            if node.attrib.get("IdType") == "doi" and node.text:
                return node.text.strip()
        for node in article.findall(".//ELocationID"):
            if node.attrib.get("EIdType") == "doi" and node.text:
                return node.text.strip()
        return None

    def _pubmed_article_id(self, article: ET.Element, id_type: str) -> str | None:
        for node in article.findall(".//ArticleIdList/ArticleId"):
            if node.attrib.get("IdType") == id_type and node.text:
                return node.text.strip()
        return None

    def _rank_external_candidates(self, query: str, papers: list[ImportedPaper]) -> list[ImportedPaper]:
        terms = set(self._query_terms(query))
        if not terms:
            return papers

        def score(paper: ImportedPaper) -> tuple[float, date]:
            title = paper.title.lower()
            abstract = paper.abstract.lower()
            title_hits = sum(1 for term in terms if term in title)
            abstract_hits = sum(1 for term in terms if term in abstract)
            published = paper.published_date or date.min
            return (title_hits * 3 + abstract_hits, published)

        ranked = sorted(papers, key=score, reverse=True)
        return [paper for paper in ranked if score(paper)[0] > 0]

    def _dedupe_imported(self, papers: list[ImportedPaper]) -> list[ImportedPaper]:
        deduped: list[ImportedPaper] = []
        seen: set[tuple[str, str]] = set()
        for paper in papers:
            key = (paper.source, paper.source_id)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(paper)
        return deduped

    def _external_candidate_limit(self, limit: int) -> int:
        multiplier = max(1, settings.search_external_candidate_multiplier)
        return max(limit * multiplier, limit)

    def _query_terms(self, query: str) -> list[str]:
        stop_words = {
            "the",
            "and",
            "for",
            "with",
            "using",
            "use",
            "uses",
            "into",
            "from",
            "that",
            "this",
            "中的",
            "应用",
            "研究",
        }
        terms = []
        for term in re.findall(r"[\w\u4e00-\u9fff]+", query.lower()):
            if len(term) < 2 or term in stop_words:
                continue
            terms.append(term)
        return list(dict.fromkeys(terms))

    def _build_message(self, stats: ImportStats) -> str:
        values = stats.values
        return (
            f"Fetched {values['fetched']} papers, created {values['created']}, "
            f"updated {values['updated']}, skipped duplicate {values['skipped_duplicate']}, "
            f"skipped no abstract {values['skipped_no_abstract']}, "
            f"pdf retried {values['pdf_retried']}, pdf already processed {values['pdf_already_processed']}, "
            f"pdf resolved {values['pdf_resolved']}, pdf unresolved {values['pdf_unresolved']}, "
            f"manual PDF required {values['manual_pdf_required']}, "
            f"skipped embedding/vector {values['skipped_embedding_failed']}, failed {values['failed']}."
        )
