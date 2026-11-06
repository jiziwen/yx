"""M2.5 scoped feedback and inactive model candidates."""

import sqlalchemy as sa
from alembic import op

revision = "f25b09310a11"
down_revision = "f14b2a5e0610"
branch_labels = None
depends_on = None


def records():
    """Common immutable record identifiers."""
    return [
        sa.Column("id", sa.String(36), primary_key=True, comment="UUID 资源标识"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, comment="UTC 创建时间"),
    ]


def upgrade():
    """Add reviews without rewriting existing model history or project data."""
    op.create_table(
        "model_candidates",
        *records(),
        sa.Column("actor_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("settings_json", sa.JSON(), nullable=False),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("approved_by", sa.String(36), sa.ForeignKey("users.id")),
        sa.Column("release_id", sa.String(36), sa.ForeignKey("model_releases.id")),
    )
    op.create_table(
        "quality_feedback",
        *records(),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("asset_id", sa.String(36), sa.ForeignKey("assets.id"), nullable=False, unique=True),
        sa.Column("reference_asset_id", sa.String(36), sa.ForeignKey("assets.id")),
        sa.Column("privacy_epoch", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(1000), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("grant_active", sa.Boolean(), nullable=False),
        sa.Column("assigned_staff_id", sa.String(36), sa.ForeignKey("users.id")),
        sa.Column("compensation_plan_id", sa.String(36), sa.ForeignKey("plan_versions.id"), unique=True),
        sa.Column("review_note", sa.String(1000), nullable=False),
    )
    op.create_index("ix_quality_feedback_project_id", "quality_feedback", ["project_id"])


def downgrade():
    """Refuse to discard review evidence and user compensation records."""
    bind = op.get_bind()
    for table in ("model_candidates", "quality_feedback"):
        if bind.execute(sa.text(f"SELECT COUNT(*) FROM {table}")).scalar():
            raise RuntimeError("M2.5 reviews require an explicit archival migration")
    op.drop_table("quality_feedback")
    op.drop_table("model_candidates")
