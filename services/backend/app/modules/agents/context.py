"""受控只读工具与上下文构建；只传选中素材的元数据，不传照片或下载链接。"""

import json
from dataclasses import dataclass
from hashlib import sha256

from sqlalchemy import select

from app.core.errors import DomainError
from app.integrations.image_sizes import image_capabilities
from app.modules.assets.models import Asset
from app.modules.assets.service import assert_accessible
from app.modules.catalog.configuration import MODES
from app.modules.catalog.live import current_catalog
from app.modules.conversations.history import cutoff_at
from app.modules.conversations.models import Message
from app.modules.project_memory.schemas import MemoryView
from app.modules.project_memory.service import memory_view
from app.modules.projects.models import Subject

from .models import AgentRun


@dataclass(frozen=True)
class ReadTool:
    """服务端绑定项目的固定工具清单；不能从模型参数获得身份或执行权限。"""

    name: str
    purpose: str
    version: str = "1"
    role: str = "creative"
    scope: str = "current_project"
    read_only: bool = True
    retry: str = "none"
    max_output_chars: int = 8000


TOOLS = (
    ReadTool("get_project_context", "当前项目类型、需求版本和未保存表单"),
    ReadTool("list_styles", "当前项目可选套系和已配置模型能力"),
    ReadTool("get_selected_materials", "已选素材的用途、尺寸及人物数量，不读取图片"),
)


def fingerprint(value) -> str:
    """规范摘要用于幂等和草稿冲突，不用于替代授权检查。"""
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def catalog_styles(app, kind=None, catalog=None):
    """目录镜头顺序与右侧图库一致；编号属于套系，不属于上传人物照。"""
    catalog = catalog if catalog is not None else current_catalog(app)
    return [
        {
            **{key: style[key] for key in ("id", "version", "name", "kind", "mood")},
            "shots": [
                {
                    **{
                        k: shot[k]
                        for k in ("id", "name", "subject_slots", "development_only", "rights_approved")
                    },
                    "display_position": index,
                }
                for index, shot in enumerate(style["shots"], 1)
            ],
        }
        for style in catalog["styles"]
        if style["enabled"] and (kind is None or style["kind"] == kind)
    ]


def catalog_context(app, kind, catalog=None):
    """模型看见的套系与画幅均来自实时目录，不自行发明模型能力。"""
    catalog = catalog if catalog is not None else current_catalog(app)
    styles = catalog_styles(app, kind, catalog)
    modes = []
    for mode in catalog["enabled_modes"]:
        try:
            policy = app.state.gateway.image_policy(MODES[mode])
            definition = app.state.gateway.definitions[policy["provider_id"]]
            caps = image_capabilities(definition["capabilities"])
            modes.append({"id": mode, **caps, "development_sample": bool(definition.get("development_only"))})
        except DomainError:
            continue
    return {"styles": styles, "modes": modes, "max_count": catalog["max_count"]}


def selection_context(style, draft):
    """冻结当前页面的目录图库、用途及选择；私有素材仅描述本次已选范围。"""
    field = {"portrait": "style_shot_ids", "template": "shot_ids"}.get(draft["mode"])
    gallery = None
    if field:
        gallery = {
            "source": "catalog",
            "role": "style_reference" if field == "style_shot_ids" else "template_base",
            "target_field": field,
            "style_id": style["id"],
            "items": [
                {"id": shot["id"], "display_position": index, "selected": shot["id"] in draft[field]}
                for index, shot in enumerate(style["shots"], 1)
            ],
        }
    return {
        "active_catalog_gallery": gallery,
        "private_materials_scope": "selected_only_not_full_project_gallery",
        "person_reference_ids": draft["reference_asset_ids"],
        "edit_base_id": draft["base_asset_id"],
    }


def build_context(app, db, project, conversation, body):
    """只纳入当前代次的完整历史轮次，当前消息和表单始终完整保留。"""
    from .releases import select_role

    role = "creative" if body.analysis_asset_ids or body.analysis_shots else select_role(app, body.text)
    if role == "support":
        from app.modules.conversations.support import build_support_context

        return build_support_context(app, db, conversation, project, body.text)
    draft = body.draft.model_dump()
    current = current_catalog(app, db)
    catalog = catalog_context(app, project.kind, current)
    style = next((s for s in current["styles"] if s["id"] == draft["style_id"]), None)
    if style is None or not style["enabled"] or style["kind"] != project.kind:
        raise DomainError("STYLE_UNAVAILABLE", "请先选择当前项目可用的套系", 422)
    shots = {shot["id"] for shot in style["shots"]}
    if not set(draft["shot_ids"] + draft["style_shot_ids"]).issubset(shots):
        raise DomainError("INPUT_CHANGED", "镜头选择已变化，请刷新目录", 409)
    asset_ids = set(draft["reference_asset_ids"] + draft.get("style_asset_ids", []))
    if draft["base_asset_id"]:
        asset_ids.add(draft["base_asset_id"])
    materials = []
    for asset_id in sorted(asset_ids):
        asset = db.get(Asset, asset_id)
        if asset is None or asset.project_id != project.id:
            raise DomainError("NOT_FOUND", "素材不存在或不可访问", 404)
        assert_accessible(db, asset)
        if asset_id in draft["reference_asset_ids"] and asset.kind != "reference":
            raise DomainError("INVALID_REFERENCE", "人物参考用途不匹配", 422)
        if asset_id in draft.get("style_asset_ids", []) and asset.kind != "style":
            raise DomainError("INVALID_STYLE", "风格参考用途不匹配", 422)
        if asset_id == draft["base_asset_id"] and asset.kind not in {"base", "photo"}:
            raise DomainError("INVALID_BASE", "底图用途不匹配", 422)
        materials.append(
            {
                "id": asset.id,
                "kind": asset.kind,
                "subject_id": asset.subject_id,
                "width": asset.width,
                "height": asset.height,
            }
        )
    for subject_id in draft["positions"]:
        subject = db.get(Subject, subject_id)
        if subject is None or subject.project_id != project.id or subject.authorization_state != "declared":
            raise DomainError("NOT_FOUND", "人物不可访问", 404)
    budget = app.state.config["agent"]
    from .graph import SYSTEM

    policy = app.state.gateway.snapshot("llm")
    output_reserve = (
        app.state.gateway.definitions[policy["provider_id"]].get("options", {}).get("max_tokens", 2000)
    )
    # UTF-8 每字符最多按 3 tokens 保守估计，另保留系统规则、输出和安全余量。
    context_limit = min(
        budget["max_context_chars"],
        (budget["context_window_tokens"] - output_reserve - 1024) // 3 - len(SYSTEM),
    )
    tool_specs = app.state.agent_tools.descriptors({m.id for m in app.state.modules})
    if tool_specs and budget["max_tool_calls"]:
        context_limit -= budget["tool_context_reserve"]
    history = []
    pairs = []
    if conversation:
        cutoff = cutoff_at(db, project.id)
        history_query = select(AgentRun).where(
            AgentRun.conversation_id == conversation.id,
            AgentRun.status == "succeeded",
            AgentRun.privacy_epoch == project.privacy_epoch,
        )
        if cutoff:
            history_query = history_query.where(AgentRun.created_at >= cutoff)
        runs = list(
            db.scalars(history_query.order_by(AgentRun.created_at.desc()).limit(budget["history_turns"]))
        )
        for run in reversed(runs):
            messages = list(db.scalars(select(Message).where(Message.run_id == run.id).order_by(Message.seq)))
            if len(messages) == 2:
                pairs.append((run.id, [{"role": m.role, "content": m.text} for m in messages]))
    facts = {
        "role": "creative",
        "project": {"kind": project.kind, "brief_revision": project.brief_revision},
        "draft": draft,
        "materials": materials,
        "catalog": catalog,
        "selection": selection_context(style, draft),
        "memory": MemoryView.model_validate(memory_view(app, db, project)).model_dump(mode="json"),
        "read_tools": tool_specs if budget["max_tool_calls"] else [],
    }
    mandatory_chars = len(json.dumps(facts, ensure_ascii=False)) + len(body.text)
    if mandatory_chars > context_limit:
        raise DomainError("AGENT_CONTEXT_LIMIT", "当前必要信息过长，请缩短创作描述后再发送", 422)
    used = mandatory_chars
    included = []
    for run_id, pair in reversed(pairs):
        size = len(json.dumps(pair, ensure_ascii=False))
        if used + size > context_limit:
            break
        history = pair + history
        included.insert(0, run_id)
        used += size
    context = {"facts": facts, "history": history, "text": body.text}
    manifest = {
        "strategy": "creative-metadata-v2",
        "project_id": project.id,
        "brief_revision": project.brief_revision,
        "privacy_epoch": project.privacy_epoch,
        "history_run_ids": included,
        "selected_asset_ids": sorted(asset_ids),
        "trimmed_turns": len(pairs) - len(included),
        "input_chars": used,
        "input_token_upper_estimate": used * 3,
        "output_token_reserve": output_reserve,
        "system_token_upper_estimate": len(SYSTEM) * 3,
        "tools": [tool.name + "@" + tool.version for tool in TOOLS],
        "context_hash": fingerprint(context),
        "draft_hash": fingerprint(draft),
        "memory_revision": facts["memory"]["revision"],
        "memory_enabled": facts["memory"]["enabled"],
        "structured_memory": True,
    }
    return context, manifest


def validate_proposal(answer, context):
    """模型无权新增素材或提高上限；不完整素材只形成追问或未就绪草稿。"""
    if context["facts"].get("role") == "support":
        if (
            answer.proposal
            or answer.memory_suggestion
            or answer.brief_suggestion
            or answer.outcome == "plan_ready"
        ):
            raise ValueError("support cannot propose creative changes or memory")
        return
    if context["facts"].get("vision") and (answer.memory_suggestion or answer.brief_suggestion):
        raise ValueError("image observations cannot become memory")
    memory = context["facts"].get("memory", {})
    definitions = {field["key"]: field for field in memory.get("field_definitions", [])}
    if answer.brief_suggestion is not None and (
        not memory.get("enabled")
        or any(
            key not in definitions or len(value) > definitions[key]["max_length"]
            for key, value in answer.brief_suggestion.items()
        )
    ):
        raise ValueError("unconfigured brief fields")
    if answer.proposal is None:
        return
    if context["facts"].get("vision"):
        answer.proposal.intent = "suggestion"  # 看图结果始终先展示差异，不能直接应用。
    from .transitions import normalize_transition

    normalize_transition(answer, context)
    patch = answer.proposal.model_dump(exclude_none=True)
    original = context["facts"]["draft"]
    if "reference_asset_ids" in patch and not set(patch["reference_asset_ids"]).issubset(
        original["reference_asset_ids"]
    ):
        raise ValueError("cannot select unchosen private photos")
    if "base_asset_id" in patch and patch["base_asset_id"] != original["base_asset_id"]:
        raise ValueError("cannot select unchosen base")
    draft = {**original, **patch}
    style = next((s for s in context["facts"]["catalog"]["styles"] if s["id"] == draft["style_id"]), {})
    shot_ids = {shot["id"] for shot in style.get("shots", [])}
    if not set(draft["shot_ids"] + draft["style_shot_ids"]).issubset(shot_ids):
        raise ValueError("unknown shot reference")
    confirmed = [
        *memory.get("requirements", []),
        *[
            definitions[key]["label"] + "：" + value
            for key, value in memory.get("fields", {}).items()
            if key in definitions
        ],
    ]
    missing = [item for item in confirmed if memory.get("enabled") and item not in draft["notes"]]
    if missing:
        notes = "；".join([part for part in [draft["notes"], *missing] if part])
        if len(notes) > 1000:
            raise ValueError("confirmed requirements do not fit notes; ask user to shorten")
        # 将已确认原话补入建议，不直接改表单或正式方案；写入仍由用户选择。
        answer.proposal.notes = notes
        draft["notes"] = notes
    catalog = context["facts"]["catalog"]
    mode = next((item for item in catalog["modes"] if item["id"] == draft["mode"]), None)
    if mode is None or draft["style_id"] not in {s["id"] for s in catalog["styles"]}:
        raise ValueError("mode/style unavailable")
    count = draft["count"] if draft["mode"] != "template" else len(draft["shot_ids"]) * draft["variants"]
    if count > catalog["max_count"]:
        raise ValueError("count exceeds configured limit")
    references = [m for m in context["facts"]["materials"] if m["id"] in draft["reference_asset_ids"]]
    if draft["mode"] in {"portrait", "template"}:
        style_count = (
            len(draft["style_shot_ids"]) + len(draft.get("style_asset_ids", []))
            if draft["mode"] == "portrait"
            else 0
        )
        total = len(references) + style_count + (draft["mode"] == "template")
        if (
            len(references) > mode["max_reference_images"]
            or style_count > mode["max_style_images"]
            or total > mode["max_input_images"]
            or len({m["subject_id"] for m in references}) > mode["max_subjects"]
        ):
            raise ValueError("selected materials exceed configured limits")
