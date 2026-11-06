"""每请求独立事务；业务用例显式提交，异常回滚；建表仅由 Alembic 执行。"""

from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import DateTime, String, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column


# SQLite 只用于零依赖开发；生产使用 PostgreSQL 行锁。
class Base(DeclarativeBase):
    """所有模块共享一个迁移元数据，开关不负责删除业务历史。"""


def now() -> datetime:
    """统一保存 UTC；JSON 输出补 UTC 时区。"""
    return datetime.now(timezone.utc)


def uid() -> str:
    """生成不可推测的资源标识；排序依赖显式业务版本。"""
    return str(uuid4())


class Record:
    """业务记录公共主键和创建时间。"""

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid, comment="UUID 资源标识")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, comment="UTC 创建时间")


def make_engine(url: str):
    """创建数据库连接并启用本地外键与有界锁等待。"""
    if url.startswith("sqlite"):
        Path(".data").mkdir(exist_ok=True)
    engine = create_engine(
        url,
        connect_args={"check_same_thread": False, "timeout": 15} if url.startswith("sqlite") else {},
        pool_pre_ping=True,
    )
    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def configure_sqlite(connection, _):
            """SQLite 默认不验证外键，必须显式打开。"""
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA journal_mode=WAL")

    return engine


def db_session(request) -> Iterator[Session]:
    """响应前提交由用例负责；依赖关闭时回滚所有未提交写入。"""
    with request.app.state.sessions() as session:
        yield session
