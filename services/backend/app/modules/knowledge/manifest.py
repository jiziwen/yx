"""知识模块注册；关闭入口和检索，不删除发布历史。"""

from app.core.plugins import Module

from .api import router

module = Module(id="knowledge", version="1.0.0", requires=("identity",), router=router)
