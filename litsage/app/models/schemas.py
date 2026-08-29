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
    cache_hit: bool = False


class QueryRewriteResponse(BaseModel):
    original: str
    variants: list[str]


class LiteratureSource(str, Enum):
    arxiv = "arxiv"
    semantic_scholar = "semantic_scholar"
    pubmed = "pubmed"


class ImportPapersRequest(BaseModel):
    query: str = Field(min_length=2)
    sources: list[LiteratureSource] = Field(default_factory=lambda: [LiteratureSource.arxiv])
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


class ImportPreviewResponse(BaseModel):
    query: str
    total: int
    candidates: list[ImportCandidatePaper]
    stats: dict[str, int | list[str]]


class ImportSelectedPapersRequest(BaseModel):
    papers: list[ImportCandidatePaper] = Field(min_length=1, max_length=100)
    include_pdf: bool = False


class ImportPapersResponse(BaseModel):
    task_id: UUID
    status: str
    message: str
    stats: dict[str, int | list[str]] | None = None


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


class SummaryTaskResponse(BaseModel):
    task_id: UUID
    status: str


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
