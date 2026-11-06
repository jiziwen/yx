"""部署配置入口；可信 YAML 声明插件，密钥只通过环境变量注入。"""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class ProviderConfig(BaseModel):
    """插件声明只接受明确类别；options 是对应适配器的可信部署参数。"""

    model_config = ConfigDict(extra="forbid")
    kind: Literal["image", "llm", "storage"]
    version: str = Field(min_length=1)
    entrypoint: str = Field(min_length=3)
    enabled: bool = True
    development_only: bool = False
    release_status: Literal["candidate", "validated"] = "candidate"
    runtime: "ProviderRuntime" = Field(default_factory=lambda: ProviderRuntime())
    capabilities: dict = Field(default_factory=dict)
    options: dict = Field(default_factory=dict)


class ProviderRuntime(BaseModel):
    """账号级共享保护；相同账号的模型插件必须使用同一 account_scope 和限额。"""

    model_config = ConfigDict(extra="forbid")
    account_scope: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    max_in_flight: int = Field(default=4, ge=1, le=1000)
    requests_per_minute: int = Field(default=30, ge=1, le=10000)
    poll_seconds: int = Field(default=5, ge=1, le=300)
    failure_threshold: int = Field(default=5, ge=1, le=100)
    cooldown_seconds: int = Field(default=60, ge=1, le=3600)
    estimated_cost_micros: int | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")


class QueueLimits(BaseModel):
    """入口容量先校验再预占；未知任务继续占用用户待处理额度。"""

    model_config = ConfigDict(extra="forbid")
    max_batch: int = Field(default=8, ge=1, le=100)
    max_user_pending: int = Field(default=16, ge=1, le=1000)
    max_pending: int = Field(default=500, ge=1, le=100000)


class ModuleConfig(BaseModel):
    """模块清单与可选关闭标志。"""

    model_config = ConfigDict(extra="forbid")
    entrypoint: str
    enabled: bool = True


class TrialConfig(BaseModel):
    """活动版本与账号首次领取次数必须有界。"""

    model_config = ConfigDict(extra="forbid")
    version: str = Field(min_length=1)
    photo_count: int = Field(ge=0, le=1000)


class ApplicationConfig(BaseModel):
    """启动前校验完整配置，错误参数不能延迟到扣权益时才失败。"""

    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1]
    modules: list[ModuleConfig] = Field(min_length=1)
    features: dict[str, bool]
    trial: TrialConfig
    routes: dict[str, str]
    providers: dict[str, ProviderConfig]
    image_routes: dict[Literal["text", "reference", "edit"], str] = Field(default_factory=dict)
    queue_limits: QueueLimits = Field(default_factory=QueueLimits)
    creation_prompt: "CreationPromptConfig" = Field(default_factory=lambda: CreationPromptConfig())
    agent: "AgentConfig" = Field(default_factory=lambda: AgentConfig())
    knowledge: "KnowledgeConfig" = Field(default_factory=lambda: KnowledgeConfig())
    conversation_stream: "ConversationStreamConfig" = Field(
        default_factory=lambda: ConversationStreamConfig()
    )


class CreationPromptConfig(BaseModel):
    """图片提示词编译插件，保留与模型供应商路由独立的版本。"""

    model_config = ConfigDict(extra="forbid")
    entrypoint: str = "app.modules.executions.prompts:compose"
    version: str = Field(default="creation-v5-zh", min_length=1, max_length=80)
    options: dict = Field(default_factory=dict)


class KnowledgeConfig(BaseModel):
    """知识索引与检索插件；同一1536维空间，换模型必须重建发布。"""

    model_config = ConfigDict(extra="forbid")
    embedding_entrypoint: str = "app.integrations.embeddings:CompatibleEmbedding"
    embedding_options: dict = Field(
        default_factory=lambda: {
            "model": "Qwen/Qwen3-Embedding-8B",
            "api_key_env": "AI302_API_KEY",
            "base_url": "https://api.302.ai/v1",
        }
    )
    max_source_bytes: int = Field(default=2097152, ge=1024, le=10485760)
    max_text_chars: int = Field(default=60000, ge=1000, le=200000)
    chunk_chars: int = Field(default=700, ge=300, le=1000)
    recall_limit: int = Field(default=20, ge=5, le=50)
    result_limit: int = Field(default=5, ge=1, le=8)
    min_similarity: float = Field(default=0.3, ge=0, le=1)
    keyword_fallback: bool = True
    index_timeout_seconds: int = Field(default=90, ge=15, le=180)


class ConversationStreamConfig(BaseModel):
    """数据库通知通道，可独立关闭；不依赖供应商的 token 流协议。"""

    model_config = ConfigDict(extra="forbid")
    enabled: bool = True
    poll_seconds: float = Field(default=2, ge=0.5, le=10)
    delta_poll_seconds: float = Field(default=0.2, ge=0.1, le=1)
    heartbeat_seconds: int = Field(default=15, ge=5, le=20)
    max_connection_seconds: int = Field(default=240, ge=30, le=600)


class ReadToolConfig(BaseModel):
    """可信只读插件清单；模型只能选择已注册名称，不能指定入口。"""

    model_config = ConfigDict(extra="forbid")
    name: str = Field(pattern=r"^[a-z_]{1,60}$")
    entrypoint: str = Field(min_length=3)
    enabled: bool = True
    max_output_chars: int = Field(default=5000, ge=256, le=8000)
    timeout_ms: int = Field(default=2000, ge=100, le=5000)


class AgentConfig(BaseModel):
    """创作角色的可信编排入口和总预算；更换模型仍由网关独立管理。"""

    model_config = ConfigDict(extra="forbid")
    entrypoint: str = "app.modules.agents.graph:run_graph"
    release_file: str = "resources/agent/release.yaml"
    streaming_enabled: bool = True
    stream_flush_ms: int = Field(default=120, ge=50, le=1000)
    max_calls: int = Field(default=3, ge=1, le=4)
    max_tool_calls: int = Field(default=4, ge=0, le=8)
    tool_context_reserve: int = Field(default=4000, ge=0, le=8000)
    memory_enabled: bool = True
    memory_max_items: int = Field(default=12, ge=1, le=12)
    brief_fields: list["BriefFieldConfig"] = Field(
        default_factory=lambda: [
            BriefFieldConfig(key=key, label=label)
            for key, label in (
                ("scene", "场景"),
                ("lighting", "光线"),
                ("palette", "配色"),
                ("keep", "保留项"),
                ("avoid", "禁止项"),
            )
        ],
        max_length=8,
    )
    tools: list[ReadToolConfig] = Field(
        default_factory=lambda: [
            ReadToolConfig(name="get_entitlements", entrypoint="app.modules.agents.tools:EntitlementsTool"),
            ReadToolConfig(name="get_job_status", entrypoint="app.modules.agents.tools:JobStatusTool"),
            ReadToolConfig(
                name="search_project_history",
                entrypoint="app.modules.conversations.history:HistorySearchTool",
            ),
            ReadToolConfig(
                name="search_knowledge",
                entrypoint="app.modules.knowledge.tools:KnowledgeSearchTool",
                timeout_ms=5000,
                max_output_chars=7000,
            ),
            ReadToolConfig(name="get_catalog", entrypoint="app.modules.agents.tools:CatalogTool"),
        ],
        max_length=12,
    )
    request_timeout_seconds: int = Field(default=300, ge=1, le=300)
    deadline_seconds: int = Field(default=330, ge=15, le=600)
    max_context_chars: int = Field(default=12000, ge=3000, le=24000)
    context_window_tokens: int = Field(default=64000, ge=8000, le=2000000)
    history_turns: int = Field(default=6, ge=1, le=12)
    max_user_pending: int = Field(default=4, ge=1, le=20)
    max_pending: int = Field(default=100, ge=1, le=10000)

    @model_validator(mode="after")
    def unique_brief_fields(self):
        """部署字段必须唯一，空清单可关闭结构化需求卡。"""
        if len({field.key for field in self.brief_fields}) != len(self.brief_fields):
            raise ValueError("brief_fields key 必须唯一")
        return self


class BriefFieldConfig(BaseModel):
    """可信配置定义可确认的需求字段；不能把身份或执行权限作为字段。"""

    model_config = ConfigDict(extra="forbid")
    key: str = Field(pattern=r"^[a-z][a-z_]{0,29}$")
    label: str = Field(min_length=1, max_length=20)
    max_length: int = Field(default=160, ge=1, le=160)


class Settings(BaseSettings):
    """进程级配置；生产启动前拒绝开发身份、弱密钥和 SQLite。"""

    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")
    app_env: Literal["development", "test", "production"] = "development"
    database_url: str = "sqlite:///./.data/yingxu.db"
    session_secret: str = "local-development-only-change-before-production"
    admin_password: str = "yingxu-dev-admin"
    dev_login_enabled: bool = True
    knowledge_development_embedding: bool = False
    admin_auth_mode: Literal["development", "database"] = "development"
    auth_state_backend: Literal["memory", "redis"] = "memory"
    admin_session_ttl: int = Field(default=3600, ge=60, le=86400)
    config_file: Path = ROOT / "resources/application.yaml"
    catalog_file: Path = ROOT / "resources/catalog.yaml"
    storage_root: Path = ROOT / ".data/objects"
    m25_run_id: str | None = None
    allowed_origins: list[str] = [
        "http://127.0.0.1:5273",
        "http://127.0.0.1:5274",
        "http://localhost:5273",
        "http://localhost:5274",
    ]
    session_ttl: int = 86400
    max_upload_bytes: int = 10 * 1024 * 1024
    redis_url: str = "redis://localhost:6379/0"

    def validate_runtime(self) -> None:
        """失败即停止启动，避免生产误用本地测试配置。"""
        if self.app_env == "production":
            if self.knowledge_development_embedding:
                raise ValueError("production 禁止开发 embedding")
            if self.dev_login_enabled or self.database_url.startswith("sqlite"):
                raise ValueError("production 禁止开发登录和 SQLite")
            if len(self.session_secret) < 40 or self.session_secret.startswith("local-"):
                raise ValueError("production 必须设置独立强会话密钥")
            if self.admin_auth_mode != "database" or self.auth_state_backend != "redis":
                raise ValueError("production 必须使用受控数据库管理凭证与 Redis 认证状态")

    def application_config(self) -> dict:
        """每次启动读取并校验一次；不支持未受控的在线代码加载。"""
        return ApplicationConfig.model_validate(
            yaml.safe_load(self.config_file.read_text(encoding="utf-8"))
        ).model_dump()
