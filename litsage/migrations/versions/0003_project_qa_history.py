"""project qa history

Revision ID: 0003_project_qa_history
Revises: 0002_user_material_ingestion
Create Date: 2026-09-02
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0003_project_qa_history"
down_revision = "0002_user_material_ingestion"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "project_qas" not in inspector.get_table_names():
        op.create_table(
            "project_qas",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("question", sa.Text(), nullable=False),
            sa.Column("answer", sa.Text(), nullable=False),
            sa.Column("citations", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    indexes = {index["name"] for index in inspector.get_indexes("project_qas")}
    if "ix_project_qas_project_id" not in indexes:
        op.create_index("ix_project_qas_project_id", "project_qas", ["project_id"], unique=False)
    if "ix_project_qas_user_id" not in indexes:
        op.create_index("ix_project_qas_user_id", "project_qas", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_project_qas_user_id", table_name="project_qas")
    op.drop_index("ix_project_qas_project_id", table_name="project_qas")
    op.drop_table("project_qas")
