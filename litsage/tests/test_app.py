from datetime import date
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.models.db import Paper
from app.models.schemas import ImportCandidatePaper
from app.services.email_verification_service import EmailVerificationService
from app.services.paper_importer import ImportedPaper, ImportStats, PaperImporter
from app.services.summary_service import SummaryService


def test_health() -> None:
    client = TestClient(create_app())
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_summary_text_uses_paper_metadata_and_abstract() -> None:
    paper = Paper(
        title="Liver Cancer Detection with Deep Learning",
        authors=[{"name": "Ada Chen"}],
        abstract="This paper studies hepatocellular carcinoma detection from medical images.",
        doi="10.1000/litsage.test",
        source="arxiv",
        source_id="2608.00001",
        citation_count=3,
    )

    text = SummaryService()._paper_to_summary_text(paper)

    assert "Liver Cancer Detection with Deep Learning" in text
    assert "Ada Chen" in text
    assert "10.1000/litsage.test" in text
    assert "hepatocellular carcinoma detection" in text
    assert text != f"paper_id={paper.id}"


def test_email_verification_code_is_single_use() -> None:
    service = EmailVerificationService()
    code = service.create_code("user@example.com")

    assert len(code) == 6
    assert service.verify_code("USER@example.com", code)
    assert not service.verify_code("user@example.com", code)


def test_import_candidate_round_trip() -> None:
    importer = PaperImporter()
    paper = ImportedPaper(
        title="Selected Liver Cancer Paper",
        authors=[{"name": "Ada Chen"}],
        abstract="A candidate selected by the user before import.",
        doi=None,
        source="arxiv",
        source_id="2608.00001",
        published_date=date(2026, 8, 1),
        pdf_url="https://arxiv.org/pdf/2608.00001",
        citation_count=0,
        metadata={"primary_category": "cs.CV"},
    )

    candidate = importer._to_candidate(paper)
    restored = importer._from_candidate(ImportCandidatePaper.model_validate(candidate.model_dump()))

    assert candidate.title == paper.title
    assert restored.source_id == paper.source_id
    assert restored.metadata["primary_category"] == "cs.CV"


class ExistingPaperQuery:
    def filter(self, *_args):
        return self

    def first(self) -> Paper:
        return Paper(id=uuid4(), title="Existing", source="arxiv", source_id="2608.00001", metadata_json={})


class ExistingPaperSession:
    def query(self, _model):
        return ExistingPaperQuery()

    def commit(self):
        return None


class FailingEmbeddingService:
    async def embed_text(self, _text: str) -> list[float]:
        raise AssertionError("Embedding should not be called for duplicate papers")


class EmptyChunkVectorStore:
    async def has_paper_chunks(self, _paper_id):
        return False

    async def delete_paper_chunks(self, _paper_id):
        return 0


@pytest.mark.asyncio
async def test_duplicate_import_skips_before_embedding() -> None:
    importer = PaperImporter()
    importer.embeddings = FailingEmbeddingService()
    stats = ImportStats()
    paper = ImportedPaper(
        title="Duplicate Liver Cancer Paper",
        authors=[],
        abstract="Already imported.",
        doi=None,
        source="arxiv",
        source_id="2608.00001",
        published_date=None,
        pdf_url=None,
        citation_count=0,
        metadata={},
    )

    await importer._import_one(db=ExistingPaperSession(), imported=paper, include_pdf=False, stats=stats)

    assert stats.values["skipped_duplicate"] == 1
    assert stats.values["created"] == 0
    assert stats.values["abstract_vectorized"] == 0


@pytest.mark.asyncio
async def test_duplicate_import_retries_missing_pdf_chunks() -> None:
    importer = PaperImporter()
    importer.embeddings = FailingEmbeddingService()
    importer._vector_store = EmptyChunkVectorStore()
    stats = ImportStats()
    calls = []

    async def fake_process_pdf(paper_id, imported, stats):
        calls.append((paper_id, imported.source_id))
        stats.inc("pdf_processed")
        from app.services.paper_importer import PDFProcessResult

        return PDFProcessResult(success=True, chunk_count=3)

    importer._try_process_pdf = fake_process_pdf
    paper = ImportedPaper(
        title="Duplicate Liver Cancer Paper",
        authors=[],
        abstract="Already imported.",
        doi=None,
        source="arxiv",
        source_id="2608.00001",
        published_date=None,
        pdf_url="https://arxiv.org/pdf/2608.00001",
        citation_count=0,
        metadata={},
    )

    await importer._import_one(db=ExistingPaperSession(), imported=paper, include_pdf=True, stats=stats)

    assert len(calls) == 1
    assert stats.values["skipped_duplicate"] == 1
    assert stats.values["pdf_retried"] == 1
    assert stats.values["pdf_processed"] == 1
    assert stats.values["abstract_vectorized"] == 0


class ExistingCompletedPDFQuery:
    def filter(self, *_args):
        return self

    def first(self) -> Paper:
        return Paper(
            id=uuid4(),
            title="Existing",
            source="arxiv",
            source_id="2608.00001",
            metadata_json={"pdf_status": "completed", "pdf_chunk_count": 3},
        )


class ExistingCompletedPDFSession:
    def query(self, _model):
        return ExistingCompletedPDFQuery()


class ExistingChunkVectorStore:
    async def has_paper_chunks(self, _paper_id):
        return True


@pytest.mark.asyncio
async def test_duplicate_import_skips_pdf_only_when_completed_marker_exists() -> None:
    importer = PaperImporter()
    importer.embeddings = FailingEmbeddingService()
    importer._vector_store = ExistingChunkVectorStore()
    stats = ImportStats()
    paper = ImportedPaper(
        title="Duplicate Liver Cancer Paper",
        authors=[],
        abstract="Already imported.",
        doi=None,
        source="arxiv",
        source_id="2608.00001",
        published_date=None,
        pdf_url="https://arxiv.org/pdf/2608.00001",
        citation_count=0,
        metadata={},
    )

    await importer._import_one(db=ExistingCompletedPDFSession(), imported=paper, include_pdf=True, stats=stats)

    assert stats.values["skipped_duplicate"] == 1
    assert stats.values["pdf_already_processed"] == 1
    assert stats.values["pdf_retried"] == 0

