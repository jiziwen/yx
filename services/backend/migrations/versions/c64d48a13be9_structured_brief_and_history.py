"""结构化创作需求和建议；旧记忆/聊天不变，分页复用会话 seq。"""

import sqlalchemy as sa
from alembic import op

revision = "c64d48a13be9"
down_revision = "a38f94cce1d2"
branch_labels = None
depends_on = None


def upgrade():
    """回填空需求字段，旧消息没有建议；不复制历史为已确认需求。"""
    with op.batch_alter_table("project_memories") as batch:
        batch.add_column(
            sa.Column(
                "fields_json",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'"),
                comment="用户确认的配置化创作需求字段",
            )
        )
    with op.batch_alter_table("project_memories") as batch:
        batch.alter_column("fields_json", existing_type=sa.JSON(), server_default=None)
    with op.batch_alter_table("messages") as batch:
        batch.add_column(
            sa.Column(
                "brief_suggestion_json",
                sa.JSON(),
                nullable=True,
                comment="待用户确认的结构化需求补丁，不自动保存",
            )
        )


def downgrade():
    """移除新增字段，不删除旧文字记忆、消息和生成记录。"""
    with op.batch_alter_table("messages") as batch:
        batch.drop_column("brief_suggestion_json")
    with op.batch_alter_table("project_memories") as batch:
        batch.drop_column("fields_json")
