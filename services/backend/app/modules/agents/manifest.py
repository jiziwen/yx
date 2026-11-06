"""Agent 模块装配；只依赖会话与可读取的素材目录。"""

from app.core.plugins import Module

from .api import router
from .vision import router as vision_router

router.include_router(vision_router)

module = Module(id="agents", version="1.0.0", requires=("conversations", "assets", "catalog"), router=router)
