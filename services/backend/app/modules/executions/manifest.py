"""executions 的可插拔公开入口；显式声明依赖而非依赖导入副作用。"""

from app.core.plugins import Module

from .api import router

module = Module(
    id="executions",
    version="1.0.0",
    requires=("projects", "assets", "catalog", "commerce", "media_jobs"),
    router=router,
)
