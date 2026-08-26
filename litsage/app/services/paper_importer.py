from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date
from uuid import UUID, uuid4

import fitz
import httpx
from sqlalchemy import or_
from sqlalchemy.exc import SQLAlchemyError

from app.config import settings
from app.models.db import Paper, SessionLocal
from app.models.schemas import ImportPapersRequest, ImportPapersResponse, LiteratureSource
from app.services.embedding_service import EmbeddingError, EmbeddingService
from app.services.vector_store import VectorStore, VectorStoreError

ATOM_NS = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
ARXIV_API_URL = "https://export.arxiv.org/api/query"


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


class ImportStats:
    def __init__(self) -> None:
        self.values: dict[str, int | list[str]] = {
            "fetched": 0,
            "created": 0,
            "updated": 0,
            "skipped_no_abstract": 0,
            "skipped_embedding_failed": 0,
            "abstract_vectorized": 0,
            "pdf_processed": 0,
            "pdf_skipped": 0,
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


class PaperImporter:
    def __init__(self) -> None:
        self.embeddings = EmbeddingService()
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

    async def import_from_sources(self, task_id: UUID, payload: ImportPapersRequest) -> dict[str, int | list[str]]:
        _ = task_id
        stats = ImportStats()
        papers = await self.fetch_from_sources(payload=payload, stats=stats)
        await self.import_papers(papers=papers, include_pdf=payload.include_pdf, stats=stats)
        return stats.values

    async def fetch_from_sources(self, payload: ImportPapersRequest, stats: ImportStats) -> list[ImportedPaper]:
        imported: list[ImportedPaper] = []
        for source in payload.sources:
            try:
                if source == LiteratureSource.arxiv:
                    imported.extend(await self.fetch_arxiv(payload.query, payload.limit, stats))
                elif source == LiteratureSource.semantic_scholar:
                    stats.error("Semantic Scholar importer is reserved but not implemented yet.")
                elif source == LiteratureSource.pubmed:
                    stats.error("PubMed importer is reserved but not implemented yet.")
            except Exception as exc:
                stats.error(f"{source.value} fetch failed: {exc}")
        return imported[: payload.limit]

    async def fetch_arxiv(self, query: str, limit: int, stats: ImportStats) -> list[ImportedPaper]:
        params = {
            "search_query": f"all:{query}",
            "start": 0,
            "max_results": limit,
            "sortBy": "submittedDate",
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
        return papers

    async def import_papers(self, papers: list[ImportedPaper], include_pdf: bool, stats: ImportStats) -> None:
        db = SessionLocal()
        try:
            for imported in papers:
                try:
                    await self._import_one(db=db, imported=imported, include_pdf=include_pdf, stats=stats)
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

    async def _import_one(self, db, imported: ImportedPaper, include_pdf: bool, stats: ImportStats) -> None:
        abstract_text = f"{imported.title}\n\n{imported.abstract}".strip()
        abstract_vector = await self.embeddings.embed_text(abstract_text)

        paper = self._find_existing_paper(db, imported)
        is_created = paper is None
        if paper is None:
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
            await self._try_process_pdf(paper_id=paper.id, imported=imported, stats=stats)

        db.commit()
        stats.inc("created" if is_created else "updated")

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

    async def _try_process_pdf(self, paper_id: UUID, imported: ImportedPaper, stats: ImportStats) -> None:
        try:
            pdf_bytes = await self._download_pdf(imported.pdf_url)
            text = self._extract_pdf_text(pdf_bytes)
            chunks = self._chunk_text(text)
            if not chunks:
                stats.inc("pdf_skipped")
                return

            for index, chunk in enumerate(chunks):
                vector = await self.embeddings.embed_text(chunk)
                await self.vector_store.upsert_chunk(
                    paper_id=paper_id,
                    chunk_id=self._chunk_id(paper_id, index),
                    vector=vector,
                    text=chunk,
                    metadata={
                        "title": imported.title,
                        "source": imported.source,
                        "source_id": imported.source_id,
                        "locator": f"chunk:{index}",
                    },
                )
            stats.inc("pdf_processed")
        except Exception as exc:
            stats.inc("pdf_skipped")
            stats.append_error(f"{imported.source}:{imported.source_id} PDF skipped: {exc}")

    async def _download_pdf(self, pdf_url: str | None) -> bytes:
        if not pdf_url:
            raise ValueError("PDF URL is empty")

        max_bytes = settings.pdf_max_size_mb * 1024 * 1024
        async with httpx.AsyncClient(timeout=settings.pdf_download_timeout_seconds, follow_redirects=True) as client:
            response = await client.get(pdf_url)
            response.raise_for_status()
            content_length = response.headers.get("content-length")
            if content_length and int(content_length) > max_bytes:
                raise ValueError(f"PDF is larger than {settings.pdf_max_size_mb}MB")
            content = response.content
            if len(content) > max_bytes:
                raise ValueError(f"PDF is larger than {settings.pdf_max_size_mb}MB")
            return content

    def _extract_pdf_text(self, pdf_bytes: bytes) -> str:
        with fitz.open(stream=pdf_bytes, filetype="pdf") as document:
            return "\n".join(page.get_text("text") for page in document).strip()

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

    def _extract_arxiv_pdf_url(self, entry: ET.Element, source_id: str) -> str:
        for link in entry.findall("atom:link", ATOM_NS):
            if link.attrib.get("title") == "pdf" and link.attrib.get("href"):
                return link.attrib["href"]
        return f"https://arxiv.org/pdf/{source_id}"

    def _text(self, element: ET.Element, path: str) -> str:
        child = element.find(path, ATOM_NS)
        return child.text.strip() if child is not None and child.text else ""

    def _clean_text(self, text: str) -> str:
        return re.sub(r"\s+", " ", text).strip()

    def _parse_date(self, value: str) -> date | None:
        if not value:
            return None
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None

    def _chunk_id(self, paper_id: UUID, index: int) -> str:
        digest = hashlib.sha1(f"{paper_id}:{index}".encode("utf-8")).hexdigest()[:16]
        return f"{paper_id}:{digest}:{index}"

    def _build_message(self, stats: ImportStats) -> str:
        values = stats.values
        return (
            f"Fetched {values['fetched']} papers, created {values['created']}, "
            f"updated {values['updated']}, skipped no abstract {values['skipped_no_abstract']}, "
            f"skipped embedding/vector {values['skipped_embedding_failed']}, failed {values['failed']}."
        )
