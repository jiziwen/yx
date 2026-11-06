"""各API/Worker读取同一数据库版本；只按需读取图片，不依赖进程重启。"""

from copy import deepcopy
from hashlib import sha256

from app.core.errors import DomainError

from .models import CatalogHead, CatalogRelease


class CatalogImages:
    """冻结元数据对应不可变对象；保留YAML图片后备，不预载全部上传图片。"""

    def __init__(self, app, stored, catalog):
        """键和摘要仅来自服务端发布记录，不能由浏览器指定路径。"""
        self.app, self.stored = app, stored
        self.checksums = {
            (style["id"], shot["id"]): shot["checksum"]
            for style in catalog["styles"]
            for shot in style["shots"]
        }

    def __getitem__(self, key):
        """读取时检查摘要；文件丢失或内容被改不能悄悄换成其他图片。"""
        item = self.stored.get("/".join(key))
        if not item:
            content = self.app.state.catalog["_images"][key]
        else:
            content = self.app.state.gateway.get("storage").get(item["storage_key"])
        if sha256(content).hexdigest() != self.checksums[key]:
            raise DomainError("TEMPLATE_CHANGED", "主题图片内容与发布版本不一致", 409)
        return content


def current_catalog(app, db=None, *, include_hidden=False):
    """一次调用返回完整快照；调用者在同个业务用例内持有快照避免读混版本。"""
    if db is None:
        with app.state.sessions() as session:
            return current_catalog(app, session, include_hidden=include_hidden)
    head = db.get(CatalogHead, "catalog", populate_existing=True)
    if not head or not head.release_id:
        return app.state.catalog
    release = db.get(CatalogRelease, head.release_id)
    if release is None:
        raise DomainError("CATALOG_UNAVAILABLE", "生效主题目录不可用", 503)
    catalog = deepcopy(release.catalog_json)
    catalog["aspect_ratios"] = list(app.state.catalog["aspect_ratios"])
    if not include_hidden:
        for style in catalog["styles"]:
            style["shots"] = [
                shot
                for shot in style["shots"]
                if shot.get("enabled", True)
                and (
                    (shot.get("development_only") and app.state.settings.app_env != "production")
                    or shot.get("rights", {}).get("display")
                )
            ]
    catalog["_images"] = CatalogImages(app, release.images_json, catalog)
    catalog["_stored_images"] = release.images_json
    return catalog
