"""302 模型设置读写与版本发布；只接受白名单表单，不接受代码和凭证。"""

import json
import re
from copy import deepcopy
from hashlib import sha256

import httpx
from fastapi import APIRouter, Request
from sqlalchemy import select

from app.core.db import uid
from app.core.errors import DomainError
from app.core.security import DB, AdminDep
from app.integrations.image_sizes import IMAGE_SIZES
from app.integrations.live import merged_config
from app.integrations.registry import Gateway
from app.integrations.secrets import provider_secret
from app.modules.media_jobs.governance import lock_gate

from .model_schemas import (
    ImageModelSettings,
    LLMModelSettings,
    ModelSettingsInput,
    ModelSettingsView,
    ProviderModelListView,
)
from .models import Audit, ModelRelease, ModelSettingHead

router = APIRouter()


def settings_view(app, db):
    """未发布时返回用户指定开发默认值，读取不创建发布或调用外部模型。"""
    head = db.get(ModelSettingHead, "ai302")
    release = db.get(ModelRelease, head.release_id) if head and head.release_id else None
    profile = (
        release.settings_json
        if release
        else {"image": ImageModelSettings().model_dump(), "llm": LLMModelSettings().model_dump()}
    )
    return {
        "revision": head.revision if head else 0,
        **profile,
        "credentials_present": bool(provider_secret(app.state.settings, "AI302_API_KEY")),
    }


def compile_providers(app, body):
    """服务器固定入口和官方地址，模型名/档位/能力变更产生新的稳定插件 ID。"""
    definitions, routes = {}, {}
    if body.image.enabled:
        definition = deepcopy(app.state.config["providers"]["ai302-image"])
        definition.update(enabled=True, development_only=False, release_status="candidate")
        definition["entrypoint"] = (
            "app.integrations.ai302_gpt:AI302GPTImage"
            if body.image.api == "gpt"
            else "app.integrations.ai302:AI302Image"
        )
        definition["capabilities"] = {
            "arbitrary_size": True,
            "reference_images": "reference" in body.image.operations,
            **body.image.model_dump(
                include={
                    "operations",
                    "max_input_images",
                    "max_reference_images",
                    "max_style_images",
                    "max_subjects",
                    "aspect_ratios",
                }
            ),
        }
        definition["options"]["models"] = {
            "text": body.image.text_model,
            "reference": body.image.reference_model,
            "edit": body.image.edit_model,
        }
        if body.image.api == "gpt":
            definition["options"].update(
                quality=body.image.quality,
                size_by_aspect_ratio=IMAGE_SIZES,
            )
        definitions["image"] = definition
    if body.llm.enabled:
        definitions["llm"] = {
            "kind": "llm",
            "enabled": True,
            "version": "ai302-chat-v1",
            "entrypoint": "app.integrations.openai_compatible:CompatibleLLM",
            "development_only": False,
            "release_status": "candidate",
            "capabilities": {"structured_output": True},
            "options": {
                "base_url": "https://api.302.ai/v1",
                "model": body.llm.model,
                "api_key_env": "AI302_API_KEY",
                "timeout_seconds": app.state.config["agent"]["request_timeout_seconds"],
                "max_tokens": body.llm.max_tokens,
            },
        }
    if body.vision.enabled:
        definitions["vision"] = {
            "kind": "vision",
            "enabled": True,
            "version": "ai302-vision-v1",
            "entrypoint": "app.integrations.openai_compatible:CompatibleLLM",
            "development_only": False,
            "release_status": "candidate",
            "capabilities": body.vision.model_dump(
                include={"max_input_images", "max_dimension", "max_bytes"}
            ),
            "options": {
                "base_url": "https://api.302.ai/v1",
                "model": body.vision.model,
                "api_key_env": "AI302_API_KEY",
                "timeout_seconds": app.state.config["agent"]["request_timeout_seconds"],
                "max_tokens": body.vision.max_tokens,
            },
        }
    providers = {}
    for kind, definition in definitions.items():
        digest = sha256(json.dumps(definition, sort_keys=True).encode()).hexdigest()[:20]
        provider_id = f"ai302-{kind}-{digest}"
        definition["version"] = f"ui-v1-{digest}"
        providers[provider_id], routes[kind] = definition, provider_id
    return providers, routes


def publish_settings(app, db, user_id, body, *, approved=False):
    """发布、版本指针与审计同一事务；验证失败不会改动当前版本。"""
    lock_gate(db, "model-settings")
    head = db.scalar(
        select(ModelSettingHead)
        .where(ModelSettingHead.key == "ai302")
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    revision = head.revision if head else 0
    if revision != body.expected_revision:
        raise DomainError("REVISION_CONFLICT", "配置已被更新，请刷新后重新保存")
    profile = body.model_dump(exclude={"expected_revision"})
    previous = db.get(ModelRelease, head.release_id) if head and head.release_id else None
    if previous and previous.settings_json == profile:
        return settings_view(app, db)
    if (body.image.enabled or body.llm.enabled or body.vision.enabled) and not provider_secret(
        app.state.settings, "AI302_API_KEY"
    ):
        raise DomainError("PROVIDER_CREDENTIALS_MISSING", "请先在后端 .env 配置 AI302_API_KEY", 422)
    providers, routes = compile_providers(app, body)
    if approved:
        for definition in providers.values():
            definition["release_status"] = "validated"
    release = ModelRelease(
        id=uid(),
        actor_id=user_id,
        revision=revision + 1,
        settings_json=profile,
        providers_json=providers,
        routes_json=routes,
    )
    # 在写指针之前按现有历史版本装配验证；这里不发送模型请求。
    releases = list(db.scalars(select(ModelRelease).order_by(ModelRelease.revision)))
    candidate_head = ModelSettingHead(key="ai302", revision=revision + 1, release_id=release.id)
    try:
        Gateway(merged_config(app.state.config, [*releases, release], candidate_head), app.state.settings)
    except ValueError as exc:
        raise DomainError("MODEL_CONFIG_INVALID", "模型配置未通过适配器或环境校验", 422) from exc
    db.add(release)
    db.flush()
    if head is None:
        head = ModelSettingHead(key="ai302")
        db.add(head)
    head.revision, head.release_id = release.revision, release.id
    db.add(
        Audit(
            actor_id=user_id,
            action="model_settings.publish",
            resource_id=release.id,
            summary={
                "revision": release.revision,
                "image_enabled": body.image.enabled,
                "llm_enabled": body.llm.enabled,
                "providers": list(providers),
            },
        )
    )
    db.commit()
    return settings_view(app, db)


@router.get("/api/v1/admin/model-settings/ai302", response_model=ModelSettingsView)
def get_settings(request: Request, user: AdminDep, db: DB):
    """读取当前发布和密钥是否已配置，永不读取凭证值到浏览器。"""
    return settings_view(request.app, db)


@router.put("/api/v1/admin/model-settings/ai302", response_model=ModelSettingsView)
def put_settings(body: ModelSettingsInput, request: Request, user: AdminDep, db: DB):
    """显式保存发布后跨进程生效，旧方案待重新确认，已批准任务保留旧插件。"""
    raise DomainError("MODEL_CANDIDATE_REQUIRED", "请先保存候选并提交实测证据，审核后启用", 409)


@router.get("/api/v1/admin/model-settings/ai302/models", response_model=ProviderModelListView)
def list_models(request: Request, user: AdminDep):
    """只读查询实际账号可见模型；返回有界 ID，不代理任意上游正文。"""
    key = provider_secret(request.app.state.settings, "AI302_API_KEY")
    if not key:
        raise DomainError("PROVIDER_CREDENTIALS_MISSING", "请先在后端配置 AI302_API_KEY", 422)
    try:
        with httpx.Client(timeout=25, follow_redirects=False) as client:
            response = client.get("https://api.302.ai/v1/models", headers={"Authorization": f"Bearer {key}"})
            response.raise_for_status()
            rows = response.json()["data"]
            if not isinstance(rows, list):
                raise ValueError("shape")
            return {
                "models": sorted(
                    {
                        row["id"]
                        for row in rows
                        if isinstance(row, dict)
                        and isinstance(row.get("id"), str)
                        and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,119}", row["id"])
                    }
                )[:3000]
            }
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        raise DomainError(
            "PROVIDER_MODELS_UNAVAILABLE", "暂时无法读取 302 模型列表，请检查凭证或稍后重试", 502
        ) from exc
