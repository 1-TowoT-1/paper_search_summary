from datetime import date, datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class UserLogin(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=128)


class UserRead(BaseModel):
    id: UUID
    username: str
    email: EmailStr
    created_at: datetime

    model_config = {"from_attributes": True}


class AuthToken(BaseModel):
    access_token: str
    token_type: str


class PasswordChangeRequest(BaseModel):
    old_password: str = Field(min_length=8, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class EmailVerificationRequest(BaseModel):
    email: EmailStr


class EmailVerificationResponse(BaseModel):
    email: EmailStr
    message: str
    dev_code: str | None = None


class EmailChangeRequest(BaseModel):
    new_email: EmailStr
    verification_code: str = Field(min_length=4, max_length=12)


class MessageResponse(BaseModel):
    message: str


class PaperRead(BaseModel):
    id: UUID
    title: str
    authors: list[dict] = []
    abstract: str | None = None
    doi: str | None = None
    source: str
    source_id: str
    published_date: date | None = None
    pdf_url: str | None = None
    citation_count: int = 0
    metadata_json: dict = {}
    source_type: str = "external"
    publication_status: str = "published"
    visibility: str = "public"
    owner_user_id: UUID | None = None
    original_filename: str | None = None
    file_path: str | None = None
    file_mime_type: str | None = None
    file_sha256: str | None = None
    ingestion_status: str = "completed"
    analysis_status: str = "pending"
    metadata_confidence: str = "high"
    text_extraction_method: str | None = None

    model_config = {"from_attributes": True}


class PaperDeleteResponse(BaseModel):
    paper_id: UUID
    deleted: bool
    project_links_deleted: int = 0
    vector_deleted: bool
    vector_delete_stats: dict[str, int | str] | None = None
    vector_delete_error: str | None = None


class PaperListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    results: list[PaperRead]


class SearchResult(BaseModel):
    paper: PaperRead
    score: float
    highlights: list[str] = []


class SearchResponse(BaseModel):
    query: str
    rewritten_queries: list[str]
    total: int
    results: list[SearchResult]
    external_total: int = 0
    external_results: list["ExternalSearchResult"] = []
    external_stats: dict[str, int | list[str]] = {}
    used_external_fallback: bool = False
    cache_hit: bool = False


class QueryRewriteResponse(BaseModel):
    original: str
    variants: list[str]


class LiteratureSource(str, Enum):
    arxiv = "arxiv"
    semantic_scholar = "semantic_scholar"
    pubmed = "pubmed"


class PublicationStatus(str, Enum):
    published = "published"
    preprint = "preprint"
    unpublished = "unpublished"
    internal = "internal"
    unknown = "unknown"


class Visibility(str, Enum):
    private = "private"
    project = "project"
    public = "public"


class ImportPapersRequest(BaseModel):
    query: str = Field(min_length=2)
    sources: list[LiteratureSource] = Field(default_factory=lambda: [LiteratureSource.pubmed])
    limit: int = Field(default=20, ge=1, le=100)
    include_pdf: bool = False


class ImportCandidatePaper(BaseModel):
    title: str
    authors: list[dict] = []
    abstract: str
    doi: str | None = None
    source: str
    source_id: str
    published_date: date | None = None
    pdf_url: str | None = None
    citation_count: int = 0
    metadata: dict = {}


class ExternalSearchResult(BaseModel):
    paper: ImportCandidatePaper
    source: str
    score: float | None = None
    reason: str = "external_fallback"


class ImportPreviewResponse(BaseModel):
    query: str
    total: int
    candidates: list[ImportCandidatePaper]
    stats: dict[str, int | list[str]]


class ImportSelectedPapersRequest(BaseModel):
    papers: list[ImportCandidatePaper] = Field(min_length=1, max_length=100)
    include_pdf: bool = False
    project_id: UUID | None = None


class ImportPapersResponse(BaseModel):
    task_id: UUID
    status: str
    message: str
    stats: dict[str, int | list[str]] | None = None


class UploadMaterialResponse(BaseModel):
    paper_id: UUID
    status: str
    message: str
    stats: dict[str, int | str | list[str]] = Field(default_factory=dict)


class UploadMaterialItemResult(BaseModel):
    filename: str
    ok: bool
    paper_id: UUID | None = None
    status: str
    message: str
    stats: dict[str, int | str | list[str]] = Field(default_factory=dict)
    error: str | None = None


class BatchUploadMaterialResponse(BaseModel):
    status: str
    message: str
    total: int
    succeeded: int
    failed: int
    results: list[UploadMaterialItemResult]


class ManualMaterialRequest(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    abstract: str = Field(min_length=20)
    content: str | None = None
    authors: list[dict] = []
    project_id: UUID | None = None
    publication_status: PublicationStatus = PublicationStatus.unpublished
    visibility: Visibility = Visibility.private
    metadata: dict = {}


class SummaryResponse(BaseModel):
    paper_id: UUID
    markdown: str
    cached: bool = False


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str | None = None


class ProjectRead(BaseModel):
    id: UUID
    user_id: UUID
    name: str
    description: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class AddProjectPaperRequest(BaseModel):
    paper_id: UUID


class AddProjectPapersRequest(BaseModel):
    paper_ids: list[UUID] = Field(min_length=1, max_length=200)


class AddProjectPapersResponse(BaseModel):
    project_id: UUID
    requested: int
    added: int
    already_linked: int
    skipped_inaccessible: int


class RemoveProjectPapersRequest(BaseModel):
    paper_ids: list[UUID] = Field(min_length=1, max_length=200)


class RemoveProjectPapersResponse(BaseModel):
    project_id: UUID
    requested: int
    removed: int
    skipped: int


class ProjectPapersResponse(BaseModel):
    project_id: UUID
    total: int
    results: list[PaperRead]


class ProjectQARead(BaseModel):
    id: UUID
    project_id: UUID
    user_id: UUID
    question: str
    answer: str
    citations: list[dict] = []
    include_in_summary_context: bool = True
    summary_context_reason: str | None = None
    created_at: datetime


class ProjectQAListResponse(BaseModel):
    project_id: UUID
    total: int
    results: list[ProjectQARead]


class DeleteProjectQAsRequest(BaseModel):
    qa_ids: list[UUID] = Field(min_length=1, max_length=200)


class DeleteProjectQAsResponse(BaseModel):
    project_id: UUID
    requested: int
    deleted: int
    skipped: int


class SummaryTaskResponse(BaseModel):
    task_id: UUID
    status: str


class ProjectSummaryRequest(BaseModel):
    question: str | None = Field(default=None, max_length=2000)


class ProjectSummaryResponse(BaseModel):
    project_id: UUID
    project_name: str
    markdown: str
    paper_count: int
    qa_count: int
    summary_question: str | None = None
    cached: bool = False


class QAScope(str, Enum):
    paper = "paper"
    project = "project"
    search_results = "search_results"


class QARequest(BaseModel):
    question: str = Field(min_length=2)
    scope: QAScope
    paper_id: UUID | None = None
    project_id: UUID | None = None
    paper_ids: list[UUID] = []
    session_id: str | None = None


class Citation(BaseModel):
    paper_id: UUID
    title: str
    chunk_id: str | None = None
    locator: str | None = None


class QAResponse(BaseModel):
    answer: str
    citations: list[Citation]
    session_id: str


class TaskStatusResponse(BaseModel):
    task_id: UUID
    status: str
    result_text: str | None = None
    error: str | None = None
