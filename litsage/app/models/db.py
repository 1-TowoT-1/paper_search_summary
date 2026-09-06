from datetime import UTC, date, datetime
from uuid import UUID as PyUUID
from uuid import uuid4

from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, create_engine
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class Paper(Base, TimestampMixin):
    __tablename__ = "papers"
    __table_args__ = (UniqueConstraint("source", "source_id", name="uq_papers_source_source_id"),)

    id: Mapped[PyUUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    authors: Mapped[list[dict]] = mapped_column(JSONB, default=list)
    abstract: Mapped[str | None] = mapped_column(Text)
    doi: Mapped[str | None] = mapped_column(String, unique=True)
    source: Mapped[str] = mapped_column(String, index=True)
    source_id: Mapped[str] = mapped_column(String, index=True)
    published_date: Mapped[date | None] = mapped_column(Date)
    pdf_url: Mapped[str | None] = mapped_column(Text)
    citation_count: Mapped[int] = mapped_column(Integer, default=0)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
    source_type: Mapped[str] = mapped_column(String, default="external", index=True)
    publication_status: Mapped[str] = mapped_column(String, default="published", index=True)
    visibility: Mapped[str] = mapped_column(String, default="public", index=True)
    owner_user_id: Mapped[PyUUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"), index=True)
    original_filename: Mapped[str | None] = mapped_column(Text)
    file_path: Mapped[str | None] = mapped_column(Text)
    file_mime_type: Mapped[str | None] = mapped_column(String)
    file_sha256: Mapped[str | None] = mapped_column(String, index=True)
    ingestion_status: Mapped[str] = mapped_column(String, default="completed", index=True)
    analysis_status: Mapped[str] = mapped_column(String, default="pending", index=True)
    metadata_confidence: Mapped[str] = mapped_column(String, default="high")
    text_extraction_method: Mapped[str | None] = mapped_column(String)


class User(Base):
    __tablename__ = "users"

    id: Mapped[PyUUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    username: Mapped[str] = mapped_column(String, unique=True, index=True)
    email: Mapped[str] = mapped_column(String, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))

    projects: Mapped[list["Project"]] = relationship(back_populates="user")


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[PyUUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[PyUUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))

    user: Mapped[User] = relationship(back_populates="projects")


class ProjectPaper(Base):
    __tablename__ = "project_papers"

    project_id: Mapped[PyUUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("projects.id"), primary_key=True)
    paper_id: Mapped[PyUUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("papers.id"), primary_key=True)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class ProjectQA(Base):
    __tablename__ = "project_qas"

    id: Mapped[PyUUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[PyUUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("projects.id"), index=True)
    user_id: Mapped[PyUUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"), index=True)
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    citations_json: Mapped[list[dict]] = mapped_column("citations", JSONB, default=list)
    include_in_summary_context: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    summary_context_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class PaperFile(Base):
    __tablename__ = "paper_files"
    __table_args__ = (UniqueConstraint("user_id", "sha256", name="uq_paper_files_user_sha256"),)

    id: Mapped[PyUUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    paper_id: Mapped[PyUUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("papers.id"), index=True)
    user_id: Mapped[PyUUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"), index=True)
    original_filename: Mapped[str] = mapped_column(Text)
    stored_path: Mapped[str] = mapped_column(Text)
    mime_type: Mapped[str] = mapped_column(String)
    file_size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String, index=True)
    upload_status: Mapped[str] = mapped_column(String, default="completed", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class PaperChunk(Base):
    __tablename__ = "paper_chunks"
    __table_args__ = (UniqueConstraint("paper_id", "chunk_index", name="uq_paper_chunks_paper_index"),)

    id: Mapped[PyUUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    paper_id: Mapped[PyUUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("papers.id"), index=True)
    chunk_index: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    page_start: Mapped[int | None] = mapped_column(Integer)
    page_end: Mapped[int | None] = mapped_column(Integer)
    chunk_type: Mapped[str] = mapped_column(String, default="body", index=True)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class SummaryTask(Base):
    __tablename__ = "summary_tasks"

    id: Mapped[PyUUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[PyUUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"), index=True)
    project_id: Mapped[PyUUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("projects.id"))
    paper_ids: Mapped[list[PyUUID] | None] = mapped_column(ARRAY(PGUUID(as_uuid=True)))
    status: Mapped[str] = mapped_column(String, default="pending", index=True)
    result_text: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
