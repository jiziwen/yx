"""通过数据库发布指针刷新网关；历史供应商定义始终保留以恢复已批准任务。"""

from copy import deepcopy
from threading import RLock

from sqlalchemy import select

from app.integrations.registry import Gateway
from app.modules.operations.models import ModelRelease, ModelSettingHead


def merged_config(base, releases, head):
    """发布只覆盖受控模型路由，业务模块、存储和部署参数仍由可信 YAML 管理。"""
    config = deepcopy(base)
    active = None
    for release in releases:
        config["providers"].update(release.providers_json)
        if head and release.id == head.release_id:
            active = release
    if active:
        config["routes"].update(active.routes_json)
        if "image" in active.routes_json:
            config["image_routes"] = {}
    return config


def bind_live_gateway(app):
    """API 与 Worker 每次使用网关前读取同一指针；刷新不包含外部网络调用。"""
    base = deepcopy(app.state.config)
    lock = RLock()
    loaded_revision = 0

    def refresh():
        """指针变更时原子装配完整新版本，失败关闭而不是偷偷退回开发插件。"""
        nonlocal loaded_revision
        with lock:
            with app.state.sessions() as db:
                head = db.get(ModelSettingHead, "ai302")
                revision = head.revision if head else 0
                if revision == loaded_revision:
                    return
                releases = list(db.scalars(select(ModelRelease).order_by(ModelRelease.revision)))
                replacement = Gateway(merged_config(base, releases, head), app.state.settings)
            gateway = app.state.gateway
            gateway.providers, gateway.definitions = replacement.providers, replacement.definitions
            gateway.routes, gateway.image_routes = replacement.routes, replacement.image_routes
            loaded_revision = revision

    app.state.gateway.refresh = refresh
