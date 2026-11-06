"""迁移唯一模型导入点；禁用模块仍保留其持久化历史。"""

from app.modules.agents.models import AgentRun, AgentStep
from app.modules.assets.models import Asset, AssetInput
from app.modules.catalog.models import CatalogHead, CatalogMaterial, CatalogRelease
from app.modules.commerce.models import Account, EntitlementEvent
from app.modules.conversations.models import Conversation, Message
from app.modules.executions.models import Approval, Idempotency, Plan
from app.modules.identity.models import AdminCredential, User
from app.modules.knowledge.models import (
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeIndexJob,
    KnowledgeVersion,
)
from app.modules.media_jobs.models import Job, Outbox, ProviderAttempt, RuntimeGate
from app.modules.operations.models import (  # noqa: F401
    Audit,
    ModelCall,
    ModelCandidate,
    ModelRelease,
    ModelSettingHead,
    QualityFeedback,
)
from app.modules.project_memory.models import ProjectMemory
from app.modules.projects.models import Project, StudioDraft, Subject
