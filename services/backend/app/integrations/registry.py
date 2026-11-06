"""统一供应商注册与选择网关；配置驱动入口、能力、超时和环境限制。"""

import json
from hashlib import sha256

from app.core.plugins import load_symbol
from app.integrations.contracts import AsyncImageProvider, ImageProvider, LLMProvider, Storage
from app.integrations.image_sizes import image_capabilities

CONTRACTS = {"image": ImageProvider, "llm": LLMProvider, "vision": LLMProvider, "storage": Storage}


class Gateway:
    """进程装配的插件容器；密钥不进入公开目录或方案快照。"""

    def __init__(self, config: dict, settings):
        """初始化当前适配器或错误，不从浏览器接受凭证与权限。"""
        self.providers, self.definitions = {}, {}
        self.recorder = None
        self.refresh = lambda: None
        from app.modules.executions.prompts import DEFAULT_CONFIG

        self.prompt_config = config.get("creation_prompt", DEFAULT_CONFIG)
        self.routes = config["routes"]
        self.image_routes = config.get("image_routes", {})
        self.queue_limits = config.get(
            "queue_limits", {"max_batch": 8, "max_user_pending": 16, "max_pending": 500}
        )
        scopes = {}
        for name, definition in config["providers"].items():
            if not definition.get("enabled", True):
                continue
            if settings.app_env == "production" and definition.get("development_only", False):
                raise ValueError(f"production 禁止开发供应商：{name}")
            if definition["kind"] == "image":
                if settings.app_env == "production" and definition.get("release_status") != "validated":
                    raise ValueError(f"图片供应商 {name} 尚未完成真实样例验收")
                runtime = definition.get("runtime", {})
                scope = runtime.get("account_scope") or name
                shared = {
                    k: runtime.get(k)
                    for k in ("max_in_flight", "requests_per_minute", "failure_threshold", "cooldown_seconds")
                }
                if scope in scopes and scopes[scope] != shared:
                    raise ValueError("同一供应商账号必须声明一致的共享限额")
                scopes[scope] = shared
                capabilities = definition.get("capabilities", {})
                if (
                    not isinstance(capabilities.get("reference_images"), bool)
                    or type(capabilities.get("max_subjects")) is not int
                    or capabilities["max_subjects"] < 0
                    or not isinstance(capabilities.get("operations"), list)
                    or not capabilities.get("operations")
                    or not set(capabilities["operations"]).issubset({"text", "reference", "edit"})
                    or any(
                        type(capabilities.get(field)) is not int or capabilities[field] < 0
                        for field in ("max_input_images", "max_reference_images", "max_style_images")
                    )
                ):
                    raise ValueError(f"图片供应商 {name} 必须声明有效的参考图和人物数量能力")
            options = dict(definition.get("options", {}))
            if definition["kind"] in {"llm", "vision"}:
                # 网络等待属于Agent部署预算；历史模型发布中的60秒不覆盖当前运行预算。
                options["timeout_seconds"] = config.get("agent", {}).get("request_timeout_seconds", 300)
            provider = load_symbol(definition["entrypoint"])(options, settings)
            contract = CONTRACTS.get(definition["kind"])
            if contract is None or not (
                isinstance(provider, contract)
                or (definition["kind"] == "image" and isinstance(provider, AsyncImageProvider))
            ):
                raise ValueError(f"供应商 {name} 不符合 {definition['kind']} 契约")
            self.providers[name], self.definitions[name] = provider, definition
        for kind, name in self.routes.items():
            if name not in self.providers or self.definitions[name]["kind"] != kind:
                raise ValueError(f"网关路由 {kind} 引用了不可用供应商 {name}")
        for operation, name in self.image_routes.items():
            if (
                name not in self.providers
                or self.definitions[name]["kind"] != "image"
                or operation not in self.definitions[name]["capabilities"]["operations"]
            ):
                raise ValueError(f"图片操作 {operation} 引用了不兼容供应商")

    def image_policy(self, operation: str) -> dict:
        """操作路由可独立配置；未指定时使用默认图片插件，能力不足时明确拒绝。"""
        self.refresh()
        policy = self.snapshot("image", self.image_routes.get(operation))
        if operation not in self.definitions[policy["provider_id"]]["capabilities"]["operations"]:
            from app.core.errors import DomainError

            raise DomainError("OPERATION_UNAVAILABLE", "当前模型尚未开放此创作方式", 422)
        return policy

    def get(self, kind: str, provider_id: str | None = None, *, audit_context: dict | None = None):
        """允许任务使用冻结的供应商 ID，不自动更换已批准的外部副作用。"""
        self.refresh()
        name = provider_id or self.routes[kind]
        if name not in self.providers or self.definitions[name]["kind"] != kind:
            raise ValueError("供应商未安装或类型不匹配")
        provider = self.providers[name]
        if self.recorder and kind != "storage":
            return self.recorder.wrap(provider, name, self.definitions[name], audit_context)
        return provider

    def snapshot(self, kind: str, provider_id: str | None = None) -> dict:
        """冻结非敏感配置摘要；部署更换模型后旧方案必须重新确认。"""
        self.refresh()
        name = provider_id or self.routes[kind]
        if name not in self.providers or self.definitions[name]["kind"] != kind:
            raise ValueError("冻结供应商已不可用")
        definition = self.definitions[name]
        digest = sha256(json.dumps(definition, sort_keys=True).encode()).hexdigest()
        return {"provider_id": name, "config_hash": digest, "version": definition["version"]}

    def public_inventory(self) -> list[dict]:
        """运营可查看能力，不暴露 options、URL 或密钥变量。"""
        self.refresh()
        return [
            {
                "id": name,
                "kind": d["kind"],
                "version": d["version"],
                "capabilities": image_capabilities(d.get("capabilities", {}))
                if d["kind"] == "image"
                else d.get("capabilities", {}),
                "development_only": d.get("development_only", False),
            }
            for name, d in self.definitions.items()
        ]
