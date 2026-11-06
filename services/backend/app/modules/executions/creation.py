"""创作方式编译器：把用户选择变为逐交付项的、角色明确且受能力限制的输入清单。"""

from io import BytesIO
from math import gcd

from PIL import Image
from sqlalchemy import select

from app.core.errors import DomainError
from app.integrations.image_sizes import output_size
from app.modules.assets.models import Asset
from app.modules.assets.service import assert_accessible
from app.modules.catalog.configuration import MODES, find_shot, shot_usage_hash, verify_catalog_inputs
from app.modules.projects.models import Subject


def private_input(db, project, asset_id: str, role: str) -> dict:
    """仅允许本项目可访问素材，人物参考必须绑定有效授权，成片可继续作为底图。"""
    asset = db.get(Asset, asset_id)
    allowed = {"person": {"reference"}, "base": {"base", "photo"}, "style": {"style"}}[role]
    if asset is None or asset.project_id != project.id or asset.kind not in allowed:
        raise DomainError("INVALID_INPUT", "所选照片不存在、用途不匹配或不属于当前项目", 422)
    assert_accessible(db, asset)
    item = {"source": "asset", "role": role, "asset_id": asset.id}
    if role == "person":
        subject = db.get(Subject, asset.subject_id)
        if subject is None or subject.authorization_state != "declared":
            raise DomainError("REFERENCES_REQUIRED", "人物参考需要有效使用授权", 422)
        item.update(subject_id=subject.id, authorization_revision=subject.authorization_revision)
    return item


def catalog_input(catalog, style, shot_id: str, role: str) -> dict:
    """只接受当前套系注册的镜头 ID，不接收任意路径或远程 URL。"""
    shot = find_shot(catalog, style["id"], shot_id)
    return {
        "source": "catalog",
        "role": role,
        "style_id": style["id"],
        "shot_id": shot_id,
        "checksum": shot["checksum"],
        "usage_hash": shot_usage_hash(shot),
    }


def item_geometry(db, item, choice, catalog):
    """冻结实际像素尺寸；自动跟随底图，明确比例或像素尺寸按用户选择透传。"""
    if choice != "auto":
        size = output_size(choice)
        if ":" in choice:
            return choice, size
        width, height = map(int, size.split("x"))
        divisor = gcd(width, height)
        return f"{width // divisor}:{height // divisor}", size
    base = next((entry for entry in item["inputs"] if entry["role"] == "base"), None)
    if base is None:
        return "3:4", output_size("3:4")
    if base["source"] == "asset":
        asset = db.get(Asset, base["asset_id"])
        width, height = asset.width, asset.height
    else:
        shot = find_shot(catalog, base["style_id"], base["shot_id"])
        width, height = shot.get("width"), shot.get("height")
        if not width or not height:
            with Image.open(BytesIO(catalog["_images"][(base["style_id"], base["shot_id"])])) as image:
                width, height = image.size
    divisor = gcd(width, height)
    return f"{width // divisor}:{height // divisor}", f"{width}x{height}"


def compile_creation(db, project, body, catalog: dict, style: dict, gateway) -> tuple[dict, list, dict]:
    """显式模式按本次选用素材冻结；旧请求无 mode 时兼容全部已授权人物参考。"""
    mode = body.mode or "portrait"
    if mode not in catalog["enabled_modes"]:
        raise DomainError("OPERATION_UNAVAILABLE", "此创作方式尚未开放", 422)
    subject_only = body.subject_only if body.subject_only is not None else mode == "template"
    if subject_only and mode != "template":
        raise DomainError("INVALID_SPEC", "只替换人物需要样片底图与人物参考，请切换拍同款", 422)
    operation = MODES[mode]
    policy = gateway.image_policy(operation)
    caps = gateway.definitions[policy["provider_id"]]["capabilities"]
    reference_ids = body.reference_asset_ids
    if body.mode is None and reference_ids is None:
        subjects = list(
            db.scalars(
                select(Subject).where(
                    Subject.project_id == project.id, Subject.authorization_state == "declared"
                )
            )
        )
        if len(subjects) != (2 if project.kind == "wedding" else 1):
            raise DomainError("REFERENCES_REQUIRED", "请先为全部人物添加授权和参考照片", 422)
        reference_ids = list(
            db.scalars(
                select(Asset.id)
                .where(Asset.project_id == project.id, Asset.kind == "reference", Asset.status == "ready")
                .order_by(Asset.created_at)
            )
        )
        if any(
            not any(db.get(Asset, asset_id).subject_id == subject.id for asset_id in reference_ids)
            for subject in subjects
        ):
            raise DomainError("REFERENCES_REQUIRED", "每位人物都需要参考照片", 422)
    reference_ids = reference_ids or []
    groups = [reference_ids, body.shot_ids, body.style_shot_ids, body.style_asset_ids]
    if any(len(set(values)) != len(values) for values in groups):
        raise DomainError("DUPLICATE_INPUT", "同一次输入不能重复选择照片", 422)
    if mode not in {"template", "portrait"} and reference_ids:
        raise DomainError("INVALID_INPUT", "此创作方式不使用人物参考", 422)
    if mode != "template" and (body.shot_ids or body.subject_bindings):
        raise DomainError("INVALID_INPUT", "只有拍同款需要样片底图与人物对应", 422)
    if mode != "portrait" and (body.style_shot_ids or body.style_asset_ids):
        raise DomainError("INVALID_INPUT", "此创作方式不使用额外风格参考", 422)
    if mode != "edit" and body.base_asset_id:
        raise DomainError("INVALID_INPUT", "当前方式不使用上传底图", 422)
    people = [private_input(db, project, asset_id, "person") for asset_id in reference_ids]
    subject_ids = set(item["subject_id"] for item in people)
    if mode in {"template", "portrait"} and not people:
        raise DomainError("REFERENCES_REQUIRED", "请选择本次使用的人物参考照片", 422)
    bindings = [binding.model_dump() for binding in body.subject_bindings]
    if mode == "template":
        if not body.shot_ids or body.count != len(body.shot_ids) * body.variants:
            raise DomainError("INVALID_SPEC", "同款成片数必须等于镜头数乘以每镜头版本数", 422)
        if (
            {binding["subject_id"] for binding in bindings} != subject_ids
            or len(bindings) != len(subject_ids)
            or len({binding["position"] for binding in bindings}) != len(bindings)
        ):
            raise DomainError("SUBJECT_BINDING_REQUIRED", "请为每位人物指定不同的底图位置", 422)
        for shot_id in body.shot_ids:
            slots = find_shot(catalog, style["id"], shot_id)["subject_slots"]
            if any(binding["position"] not in slots for binding in bindings):
                raise DomainError("SUBJECT_BINDING_REQUIRED", "人物位置与所选镜头不匹配，请重新指定", 422)
        items = [
            {"shot_id": shot_id, "inputs": [catalog_input(catalog, style, shot_id, "base"), *people]}
            for shot_id in body.shot_ids
            for _ in range(body.variants)
        ]
    elif mode == "edit":
        if not body.base_asset_id or not body.change.strip():
            raise DomainError("BASE_REQUIRED", "请选择底图并说明修改要求", 422)
        items = [
            {"inputs": [private_input(db, project, body.base_asset_id, "base")]} for _ in range(body.count)
        ]
    elif mode == "text":
        if not body.notes.strip():
            raise DomainError("PROMPT_REQUIRED", "请填写画面描述", 422)
        items = [{"inputs": []} for _ in range(body.count)]
    else:
        references = [catalog_input(catalog, style, shot_id, "style") for shot_id in body.style_shot_ids]
        references += [private_input(db, project, asset_id, "style") for asset_id in body.style_asset_ids]
        items = [{"inputs": [*people, *references]} for _ in range(body.count)]
    for item in items:
        inputs = item["inputs"]
        if not gateway.definitions[policy["provider_id"]].get("development_only", False) and any(
            entry.get("source") == "catalog"
            and find_shot(catalog, entry["style_id"], entry["shot_id"])["development_only"]
            for entry in inputs
        ):
            raise DomainError(
                "TEMPLATE_NOT_RELEASED",
                "这张参考图尚未开放真实创作，请补齐素材来源及展示、衍生创作、模型处理用途后保存",
                422,
            )
        if any(
            entry.get("source") == "catalog"
            and not find_shot(catalog, entry["style_id"], entry["shot_id"]).get("development_only")
            and not find_shot(catalog, entry["style_id"], entry["shot_id"]).get("rights_approved")
            for entry in inputs
        ):
            raise DomainError(
                "SHOT_USAGE_NOT_ALLOWED", "所选主题图片仅允许展示，尚未开放衍生创作与模型处理用途", 422
            )
        item["aspect_ratio"], item["size"] = item_geometry(db, item, body.aspect_ratio, catalog)
        if (
            len(inputs) > caps["max_input_images"]
            or len(people) > caps["max_reference_images"]
            or sum(i["role"] == "style" for i in inputs) > caps["max_style_images"]
            or len(subject_ids) > caps["max_subjects"]
        ):
            raise DomainError(
                "PROVIDER_CAPABILITY_MISMATCH",
                "所选图片数量、人物数量或画幅超过当前模型限制，请调整选择",
                422,
            )
    manifest = []
    for item in items:
        for entry in item["inputs"]:
            if entry not in manifest:
                manifest.append(entry)
    return (
        {
            "mode": mode,
            "aspect_ratio_choice": body.aspect_ratio,
            "aspect_ratio": items[0]["aspect_ratio"]
            if len({item["aspect_ratio"] for item in items}) == 1
            else "auto",
            "subject_only": subject_only,
            "operation": operation,
            "items": items,
            "reference_asset_ids": reference_ids,
            "reference_count": len(people),
            "subject_bindings": bindings,
        },
        manifest,
        policy,
    )


def verify_templates(catalog: dict, plan) -> None:
    """检查冻结镜头；旧版只含人物参考的方案继续可读。"""
    verify_catalog_inputs(catalog, plan.input_manifest)
