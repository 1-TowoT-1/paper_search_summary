from datetime import UTC, date, datetime
from uuid import UUID as PyUUID
from uuid import uuid4

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, create_engine
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
