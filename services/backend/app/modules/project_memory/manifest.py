"""项目记忆独立可停用，历史数据由迁移和隐私清理维护。"""

from app.core.plugins import Module

from .api import router

module = Module(id="project_memory", version="1.0.0", requires=("projects",), router=router)
