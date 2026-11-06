"""私有文件授权、图片验证与输入快照校验；任何旧授权均不能绕过检查。"""

from io import BytesIO

from PIL import Image, UnidentifiedImageError
from sqlalchemy import select

from app.core.errors import DomainError
from app.modules.projects.models import Subject

from .models import Asset, AssetInput

Image.MAX_IMAGE_PIXELS = 30_000_000


def normalize_image(content: bytes) -> tuple[bytes, int, int]:
    """服务端解码、限制像素并去 EXIF；永远不信任文件扩展名。"""
    try:
        with Image.open(BytesIO(content)) as image:
            if image.format not in {"JPEG", "PNG", "WEBP"}:
                raise ValueError("format")
            if image.width * image.height > 30_000_000 or min(image.size) < 64:
                raise ValueError("size")
            image.load()
            image = image.convert("RGB")
            image.thumbnail((4096, 4096))
            result = BytesIO()
            image.save(result, "PNG")
            return result.getvalue(), image.width, image.height
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise DomainError(
            "INVALID_IMAGE", "请上传有效的 JPG、PNG 或 WebP 图片（64 像素以上，最多 3000 万像素）", 422
        ) from exc


def assert_accessible(db, asset: Asset) -> None:
    """先检查状态，再按人物和派生血缘检查撤销，阻断签发新访问。"""
    # 连续编辑可能形成多代血缘；撤销任何祖先都必须立即阻断后代访问。
    pending, visited = [asset.id], set()
    while pending:
        current_id = pending.pop()
        if current_id in visited:
            continue
        visited.add(current_id)
        current = db.get(Asset, current_id)
        if current is None or current.status != "ready" or current.project_id != asset.project_id:
            raise DomainError("ASSET_UNAVAILABLE", "文件或原始输入已撤销", 404)
        if current.subject_id:
            subject = db.get(Subject, current.subject_id)
            if subject is None or subject.authorization_state != "declared":
                raise DomainError("AUTHORIZATION_REVOKED", "原始输入人物授权已撤销", 404)
        pending.extend(db.scalars(select(AssetInput.input_asset_id).where(AssetInput.asset_id == current_id)))


def verify_inputs(db, project, manifest: list[dict], privacy_epoch: int) -> None:
    """确认前、外部提交前及输出提交前重新检查冻结授权与素材。"""
    if project.lifecycle != "active" or project.privacy_epoch != privacy_epoch:
        raise DomainError("AUTHORIZATION_CHANGED", "项目状态或人物授权已变化")
    for item in manifest:
        if item.get("source") == "catalog":
            continue
        asset = db.get(Asset, item["asset_id"])
        if asset is None or asset.project_id != project.id:
            raise DomainError("INPUT_CHANGED", "参考图或人物授权已变化")
        if item.get("subject_id"):
            subject = db.get(Subject, item["subject_id"])
            if (
                subject is None
                or asset.subject_id != subject.id
                or subject.project_id != project.id
                or subject.authorization_revision != item["authorization_revision"]
            ):
                raise DomainError("INPUT_CHANGED", "参考图或人物授权已变化")
        assert_accessible(db, asset)
