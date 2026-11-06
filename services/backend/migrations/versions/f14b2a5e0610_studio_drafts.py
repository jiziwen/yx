"""M2.5 private shared studio drafts; preserves existing projects and plans."""

import sqlalchemy as sa
from alembic import op

revision = "f14b2a5e0610"
down_revision = "d72ad49fe108"
branch_labels = None
depends_on = None


def upgrade():
    """Add isolated drafts without changing historical execution state."""
    op.create_table(
        "studio_drafts",
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), primary_key=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("privacy_epoch", sa.Integer(), nullable=False),
        sa.Column("draft_json", sa.JSON(), nullable=False),
    )


def downgrade():
    """Refuse to discard saved user drafts during rollback."""
    if op.get_bind().execute(sa.text("SELECT COUNT(*) FROM studio_drafts")).scalar():
        raise RuntimeError("studio drafts require backup and explicit migration before downgrade")
    op.drop_table("studio_drafts")
