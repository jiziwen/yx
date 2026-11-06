"""主动看图的授权清单与临时多模态输入；不保存图片字节或远端 URL。"""

import base64
from hashlib import sha256
from io import BytesIO

from fastapi import APIRouter, Request
from PIL import Image

from app.core.errors import DomainError
from app.core.security import UserDep
from app.modules.assets.models import Asset
from app.modules.assets.service import assert_accessible
from app.modules.catalog.configuration import find_shot, shot_usage_hash
from app.modules.catalog.live import current_catalog

router = APIRouter(tags=["agents"])


@router.get("/api/v1/web/vision-capability")
def capability(request: Request, user: UserDep):
    """只公开已启用视觉路由的能力，不把聊天模型视作视觉模型。"""
    gateway = request.app.state.gateway
    gateway.refresh()
    name = gateway.routes.get("vision")
    definition = gateway.definitions.get(name, {})
    return {
        "enabled": bool(name),
        "model": definition.get("options", {}).get("model"),
        **definition.get("capabilities", {}),
    }


def prepare(app, db, project, body, context, manifest):
    """显式同意、明确用途及具体图片ID全部齐备才受理；跨项目或已撤销引用拒绝。"""
    if not body.analysis_asset_ids and not body.analysis_shots:
        return "llm"
    if not body.analysis_consent or not body.analysis_purpose.strip():
        raise DomainError("VISION_CONSENT_REQUIRED", "请确认本次发送的图片与分析用途", 422)
    app.state.gateway.refresh()
    provider = app.state.gateway.routes.get("vision")
    if not provider:
        raise DomainError("VISION_UNAVAILABLE", "尚未启用经过审核的视觉模型", 503)
    limits = app.state.gateway.definitions[provider].get("capabilities", {})
    ids = body.analysis_asset_ids
    if len(ids) != len(set(ids)) or len(ids) + len(body.analysis_shots) > limits.get("max_input_images", 0):
        raise DomainError("VISION_INPUT_LIMIT", "超出当前视觉模型图片数量限制", 422)
    images = []
    for asset_id in ids:
        asset = db.get(Asset, asset_id)
        if asset is None or asset.project_id != project.id:
            raise DomainError("NOT_FOUND", "图片不可访问", 404)
        assert_accessible(db, asset)
        images.append({"asset_id": asset.id, "checksum": asset.checksum, "kind": asset.kind})
    for chosen in body.analysis_shots:
        shot = find_shot(current_catalog(app, db), chosen.style_id, chosen.shot_id)
        rights = shot.get("rights", {})
        allowed = bool(
            rights.get("model_processing")
            and rights.get("source_record")
            and rights.get("reviewed_by")
            and rights.get("checksum") == shot["checksum"]
        )
        legacy_mock = shot.get("development_only") and app.state.gateway.definitions[provider].get(
            "development_only"
        )
        if not allowed and not legacy_mock:
            raise DomainError("TEMPLATE_NOT_RELEASED", "样片尚未审核模型处理用途", 422)
        images.append(
            {
                "source": "catalog",
                "style_id": chosen.style_id,
                "shot_id": chosen.shot_id,
                "asset_id": chosen.style_id + ":" + chosen.shot_id,
                "checksum": shot["checksum"],
                "usage_hash": shot_usage_hash(shot),
                "kind": "主题样片",
            }
        )
    manifest["vision"] = {"images": images, "purpose": body.analysis_purpose, "limits": limits}
    manifest["selected_asset_ids"] = sorted(set(manifest["selected_asset_ids"]) | set(ids))
    context["facts"]["role"] = "creative"
    context["facts"]["vision"] = manifest["vision"]
    return "vision"


def hydrate(app, db, run, messages):
    """临调用才读取所选对象，复核摘要、去元数据并缩小到声明尺寸，不写日志。"""
    vision = run.manifest_json.get("vision")
    if not vision:
        return messages
    parts = [{"type": "text", "text": "本轮用户明确授权的图像。用途：" + vision["purpose"]}]
    total = 0
    for item in vision["images"]:
        if item.get("source") == "catalog":
            shot = find_shot(current_catalog(app, db), item["style_id"], item["shot_id"])
            if shot["checksum"] != item["checksum"] or (
                item.get("usage_hash") and item["usage_hash"] != shot_usage_hash(shot)
            ):
                raise DomainError("INPUT_CHANGED", "分析样片已变化")
            content = current_catalog(app, db)["_images"][(item["style_id"], item["shot_id"])]
        else:
            asset = db.get(Asset, item["asset_id"])
            if not asset or asset.project_id != run.project_id or asset.checksum != item["checksum"]:
                raise DomainError("INPUT_CHANGED", "待分析图片已变化")
            assert_accessible(db, asset)
            content = app.state.gateway.get("storage").get(asset.storage_key)
        if sha256(content).hexdigest() != item["checksum"]:
            raise DomainError("INPUT_CHANGED", "待分析图片摘要不匹配")
        with Image.open(BytesIO(content)) as source:
            image = source.convert("RGB")
            edge = vision["limits"]["max_dimension"]
            image.thumbnail((edge, edge))
            output = BytesIO()
            image.save(output, "JPEG", quality=85)
        raw = output.getvalue()
        total += len(raw)
        if total > vision["limits"]["max_bytes"]:
            raise DomainError("VISION_INPUT_LIMIT", "分析图片超过请求大小限制", 422)
        parts += [
            {"type": "text", "text": item["kind"] + " · " + item["asset_id"]},
            {
                "type": "image_url",
                "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(raw).decode()},
            },
        ]
    return [*messages, {"role": "user", "content": parts}]
