"""迁移环境；使用与 API 相同的模型和配置，生产不自动 create_all。"""

from alembic import context

import app.core.models
from app.core.config import Settings
from app.core.db import Base, make_engine

target_metadata = Base.metadata


def run_migrations():
    """以事务执行迁移；SQLite 本地开发使用批量兼容模式。"""
    settings = Settings()
    if context.is_offline_mode():
        context.configure(url=settings.database_url, target_metadata=target_metadata, literal_binds=True)
        with context.begin_transaction():
            context.run_migrations()
    else:
        engine = make_engine(settings.database_url)
        with engine.connect() as connection:
            sqlite = engine.dialect.name == "sqlite"
            if sqlite:
                # 单迁移连接暂关FK，显式事务覆盖父表重建；校验后才提交。
                connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
                connection.commit()
                connection.exec_driver_sql("BEGIN IMMEDIATE")
            context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=sqlite)
            try:
                with context.begin_transaction():
                    context.run_migrations()
                if sqlite:
                    if connection.exec_driver_sql("PRAGMA foreign_key_check").fetchone():
                        raise RuntimeError("迁移后外键校验失败")
                    connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                if sqlite:
                    connection.exec_driver_sql("PRAGMA foreign_keys=ON")
                    connection.commit()
        engine.dispose()


run_migrations()
