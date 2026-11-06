"""业务模块注册表：显式依赖、拓扑排序、缺失/循环检查及服务端路由装配。"""

from dataclasses import dataclass
from importlib import import_module

from fastapi import APIRouter, FastAPI


@dataclass(frozen=True)
class Module:
    """插件公开契约；禁用只关闭入口，不删除历史数据。"""

    id: str
    version: str
    requires: tuple[str, ...]
    router: APIRouter


def load_symbol(path: str):
    """只加载管理员维护的部署配置；禁止客户端提供 import 路径。"""
    module, separator, symbol = path.partition(":")
    if not separator:
        raise ValueError(f"插件入口必须是 module:symbol：{path}")
    return getattr(import_module(module), symbol)


def resolve_modules(entries: list[dict]) -> list[Module]:
    """解析启用模块并按依赖排序；配置错误不能静默降级。"""
    modules: dict[str, Module] = {}
    for entry in entries:
        if not entry.get("enabled", True):
            continue
        module = load_symbol(entry["entrypoint"])
        if not isinstance(module, Module) or module.id in modules:
            raise ValueError("业务模块类型不正确或 ID 重复")
        modules[module.id] = module
    ordered, visiting, visited = [], set(), set()

    def visit(name: str):
        """深度优先解析依赖，启动时检测循环和关闭的前置模块。"""
        if name in visited:
            return
        if name in visiting or name not in modules:
            raise ValueError(f"模块依赖缺失或存在循环：{name}")
        visiting.add(name)
        for dependency in modules[name].requires:
            visit(dependency)
        visiting.remove(name)
        visited.add(name)
        ordered.append(modules[name])

    for name in modules:
        visit(name)
    return ordered


def install_modules(app: FastAPI, entries: list[dict]) -> list[Module]:
    """挂载经过验证的模块；前端能力列表由相同装配结果提供。"""
    modules = resolve_modules(entries)
    for module in modules:
        app.include_router(module.router)
    return modules
