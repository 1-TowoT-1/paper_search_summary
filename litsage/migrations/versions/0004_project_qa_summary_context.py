"""project qa summary context filter

Revision ID: 0004_project_qa_summary_context
Revises: 0003_project_qa_history
Create Date: 2026-09-06
"""

from alembic import op
import sqlalchemy as sa

revision = "0004_project_qa_summary_context"
down_revision = "0003_project_qa_history"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "project_qas" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("project_qas")}
    if "include_in_summary_context" not in columns:
        op.add_column(
            "project_qas",
            sa.Column("include_in_summary_context", sa.Boolean(), nullable=False, server_default=sa.true()),
        )
    if "summary_context_reason" not in columns:
        op.add_column("project_qas", sa.Column("summary_context_reason", sa.Text(), nullable=True))

    indexes = {index["name"] for index in inspector.get_indexes("project_qas")}
    if "ix_project_qas_include_in_summary_context" not in indexes:
        op.create_index(
            "ix_project_qas_include_in_summary_context",
            "project_qas",
            ["include_in_summary_context"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "project_qas" not in inspector.get_table_names():
        return

    indexes = {index["name"] for index in inspector.get_indexes("project_qas")}
    if "ix_project_qas_include_in_summary_context" in indexes:
        op.drop_index("ix_project_qas_include_in_summary_context", table_name="project_qas")

    columns = {column["name"] for column in inspector.get_columns("project_qas")}
    if "summary_context_reason" in columns:
        op.drop_column("project_qas", "summary_context_reason")
    if "include_in_summary_context" in columns:
        op.drop_column("project_qas", "include_in_summary_context")
