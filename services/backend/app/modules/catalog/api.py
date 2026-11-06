"""公共版本化目录；功能可用性来自已安装模块，前端不猜测后端能力。"""

from fastapi import APIRouter, Request, Response

from app.core.errors import DomainError
from app.core.views import CatalogView
from app.integrations.image_sizes import image_capabilities
from app.modules.executions.prompts import prompt_policy_hash

from .configuration import MODES, find_shot
from .live import current_catalog

router = APIRouter(tags=["catalog"])


@router.get("/api/v1/web/catalog", response_model=CatalogView)
def catalog(request: Request):
    """访客可浏览目录，但创作、下载必须另行验证身份。"""
    state = request.app.state
    current = current_catalog(request.app)
    modes = []
    for mode in current["enabled_modes"]:
        try:
            policy = state.gateway.image_policy(MODES[mode])
        except DomainError:
            continue
        definition = state.gateway.definitions[policy["provider_id"]]
        modes.append(
            {
                "id": mode,
                "operation": MODES[mode],
                **image_capabilities(definition["capabilities"]),
                "development_sample": definition.get("development_only", False),
            }
        )
    return {
        **current,
        "styles": [style for style in current["styles"] if style["enabled"]],
        "creation_modes": modes,
        "creation_prompt_policy_hash": prompt_policy_hash(state.gateway.prompt_config),
        "upload_limits": {**current["upload_limits"], "max_bytes": state.settings.max_upload_bytes},
        "features": state.config["features"],
        "modules": [m.id for m in state.modules],
        "development_mode": state.settings.app_env != "production",
        "dev_login_enabled": state.settings.dev_login_enabled,
        "trial_photo_count": state.config["trial"]["photo_count"],
    }


@router.get("/api/v1/web/inspiration/{style_id}/{shot_id}/content")
def inspiration(style_id: str, shot_id: str, request: Request, checksum: str | None = None):
    """公开授权样片与私有人物资产隔离，不接受任意文件路径或外部 URL。"""
    catalog = current_catalog(request.app)
    shot = find_shot(catalog, style_id, shot_id)
    if checksum and checksum != shot["checksum"]:
        raise DomainError("TEMPLATE_CHANGED", "主题图片已更新，请刷新目录", 409)
    return Response(content=catalog["_images"][(style_id, shot_id)], media_type="image/png")
