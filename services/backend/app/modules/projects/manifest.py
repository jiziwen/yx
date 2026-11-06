"""projects 的可插拔公开入口；显式声明依赖而非依赖导入副作用。"""

from app.core.plugins import Module

from .api import router
from .deletion import router as deletion_router
from .drafts import router as drafts_router

router.include_router(drafts_router)
router.include_router(deletion_router)

module = Module(id="projects", version="1.0.0", requires=("identity", "commerce"), router=router)
