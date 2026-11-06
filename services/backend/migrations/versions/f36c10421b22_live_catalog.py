"""Live theme material publications without changing existing YAML or project data."""

import sqlalchemy as sa
from alembic import op

revision = "f36c10421b22"
down_revision = "f25b09310a11"
branch_labels = None
depends_on = None


def records():
    """Immutable record identity shared by upload and publication rows."""
    return [
        sa.Column("id", sa.String(36), primary_key=True, comment="UUID 资源标识"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, comment="UTC 创建时间"),
    ]


def upgrade():
    """Add an empty publication head; no implicit approval of existing samples."""
    op.create_table(
        "catalog_materials",
        *records(),
        sa.Column("actor_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("request_key", sa.String(36), nullable=False),
        sa.Column("storage_key", sa.String(200), nullable=False),
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.UniqueConstraint("actor_id", "request_key", name="uq_catalog_upload_request"),
    )
    op.create_table(
        "catalog_releases",
        *records(),
        sa.Column("actor_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("request_key", sa.String(36), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, unique=True),
        sa.Column("style_id", sa.String(80), nullable=False),
        sa.Column("request_json", sa.JSON(), nullable=False),
        sa.Column("catalog_json", sa.JSON(), nullable=False),
        sa.Column("images_json", sa.JSON(), nullable=False),
        sa.UniqueConstraint("actor_id", "request_key", name="uq_catalog_release_request"),
    )
    head = op.create_table(
        "catalog_heads",
        sa.Column("key", sa.String(16), primary_key=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("release_id", sa.String(36), sa.ForeignKey("catalog_releases.id")),
    )
    op.bulk_insert(head, [{"key": "catalog", "revision": 0, "release_id": None}])


def downgrade():
    """Refuse to erase published images or history without explicit archival."""
    for table in ("catalog_materials", "catalog_releases"):
        if op.get_bind().execute(sa.text(f"SELECT COUNT(*) FROM {table}")).scalar():
            raise RuntimeError("Catalog publications require an explicit archival migration")
    op.drop_table("catalog_heads")
    op.drop_table("catalog_releases")
    op.drop_table("catalog_materials")
