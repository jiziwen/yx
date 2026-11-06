"""使用真实 Alembic 迁移创建隔离数据库；测试卡片不含真实个人信息。"""

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


@pytest.fixture
def app(tmp_path, monkeypatch):
    """每个用例独立数据库、私有存储和验证码内存，避免状态互相污染。"""
    url = f"sqlite:///{tmp_path / 'test.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    settings = Settings(database_url=url, storage_root=tmp_path / "objects", app_env="test")
    configuration = Config("alembic.ini")
    command.upgrade(configuration, "head")
    application = create_app(settings)
    yield application
    application.state.engine.dispose()


@pytest.fixture
def client(app):
    """同源客户端自动保存 HttpOnly Cookie。"""
    with TestClient(app) as value:
        yield value
