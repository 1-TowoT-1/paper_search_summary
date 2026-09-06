"""user material ingestion

Revision ID: 0002_user_material_ingestion
Revises: 0001_initial_schema
Create Date: 2026-09-02
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002_user_material_ingestion"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    def has_table(table_name: str) -> bool:
        return table_name in inspector.get_table_names()

    def has_column(table_name: str, column_name: str) -> bool:
        return column_name in {column["name"] for column in inspector.get_columns(table_name)}

    def has_index(table_name: str, index_name: str) -> bool:
        return index_name in {index["name"] for index in inspector.get_indexes(table_name)}

    def has_foreign_key(table_name: str, constraint_name: str) -> bool:
        return constraint_name in {fk["name"] for fk in inspector.get_foreign_keys(table_name)}

    paper_columns = [
        sa.Column("source_type", sa.String(), nullable=False, server_default="external"),
        sa.Column("publication_status", sa.String(), nullable=False, server_default="published"),
        sa.Column("visibility", sa.String(), nullable=False, server_default="public"),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("original_filename", sa.Text(), nullable=True),
        sa.Column("file_path", sa.Text(), nullable=True),
        sa.Column("file_mime_type", sa.String(), nullable=True),
        sa.Column("file_sha256", sa.String(), nullable=True),
        sa.Column("ingestion_status", sa.String(), nullable=False, server_default="completed"),
        sa.Column("analysis_status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("metadata_confidence", sa.String(), nullable=False, server_default="high"),
        sa.Column("text_extraction_method", sa.String(), nullable=True),
    ]
    for column in paper_columns:
        if not has_column("papers", column.name):
            op.add_column("papers", column)

    if not has_foreign_key("papers", "fk_papers_owner_user_id_users"):
        op.create_foreign_key("fk_papers_owner_user_id_users", "papers", "users", ["owner_user_id"], ["id"])

    paper_indexes = [
        ("ix_papers_source_type", ["source_type"]),
        ("ix_papers_publication_status", ["publication_status"]),
        ("ix_papers_visibility", ["visibility"]),
        ("ix_papers_owner_user_id", ["owner_user_id"]),
        ("ix_papers_file_sha256", ["file_sha256"]),
        ("ix_papers_ingestion_status", ["ingestion_status"]),
        ("ix_papers_analysis_status", ["analysis_status"]),
    ]
    for index_name, columns in paper_indexes:
        if not has_index("papers", index_name):
            op.create_index(index_name, "papers", columns, unique=False)

    if not has_table("paper_files"):
        op.create_table(
            "paper_files",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("paper_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("original_filename", sa.Text(), nullable=False),
            sa.Column("stored_path", sa.Text(), nullable=False),
            sa.Column("mime_type", sa.String(), nullable=False),
            sa.Column("file_size_bytes", sa.BigInteger(), nullable=False),
            sa.Column("sha256", sa.String(), nullable=False),
            sa.Column("upload_status", sa.String(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["paper_id"], ["papers.id"]),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("user_id", "sha256", name="uq_paper_files_user_sha256"),
        )
    paper_file_indexes = [
        ("ix_paper_files_paper_id", ["paper_id"]),
        ("ix_paper_files_user_id", ["user_id"]),
        ("ix_paper_files_sha256", ["sha256"]),
        ("ix_paper_files_upload_status", ["upload_status"]),
    ]
    for index_name, columns in paper_file_indexes:
        if not has_index("paper_files", index_name):
            op.create_index(index_name, "paper_files", columns, unique=False)

    if not has_table("paper_chunks"):
        op.create_table(
            "paper_chunks",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("paper_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("chunk_index", sa.Integer(), nullable=False),
            sa.Column("text", sa.Text(), nullable=False),
            sa.Column("page_start", sa.Integer(), nullable=True),
            sa.Column("page_end", sa.Integer(), nullable=True),
            sa.Column("chunk_type", sa.String(), nullable=False),
            sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["paper_id"], ["papers.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("paper_id", "chunk_index", name="uq_paper_chunks_paper_index"),
        )
    paper_chunk_indexes = [
        ("ix_paper_chunks_paper_id", ["paper_id"]),
        ("ix_paper_chunks_chunk_type", ["chunk_type"]),
    ]
    for index_name, columns in paper_chunk_indexes:
        if not has_index("paper_chunks", index_name):
            op.create_index(index_name, "paper_chunks", columns, unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_paper_chunks_chunk_type"), table_name="paper_chunks")
    op.drop_index(op.f("ix_paper_chunks_paper_id"), table_name="paper_chunks")
    op.drop_table("paper_chunks")
    op.drop_index(op.f("ix_paper_files_upload_status"), table_name="paper_files")
    op.drop_index(op.f("ix_paper_files_sha256"), table_name="paper_files")
    op.drop_index(op.f("ix_paper_files_user_id"), table_name="paper_files")
    op.drop_index(op.f("ix_paper_files_paper_id"), table_name="paper_files")
    op.drop_table("paper_files")
    op.drop_index(op.f("ix_papers_analysis_status"), table_name="papers")
    op.drop_index(op.f("ix_papers_ingestion_status"), table_name="papers")
    op.drop_index(op.f("ix_papers_file_sha256"), table_name="papers")
    op.drop_index(op.f("ix_papers_owner_user_id"), table_name="papers")
    op.drop_index(op.f("ix_papers_visibility"), table_name="papers")
    op.drop_index(op.f("ix_papers_publication_status"), table_name="papers")
    op.drop_index(op.f("ix_papers_source_type"), table_name="papers")
    op.drop_constraint("fk_papers_owner_user_id_users", "papers", type_="foreignkey")
    op.drop_column("papers", "text_extraction_method")
    op.drop_column("papers", "metadata_confidence")
    op.drop_column("papers", "analysis_status")
    op.drop_column("papers", "ingestion_status")
    op.drop_column("papers", "file_sha256")
    op.drop_column("papers", "file_mime_type")
    op.drop_column("papers", "file_path")
    op.drop_column("papers", "original_filename")
    op.drop_column("papers", "owner_user_id")
    op.drop_column("papers", "visibility")
    op.drop_column("papers", "publication_status")
    op.drop_column("papers", "source_type")
