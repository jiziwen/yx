"""插件契约验证：缺失依赖、循环、模块禁用和生产防误用。"""

from copy import deepcopy

import pytest
import yaml
from fastapi import APIRouter

from app.core.config import Settings
from app.core.plugins import Module, resolve_modules
from app.main import create_app


def test_module_missing_dependency_fails(app):
    """禁止静默启用依赖已关闭的模块。"""
    entries = deepcopy(app.state.config["modules"])
    for entry in entries:
        if "assets.manifest" in entry["entrypoint"]:
            entry["enabled"] = False
    with pytest.raises(ValueError, match="依赖"):
        resolve_modules(entries)


def test_disabled_module_removes_routes(app, tmp_path):
    """后台模块关闭后其 API 不会继续挂载，其他功能仍可启动。"""
    config = deepcopy(app.state.config)
    for entry in config["modules"]:
        if "operations.manifest" in entry["entrypoint"]:
            entry["enabled"] = False
    file = tmp_path / "config.yaml"
    file.write_text(yaml.safe_dump(config), encoding="utf-8")
    other = create_app(app.state.settings.model_copy(update={"config_file": file}), engine=app.state.engine)
    assert all(route.path != "/api/v1/admin/overview" for route in other.routes)
    assert "operations" not in [module.id for module in other.state.modules]


def test_duplicate_and_circular_modules_rejected(monkeypatch):
    """自定义模块注册也必须检查循环，而非只验证内置清单。"""
    registry = {"a": Module("a", "1", ("b",), APIRouter()), "b": Module("b", "1", ("a",), APIRouter())}
    monkeypatch.setattr("app.core.plugins.load_symbol", registry.__getitem__)
    with pytest.raises(ValueError):
        resolve_modules([{"entrypoint": "a"}, {"entrypoint": "b"}])
    with pytest.raises(ValueError):
        resolve_modules([{"entrypoint": "a"}, {"entrypoint": "a"}])


def test_production_rejects_mock_and_weak_config():
    """生产不能使用开发会话、SQLite 或假供应商。"""
    with pytest.raises(ValueError, match="production"):
        create_app(Settings(app_env="production"))
    with pytest.raises(ValueError, match="开发供应商"):
        create_app(
            Settings(
                app_env="production",
                database_url="postgresql+psycopg://unused",
                dev_login_enabled=False,
                session_secret="x" * 48,
                admin_password="configured-strong-password",
                admin_auth_mode="database",
                auth_state_backend="redis",
            )
        )


def test_storage_rejects_path_traversal(app):
    """插件基础设施不能让对象键逃逸私有目录。"""
    storage = app.state.gateway.get("storage")
    with pytest.raises(ValueError):
        storage.get("../outside.png")


def test_enabling_feature_requires_real_module(app, tmp_path):
    """未安装的聊天/赠品不能仅改开关就伪装为可用功能。"""
    config = deepcopy(app.state.config)
    config["features"]["chat_enabled"] = True
    config["modules"] = [
        entry
        for entry in config["modules"]
        if not any(name in entry["entrypoint"] for name in ("conversations", "agents"))
    ]
    file = tmp_path / "unavailable-feature.yaml"
    file.write_text(yaml.safe_dump(config), encoding="utf-8")
    with pytest.raises(ValueError, match="缺少已启用模块"):
        create_app(app.state.settings.model_copy(update={"config_file": file}), engine=app.state.engine)
