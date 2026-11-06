"""operations 的可插拔公开入口；显式声明依赖而非依赖导入副作用。"""

from app.core.plugins import Module

from .api import router
from .candidates import router as candidates_router
from .feedback import router as feedback_router

router.include_router(candidates_router)
router.include_router(feedback_router)

module = Module(
    id="operations", version="1.0.0", requires=("identity", "catalog", "media_jobs"), router=router
)
