"""可禁用的会话模块入口；关闭入口不会删除历史。"""

from app.core.plugins import Module

from .api import router

module = Module(id="conversations", version="1.0.0", requires=("projects",), router=router)
