"""Persist bounded administrator-only model call input and output records."""

import sqlalchemy as sa
from alembic import op

revision = "f47d21532c33"
down_revision = "f36c10421b22"
branch_labels = None
depends_on = None


def upgrade():
    """Add new call records without manufacturing historical model payloads."""
    op.create_table(
        "model_calls",
        sa.Column("id", sa.String(36), primary_key=True, comment="UUID 资源标识"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, comment="UTC 创建时间"),
        sa.Column("provider_id", sa.String(160), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("model", sa.String(200), nullable=False),
        sa.Column("operation", sa.String(30), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("development_sample", sa.Boolean(), nullable=False),
        sa.Column("project_id", sa.String(36)),
        sa.Column("owner_user_id", sa.String(36)),
        sa.Column("run_id", sa.String(36)),
        sa.Column("job_id", sa.String(36)),
        sa.Column("privacy_epoch", sa.Integer()),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("latency_ms", sa.Integer()),
        sa.Column("http_status", sa.Integer()),
        sa.Column("error_code", sa.String(80)),
        sa.Column("result_unknown", sa.Boolean(), nullable=False),
        sa.Column("request_json", sa.JSON(), nullable=False),
        sa.Column("response_json", sa.JSON()),
    )
    op.create_index("ix_model_calls_created_id", "model_calls", ["created_at", "id"])
    op.create_index("ix_model_calls_project_id", "model_calls", ["project_id"])
    op.create_index("ix_model_calls_owner_user_id", "model_calls", ["owner_user_id"])


def downgrade():
    """Protect existing call records from accidental destructive rollback."""
    if op.get_bind().execute(sa.text("SELECT COUNT(*) FROM model_calls")).scalar():
        raise RuntimeError("Model calls require explicit archival before downgrade")
    op.drop_table("model_calls")
