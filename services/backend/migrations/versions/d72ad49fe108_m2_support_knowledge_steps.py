"""M2 知识索引、独立客服与公开运行步骤；保留全部原创作记录。"""

import pgvector.sqlalchemy.vector
import sqlalchemy as sa
from alembic import op

revision = "d72ad49fe108"
down_revision = "c64d48a13be9"
branch_labels = None
depends_on = None


def upgrade():
    """旧会话回填拥有者和auto角色，新增内容不自动发布/接管。"""
    connection = op.get_bind()
    if connection.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    with op.batch_alter_table("conversations") as batch:
        batch.alter_column("project_id", existing_type=sa.String(36), nullable=True)
        batch.add_column(
            sa.Column(
                "owner_user_id",
                sa.String(36),
                sa.ForeignKey("users.id", name="fk_conversations_owner"),
                nullable=True,
            )
        )
        batch.add_column(
            sa.Column(
                "context_project_id",
                sa.String(36),
                sa.ForeignKey("projects.id", name="fk_conversations_context_project"),
                nullable=True,
            )
        )
        batch.add_column(sa.Column("scope_key", sa.String(150), nullable=True))
        batch.add_column(sa.Column("entry_mode", sa.String(20), nullable=False, server_default="auto"))
        batch.add_column(sa.Column("handoff_status", sa.String(20), nullable=False, server_default="bot"))
        batch.add_column(
            sa.Column(
                "assigned_staff_id",
                sa.String(36),
                sa.ForeignKey("users.id", name="fk_conversations_staff"),
                nullable=True,
            )
        )
        batch.add_column(sa.Column("revision", sa.Integer(), nullable=False, server_default="0"))
        batch.create_unique_constraint("uq_conversation_scope", ["scope_key"])
        batch.create_index("ix_conversations_owner_user_id", ["owner_user_id"])
        batch.create_index("ix_conversations_context_project_id", ["context_project_id"])
        batch.create_index("ix_conversations_handoff_status", ["handoff_status"])
    connection.exec_driver_sql(
        "UPDATE conversations SET owner_user_id=(SELECT owner_user_id FROM projects WHERE projects.id=conversations.project_id), context_project_id=project_id, scope_key='project:' || project_id || ':auto'"
    )
    with op.batch_alter_table("agent_runs") as batch:
        batch.alter_column("project_id", existing_type=sa.String(36), nullable=True)
        batch.add_column(
            sa.Column(
                "owner_user_id", sa.String(36), sa.ForeignKey("users.id", name="fk_runs_owner"), nullable=True
            )
        )
        batch.add_column(sa.Column("primary_role", sa.String(20), nullable=False, server_default="creative"))
        batch.add_column(sa.Column("release_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")))
        batch.create_index("ix_agent_runs_owner_user_id", ["owner_user_id"])
    op.execute(
        "UPDATE agent_runs SET owner_user_id=(SELECT owner_user_id FROM projects WHERE projects.id=agent_runs.project_id)"
    )
    with op.batch_alter_table("messages") as batch:
        batch.add_column(
            sa.Column("citations_json", sa.JSON(), nullable=True, comment="后端验证的已发布知识引用")
        )
        batch.add_column(
            sa.Column(
                "actor_id",
                sa.String(36),
                sa.ForeignKey("users.id", name="fk_messages_actor"),
                nullable=True,
                comment="员工消息真实操作者",
            )
        )
        batch.add_column(
            sa.Column("client_message_id", sa.String(100), nullable=True, comment="人工期间消息幂等键")
        )
        batch.create_unique_constraint("uq_support_message", ["conversation_id", "client_message_id"])

    op.create_table(
        "knowledge_documents",
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("published_version_id", sa.String(length=36), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False, comment="UUID 资源标识"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, comment="UTC 创建时间"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "knowledge_versions",
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("request_key", sa.String(length=100), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("summary", sa.String(length=300), nullable=False),
        sa.Column("category", sa.String(length=20), nullable=False),
        sa.Column("source_key", sa.String(length=200), nullable=False),
        sa.Column("source_format", sa.String(length=8), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("error_code", sa.String(length=50), nullable=True),
        sa.Column("embedding_spec", sa.JSON(), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("actor_id", sa.String(length=36), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False, comment="UUID 资源标识"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, comment="UTC 创建时间"),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["knowledge_documents.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id", "request_key"),
        sa.UniqueConstraint("document_id", "version_no"),
        sa.UniqueConstraint("document_id", "id"),
    )
    op.create_table(
        "knowledge_chunks",
        sa.Column("version_id", sa.String(length=36), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("locator", sa.String(length=100), nullable=False),
        sa.Column("search_text", sa.Text(), nullable=False),
        sa.Column(
            "embedding",
            pgvector.sqlalchemy.vector.VECTOR(dim=1536).with_variant(sa.JSON(), "sqlite"),
            nullable=False,
        ),
        sa.Column("id", sa.String(length=36), nullable=False, comment="UUID 资源标识"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, comment="UTC 创建时间"),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["knowledge_versions.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("version_id", "ordinal"),
    )
    op.create_table(
        "knowledge_index_jobs",
        sa.Column("version_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("lease_token", sa.String(length=36), nullable=True),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=50), nullable=True),
        sa.Column("usage_json", sa.JSON(), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False, comment="UUID 资源标识"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, comment="UTC 创建时间"),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["knowledge_versions.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("version_id"),
    )
    op.create_table(
        "agent_steps",
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("manifest_json", sa.JSON(), nullable=False),
        sa.Column("usage_json", sa.JSON(), nullable=True),
        sa.Column("error_code", sa.String(length=60), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False, comment="UUID 资源标识"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, comment="UTC 创建时间"),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["agent_runs.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "seq"),
    )

    for table, field in (
        ("agent_steps", "run_id"),
        ("knowledge_chunks", "version_id"),
        ("knowledge_index_jobs", "status"),
        ("knowledge_versions", "document_id"),
        ("knowledge_versions", "status"),
    ):
        op.create_index(f"ix_{table}_{field}", table, [field])
    with op.batch_alter_table("knowledge_documents") as batch:
        batch.create_foreign_key(
            "fk_knowledge_published_version",
            "knowledge_versions",
            ["id", "published_version_id"],
            ["document_id", "id"],
        )
    for table, fields in [
        ("conversations", ["entry_mode", "handoff_status", "revision"]),
        ("agent_runs", ["primary_role", "release_json"]),
    ]:
        with op.batch_alter_table(table) as batch:
            for field in fields:
                batch.alter_column(field, server_default=None)


def downgrade():
    """有新增独立客服记录时拒绝有损回退；先备份迁移数据再安排回退窗口。"""
    connection = op.get_bind()
    if connection.execute(sa.text("SELECT 1 FROM conversations WHERE entry_mode!='auto' LIMIT 1")).first():
        raise RuntimeError("存在独立客服记录，请先备份并制定数据迁移方案，禁止有损回退")
    with op.batch_alter_table("knowledge_documents") as batch:
        batch.drop_constraint("fk_knowledge_published_version", type_="foreignkey")
    for table in (
        "agent_steps",
        "knowledge_index_jobs",
        "knowledge_chunks",
        "knowledge_versions",
        "knowledge_documents",
    ):
        op.drop_table(table)
    with op.batch_alter_table("messages") as batch:
        batch.drop_constraint("uq_support_message", type_="unique")
        for field in ("citations_json", "actor_id", "client_message_id"):
            batch.drop_column(field)
    with op.batch_alter_table("agent_runs") as batch:
        batch.drop_index("ix_agent_runs_owner_user_id")
        for field in ("owner_user_id", "primary_role", "release_json"):
            batch.drop_column(field)
        batch.alter_column("project_id", existing_type=sa.String(36), nullable=False)
    with op.batch_alter_table("conversations") as batch:
        batch.drop_constraint("uq_conversation_scope", type_="unique")
        for index in ("owner_user_id", "context_project_id", "handoff_status"):
            batch.drop_index("ix_conversations_" + index)
        for field in (
            "owner_user_id",
            "context_project_id",
            "scope_key",
            "entry_mode",
            "handoff_status",
            "assigned_staff_id",
            "revision",
        ):
            batch.drop_column(field)
        batch.alter_column("project_id", existing_type=sa.String(36), nullable=False)
