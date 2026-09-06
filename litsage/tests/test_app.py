from datetime import date
import xml.etree.ElementTree as ET
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.api.dependencies import get_current_user_id, get_db
from app.models.db import Paper, Project, ProjectQA
from app.models.schemas import Citation, ImportCandidatePaper, UploadMaterialResponse
from app.services.email_verification_service import EmailVerificationService
from app.llm.llm_client import LLMClient, LLMClientError
from app.services.paper_importer import ImportedPaper, ImportStats, PaperImporter
from app.services.paper_catalog_service import PaperCatalogService
from app.services.pdf_resolver import PDFResolveResult, PDFResolver, StructuredFullTextResult
from app.services.rag_service import RAGService
from app.services.search_service import SearchService
from app.services.summary_service import SummaryService
from app.services.user_material_importer import UserMaterialImporter


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


def test_project_summary_formatters_tolerate_empty_legacy_fields() -> None:
    service = SummaryService()
    paper = Paper(title="Legacy Paper", authors=None, abstract=None, source="pubmed", source_id="123")
    qa = ProjectQA(project_id=uuid4(), user_id=uuid4(), question="研究方法是什么？", answer=None)

    paper_text = service._format_project_papers([paper])
    qa_text = service._format_project_qas([qa])

    assert "Legacy Paper" in paper_text
    assert "暂无摘要" in paper_text
    assert "未记录回答" in qa_text


@pytest.mark.asyncio
async def test_project_summary_falls_back_when_llm_fails() -> None:
    service = SummaryService()

    async def fail_generate(**_kwargs):
        raise RuntimeError("LLM timeout")

    service.llm._generate = fail_generate
    project = Project(id=uuid4(), user_id=uuid4(), name="肝癌研究", description=None)
    paper = Paper(title="Liver cancer paper", authors=[], abstract="A study about liver cancer.", source="pubmed", source_id="1")

    markdown = await service._generate_project_summary(project=project, papers=[paper], qas=[])

    assert "## 阶段性结论" in markdown
    assert "大模型生成失败" in markdown
    assert "Liver cancer paper" in markdown


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


def test_user_material_importer_extracts_declared_abstract() -> None:
    importer = UserMaterialImporter()
    text = """
    Breast Cancer Review

    Abstract
    Breast cancer is a heterogeneous disease with multiple molecular subtypes.
    This review summarizes risk factors, screening methods, diagnosis, and
    clinical challenges across recent studies.

    Keywords: breast cancer; diagnosis

    1. Introduction
    The following section should not be included.
    """

    abstract = importer._extract_declared_abstract(text)

    assert "heterogeneous disease" in abstract
    assert "Introduction" not in abstract


def test_rag_context_uses_numbered_sources_and_real_titles() -> None:
    service = RAGService.__new__(RAGService)
    paper_id = uuid4()
    chunk_id = str(uuid4())
    evidence = [
        {
            "paper_id": paper_id,
            "title": "Breast Cancer Review",
            "chunk_id": chunk_id,
            "locator": "page:2",
            "text": "Breast cancer has multiple molecular subtypes.",
            "score": 0.82,
        },
        {
            "paper_id": paper_id,
            "title": "Breast Cancer Review",
            "chunk_id": chunk_id,
            "locator": "page:2",
            "text": "Breast cancer has multiple molecular subtypes.",
            "score": 0.82,
        },
    ]

    context = service._build_context(evidence)
    citations = service._build_citations(evidence)

    assert "[来源 1] Breast Cancer Review，位置：page:2" in context
    assert "Unknown paper" not in context
    assert len(citations) == 1
    assert citations[0].title == "Breast Cancer Review"


def test_rag_skips_unsupported_image_placeholders() -> None:
    service = RAGService.__new__(RAGService)

    assert service._is_unusable_evidence_text("[Unsupported Image]")
    assert service._is_unusable_evidence_text("无法读取图片内容")
    assert service._is_unusable_evidence_text("抱歉，我无法看到上传的图片内容。图片显示为“[无法识别]”。")
    assert not service._is_unusable_evidence_text("This paper describes a cohort study and survival analysis.")


@pytest.mark.asyncio
async def test_project_qa_summary_context_assessment_parses_llm_json() -> None:
    client = LLMClient()

    async def fake_generate(**_kwargs):
        return '{"include": false, "reason": "只是测试问题"}'

    client._generate = fake_generate

    result = await client.assess_project_qa_summary_context(question="测试一下", answer="可以")

    assert result == {"include": False, "reason": "只是测试问题"}


@pytest.mark.asyncio
async def test_project_qa_record_saves_summary_context_decision() -> None:
    service = RAGService.__new__(RAGService)

    class FakeLLM:
        async def assess_project_qa_summary_context(self, question, answer):
            assert "研究方法" in question
            assert "cohort" in answer
            return {"include": True, "reason": "包含研究方法"}

    class FakeSession:
        def __init__(self):
            self.added = []
            self.committed = False

        def add(self, item):
            self.added.append(item)

        def commit(self):
            self.committed = True

    service.llm = FakeLLM()
    db = FakeSession()
    citation = Citation(paper_id=uuid4(), title="Paper", chunk_id=None, locator="abstract")

    await service._record_project_qa(
        db=db,
        project_id=uuid4(),
        user_id=uuid4(),
        question="这篇文献有哪些研究方法？",
        answer="It used cohort analysis.",
        citations=[citation],
    )

    assert db.committed
    assert db.added[0].include_in_summary_context is True
    assert db.added[0].summary_context_reason == "包含研究方法"


def test_multimodal_extraction_rejects_image_apology_text() -> None:
    client = LLMClient()

    with pytest.raises(LLMClientError):
        client._validate_multimodal_text(
            "抱歉，我无法看到上传的图片内容。图片显示为“[无法识别]”，可能因为图片格式不被支持或未能成功上传。"
        )


def test_external_pdf_import_rejects_tiny_extracted_text() -> None:
    importer = PaperImporter()

    assert importer._is_unusable_extracted_text("here")
    assert not importer._is_unusable_extracted_text(
        "This full-text section describes hepatocellular carcinoma cohort selection, "
        "imaging feature extraction, statistical analysis, and model validation across patients."
    )


def test_rag_abstract_context_includes_metadata_and_abstract() -> None:
    service = RAGService.__new__(RAGService)
    paper = Paper(
        title="Liver Cancer Progress",
        authors=[{"name": "Ada Chen"}],
        abstract="This review summarizes hepatocellular carcinoma diagnosis and treatment progress.",
        doi="10.1000/liver.test",
        published_date=date(2026, 1, 2),
    )

    context = service._paper_abstract_context(paper)

    assert "Liver Cancer Progress" in context
    assert "Ada Chen" in context
    assert "hepatocellular carcinoma" in context


def test_user_material_importer_extracts_rezumat_from_single_line_pdf_text() -> None:
    importer = UserMaterialImporter()
    text = (
        "Rezumat Neoplasmul mamar reprezintă una dintre principalele malignităţi în rândul femeilor "
        "la nivel mondial. Heterogenitatea sa remarcabilă reprezintă o caracteristică definitorie, "
        "determinând atât tipare diverse de progresie a bolii, cât şi răspunsuri terapeutice variate. "
        "Acest review al literaturii explorează evoluţia clasificărilor cancerului mamar, concentrându-se "
        "pe factorii prognostici şi predictivi. Sunt examinate metodele tradiţionale de evaluare a bolii. "
        "Review Article Chirurgia (2025) Breast Cancer: A Heterogeneous Pathology."
    )

    abstract = importer._extract_declared_abstract(text)

    assert "Neoplasmul mamar" in abstract
    assert "Review Article" not in abstract


@pytest.mark.asyncio
async def test_user_material_importer_prefers_multimodal_metadata_abstract() -> None:
    importer = UserMaterialImporter()
    abstract = await importer._resolve_abstract_from_text(
        "Title only. No declared abstract section here.",
        model_abstract="多模态模型识别出的摘要。",
    )

    assert abstract == "多模态模型识别出的摘要。"


@pytest.mark.asyncio
async def test_user_material_importer_falls_back_to_extractive_abstract_when_llm_fails() -> None:
    importer = UserMaterialImporter()

    async def fail_generate(_text: str) -> str:
        raise RuntimeError("LLM unavailable")

    importer._generate_ingestion_abstract = fail_generate
    abstract = await importer._resolve_abstract_from_text("A" * 200)

    assert abstract == "A" * 200


def test_batch_upload_accepts_multiple_files(monkeypatch: pytest.MonkeyPatch) -> None:
    app = create_app()
    user_id = uuid4()

    class DummySession:
        def rollback(self):
            return None

    class FakeUserMaterialImporter:
        async def upload_material(self, **kwargs):
            return UploadMaterialResponse(
                paper_id=uuid4(),
                status="created",
                message=kwargs["file"].filename,
                stats={"chunks": 1},
            )

    from app.api.routes import papers

    app.dependency_overrides[get_current_user_id] = lambda: str(user_id)
    app.dependency_overrides[get_db] = lambda: DummySession()
    monkeypatch.setattr(papers, "UserMaterialImporter", FakeUserMaterialImporter)

    client = TestClient(app)
    response = client.post(
        "/api/papers/upload/batch",
        data={"project_id": "", "publication_status": "unpublished", "visibility": "private", "authors_json": "[]"},
        files=[
            ("files", ("first.pdf", b"%PDF-1.4 first", "application/pdf")),
            ("files", ("second.pdf", b"%PDF-1.4 second", "application/pdf")),
        ],
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert body["succeeded"] == 2
    assert [item["filename"] for item in body["results"]] == ["first.pdf", "second.pdf"]


def test_pubmed_query_uses_title_abstract_fields() -> None:
    importer = PaperImporter()

    query = importer._build_pubmed_query("liver cancer diagnosis deep learning", 2025, 2026)

    assert '"liver"[Title/Abstract]' in query
    assert '"cancer"[Title/Abstract]' in query
    assert '"2025/01/01"[Date - Publication]' in query
    assert '"2026/12/31"[Date - Publication]' in query
    assert " AND " in query


def test_external_queries_prefer_english_rewrites_for_chinese_query() -> None:
    service = SearchService()

    queries = service._external_queries(
        query="肝癌 深度学习 诊断",
        rewritten_queries=[
            "肝癌 深度学习 诊断",
            "liver cancer diagnosis deep learning",
            "hepatocellular carcinoma detection using neural networks",
        ],
    )

    assert queries == [
        "liver cancer diagnosis deep learning",
        "hepatocellular carcinoma detection using neural networks",
    ]


def test_paper_catalog_filters_use_expanded_query_terms() -> None:
    service = PaperCatalogService()

    terms = service._query_terms("乳腺癌", ["breast cancer", "breast neoplasm", "乳腺癌"])

    assert terms == ["乳腺癌", "breast cancer", "breast neoplasm"]


def test_parse_pubmed_article_metadata() -> None:
    importer = PaperImporter()
    article = ET.fromstring(
        """
        <PubmedArticle>
          <MedlineCitation>
            <PMID>123456</PMID>
            <Article>
              <ArticleTitle>Deep learning for liver cancer diagnosis.</ArticleTitle>
              <Journal>
                <Title>Journal of Medical AI</Title>
                <ISOAbbreviation>J Med AI</ISOAbbreviation>
                <JournalIssue>
                  <PubDate>
                    <Year>2025</Year>
                    <Month>Mar</Month>
                    <Day>9</Day>
                  </PubDate>
                </JournalIssue>
              </Journal>
              <AuthorList>
                <Author>
                  <ForeName>Ada</ForeName>
                  <LastName>Chen</LastName>
                </Author>
              </AuthorList>
              <Abstract>
                <AbstractText>We study hepatocellular carcinoma diagnosis using deep learning.</AbstractText>
              </Abstract>
            </Article>
          </MedlineCitation>
          <PubmedData>
            <ArticleIdList>
              <ArticleId IdType="doi">10.1000/pubmed.test</ArticleId>
              <ArticleId IdType="pmc">PMC1234567</ArticleId>
              <ArticleId IdType="pii">S1234-5678</ArticleId>
            </ArticleIdList>
          </PubmedData>
        </PubmedArticle>
        """
    )

    paper = importer._parse_pubmed_article(article)

    assert paper.source == "pubmed"
    assert paper.source_id == "123456"
    assert paper.title == "Deep learning for liver cancer diagnosis."
    assert paper.authors == [{"name": "Ada Chen"}]
    assert paper.doi == "10.1000/pubmed.test"
    assert paper.published_date == date(2025, 3, 9)
    assert paper.metadata["pmc_id"] == "PMC1234567"
    assert paper.metadata["pii"] == "S1234-5678"
    assert paper.metadata["journal"] == "Journal of Medical AI"


def test_pdf_resolver_extracts_citation_pdf_url() -> None:
    resolver = PDFResolver()
    html = '<html><head><meta name="citation_pdf_url" content="/article/full.pdf"></head></html>'

    assert resolver.extract_pdf_url_from_html(html, "https://publisher.example/articles/1") == (
        "https://publisher.example/article/full.pdf"
    )


def test_pdf_resolver_uses_browser_headers_for_doi_landing_pages() -> None:
    resolver = PDFResolver()

    headers = resolver._browser_headers()

    assert "Mozilla/5.0" in headers["User-Agent"]
    assert "Chrome/" in headers["User-Agent"]
    assert "text/html" in headers["Accept"]


def test_pdf_resolver_normalizes_pmc_oa_ftp_pdf_href() -> None:
    resolver = PDFResolver()

    assert resolver._normalize_pmc_oa_href(
        "ftp://ftp.ncbi.nlm.nih.gov/pub/pmc/oa_pdf/aa/bb/test.pdf"
    ) == "https://ftp.ncbi.nlm.nih.gov/pub/pmc/oa_pdf/aa/bb/test.pdf"


def test_pdf_resolver_extracts_bioc_full_text() -> None:
    resolver = PDFResolver()
    payload = {
        "documents": [
            {
                "passages": [
                    {"infons": {"section_type": "TITLE"}, "text": "Natural killer cell-mediated immunosurveillance"},
                    {"infons": {"section_type": "ABSTRACT"}, "text": "This study investigates liver cancer evolution."},
                    {"infons": {"section_type": "METHODS"}, "text": "Researchers performed cohort analysis and assays."},
                ]
            }
        ]
    }

    text = resolver._extract_bioc_text(payload)

    assert "[TITLE]" in text
    assert "liver cancer evolution" in text
    assert "cohort analysis" in text


def test_pdf_resolver_extracts_oai_jats_full_text() -> None:
    resolver = PDFResolver()
    root = ET.fromstring(
        """
        <OAI-PMH xmlns:mml="http://www.w3.org/1998/Math/MathML">
          <GetRecord>
            <record>
              <metadata>
                <article>
                  <front>
                    <article-meta>
                      <title-group><article-title>PMC full text title</article-title></title-group>
                      <abstract><p>This is an abstract about cancer progression.</p></abstract>
                    </article-meta>
                  </front>
                  <body>
                    <sec>
                      <title>Methods</title>
                      <p>The study used sequencing and survival analysis.</p>
                    </sec>
                  </body>
                </article>
              </metadata>
            </record>
          </GetRecord>
        </OAI-PMH>
        """
    )

    text = resolver._extract_jats_text(root)

    assert "PMC full text title" in text
    assert "cancer progression" in text
    assert "survival analysis" in text


@pytest.mark.asyncio
async def test_resolve_pubmed_pdf_prefers_pmc_strategy(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_resolve_pmc_pdf(self, pmc_id):
        _ = self
        return PDFResolveResult(
            pdf_url=f"https://pmc.example/articles/{pmc_id}/paper.pdf",
            landing_url=f"https://pmc.example/articles/{pmc_id}/",
            source="pmc_oa",
        )

    monkeypatch.setattr(PDFResolver, "resolve_pmc_pdf", fake_resolve_pmc_pdf)

    result = await PDFResolver().resolve_pubmed_pdf(doi="10.1000/fallback", pmc_id="13408697", pmid="40808340")

    assert result.pdf_url == "https://pmc.example/articles/PMC13408697/paper.pdf"
    assert result.source == "pmc_oa"


@pytest.mark.asyncio
async def test_pubmed_pdf_resolve_updates_imported_paper() -> None:
    importer = PaperImporter()

    class FakePDFResolver:
        async def resolve_pubmed_pdf(self, **_kwargs):
            return PDFResolveResult(
                pdf_url="https://publisher.example/full.pdf",
                landing_url="https://publisher.example/article",
                source="doi_landing",
            )

    importer.pdf_resolver = FakePDFResolver()
    stats = ImportStats()
    paper = ImportedPaper(
        title="PubMed Paper",
        authors=[],
        abstract="Already imported.",
        doi="10.1000/pubmed.test",
        source="pubmed",
        source_id="123456",
        published_date=None,
        pdf_url=None,
        citation_count=0,
        metadata={"pmc_id": None},
    )

    await importer._resolve_pdf_for_import(paper, stats)

    assert paper.pdf_url == "https://publisher.example/full.pdf"
    assert paper.metadata["pdf_resolver"] == "doi_landing"
    assert stats.values["pdf_resolved"] == 1


class ExistingPaperQuery:
    def filter(self, *_args):
        return self

    def first(self) -> Paper:
        return Paper(id=uuid4(), title="Existing", source="arxiv", source_id="2608.00001", metadata_json={})

    def delete(self, synchronize_session=False):
        _ = synchronize_session
        return 0


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

    async def fake_process_pdf(db, paper_id, imported, stats):
        _ = db
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


def test_deepseek_image_calls_use_deepseek_vision_model(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.llm import llm_client

    monkeypatch.setattr(llm_client.settings, "llm_provider", "deepseek")
    monkeypatch.setattr(llm_client.settings, "openai_base_url", "https://api.deepseek.com")
    monkeypatch.setattr(llm_client.settings, "openai_model", "deepseek-v4-flash")
    monkeypatch.setattr(llm_client.settings, "deepseek_vision_model", "deepseek-v4-flash-vision-exp")
    monkeypatch.setattr(llm_client.settings, "pdf_multimodal_model", None)

    client = LLMClient()

    assert client._vision_model() == "deepseek-v4-flash-vision-exp"
    client._validate_vision_model()


def test_responses_text_extraction_ignores_reasoning_items() -> None:
    client = LLMClient()
    data = {
        "output": [
            {
                "type": "reasoning",
                "content": [{"type": "reasoning_text", "text": "The user wants me to extract text."}],
            },
            {
                "type": "message",
                "content": [{"type": "output_text", "text": "Article title\n\nAbstract\nReadable paper text."}],
            },
        ]
    }

    assert client._extract_responses_text(data) == "Article title\n\nAbstract\nReadable paper text."


def test_multimodal_validation_allows_local_unreadable_marker() -> None:
    client = LLMClient()

    text = "Article title\n\nAbstract\nThis page is readable, but one table cell is [无法识别]."

    assert client._validate_multimodal_text(text) == text


def test_pdf_multimodal_model_overrides_deepseek_vision_model(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.llm import llm_client

    monkeypatch.setattr(llm_client.settings, "llm_provider", "deepseek")
    monkeypatch.setattr(llm_client.settings, "openai_base_url", "https://api.deepseek.com")
    monkeypatch.setattr(llm_client.settings, "pdf_multimodal_model", "custom-vision-model")

    client = LLMClient()

    assert client._vision_model() == "custom-vision-model"
    with pytest.raises(LLMClientError):
        client._validate_vision_model()


def test_pdf_importer_uses_browser_headers_for_publisher_downloads() -> None:
    importer = PaperImporter()

    headers = importer._pdf_download_headers("https://www.nature.com/articles/s41467-026-74360-x.pdf")

    assert "Mozilla/5.0" in headers["User-Agent"]
    assert "application/pdf" in headers["Accept"]
    assert headers["Referer"] == "https://www.nature.com/articles/s41467-026-74360-x"


def test_pdf_importer_detects_html_challenge_response() -> None:
    importer = PaperImporter()

    assert importer._looks_like_html_response(b"<!doctype html><html>JavaScript is disabled</html>", "text/html")
    assert not importer._looks_like_html_response(b"%PDF-1.7\nbinary", "application/pdf")


def test_pdf_importer_extracts_pmc_id_from_pdf_url() -> None:
    importer = PaperImporter()

    assert importer._pmc_id_from_url("https://pmc.ncbi.nlm.nih.gov/articles/PMC13408697/pdf/") == "PMC13408697"
    assert importer._pmc_id_from_url("https://example.test/no-pmc") is None


def test_pdf_importer_does_not_retry_less_specific_pmc_pdf_directory() -> None:
    importer = PaperImporter()

    assert not importer._should_retry_pdf_url(
        current_url="https://pmc.ncbi.nlm.nih.gov/articles/PMC13408697/pdf/41467_2026_Article_74360.pdf",
        resolved_url="https://pmc.ncbi.nlm.nih.gov/articles/PMC13408697/pdf/",
    )
    assert importer._should_retry_pdf_url(
        current_url="https://pmc.ncbi.nlm.nih.gov/articles/PMC13408697/pdf/",
        resolved_url="https://pmc.ncbi.nlm.nih.gov/articles/PMC13408697/pdf/41467_2026_Article_74360.pdf",
    )


def test_pdf_importer_classifies_recaptcha_as_manual_pdf_required() -> None:
    importer = PaperImporter()

    assert importer._is_manual_pdf_required_error(
        ValueError("Downloaded file is blocked by reCAPTCHA instead of a PDF.")
    )
    assert not importer._is_manual_pdf_required_error(RuntimeError("Embedding service timeout"))


def test_pdf_importer_records_final_redirected_pdf_url() -> None:
    importer = PaperImporter()
    paper_id = uuid4()
    paper = Paper(
        id=paper_id,
        title="PMC paper",
        source="pubmed",
        source_id="40808340",
        pdf_url="https://www.ncbi.nlm.nih.gov/pmc/articles/PMC13408697/pdf/",
        metadata_json={},
    )

    class FakeSession:
        def get(self, model, key):
            _ = model
            return paper if key == paper_id else None

    imported = ImportedPaper(
        title="PMC paper",
        authors=[],
        abstract="abstract",
        doi=None,
        source="pubmed",
        source_id="40808340",
        published_date=None,
        pdf_url="https://www.ncbi.nlm.nih.gov/pmc/articles/PMC13408697/pdf/",
        citation_count=0,
        metadata={},
    )
    final_url = "https://pmc.ncbi.nlm.nih.gov/articles/PMC13408697/pdf/41467_2026_Article_74360.pdf"

    importer._record_final_pdf_url(db=FakeSession(), paper_id=paper_id, imported=imported, final_url=final_url)

    assert imported.pdf_url == final_url
    assert paper.pdf_url == final_url
    assert paper.metadata_json["requested_pdf_url"] == "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC13408697/pdf/"
    assert paper.metadata_json["final_pdf_url"] == final_url


@pytest.mark.asyncio
async def test_pdf_importer_prefers_structured_full_text_before_pdf_download() -> None:
    importer = PaperImporter()
    paper_id = uuid4()
    stats = ImportStats()

    class FakeStructuredResolver:
        async def resolve_pmc_full_text(self, pmc_id):
            assert pmc_id == "PMC13408697"
            return StructuredFullTextResult(
                text="This PMC structured full text describes liver cancer methods and findings. " * 80,
                source="pmc_bioc",
                url="https://example.test/pmc/PMC13408697/bioc",
            )

    class FakeEmbeddingService:
        async def embed_text(self, _text):
            return [0.1] * 1024

    class FakeVectorStore:
        async def upsert_chunk(self, **_kwargs):
            return None

    class FakeSession:
        def __init__(self):
            self.added = []

        def add(self, item):
            self.added.append(item)

        def get(self, *_args):
            return None

    async def fail_download(_url):
        raise AssertionError("PDF download should not be called when PMC structured full text is available")

    importer.pdf_resolver = FakeStructuredResolver()
    importer.embeddings = FakeEmbeddingService()
    importer._vector_store = FakeVectorStore()
    importer._download_pdf = fail_download
    db = FakeSession()
    imported = ImportedPaper(
        title="PMC paper",
        authors=[],
        abstract="abstract",
        doi=None,
        source="pubmed",
        source_id="40808340",
        published_date=None,
        pdf_url="https://pmc.ncbi.nlm.nih.gov/articles/PMC13408697/pdf/",
        citation_count=0,
        metadata={"pmc_id": "PMC13408697"},
    )

    result = await importer._try_process_pdf(db=db, paper_id=paper_id, imported=imported, stats=stats)

    assert result.success
    assert result.extraction_method == "pmc_bioc"
    assert result.structured_fulltext_url == "https://example.test/pmc/PMC13408697/bioc"
    assert stats.values["structured_fulltext_resolved"] == 1
    assert stats.values["pdf_processed"] == 1
    assert db.added
    assert db.added[0].metadata_json["extraction_method"] == "pmc_bioc"
    assert db.added[0].metadata_json["structured_fulltext_url"] == "https://example.test/pmc/PMC13408697/bioc"

