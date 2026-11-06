"""动态主题目录：合成图片的即时发布、来源用途、版本防重及Worker冻结边界。"""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from io import BytesIO
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import event, func, select
from test_creative_flow import accept, account, create_project, image_bytes, login, prepare, save_plan
from test_model_settings import admin

from app.main import create_app
from app.modules.catalog.live import current_catalog
from app.modules.catalog.models import CatalogHead, CatalogMaterial, CatalogRelease
from app.modules.identity.models import User
from app.modules.media_jobs.models import Job
from app.modules.operations.models import Audit
from app.workers.runtime import process_job

PATH = "/api/v1/admin/theme-materials"


def upload(client, content=None, key=None):
    """同正式multipart协议，只使用合成无人物色块。"""
    return client.post(
        PATH + "/images",
        data={"request_key": key or str(uuid4())},
        files={"file": ("synthetic.webp", content or image_bytes(), "image/webp")},
    )


def body(client, image=None, **shot_patch):
    """与后台相同完整套系编辑输入，确认用途的证据明确标为测试。"""
    current = client.get(PATH).json()
    style = next(style for style in current["styles"] if style["id"] == "portrait_portrait_01")
    fields = ("id", "name", "kind", "theme_id", "mood", "description", "enabled")
    return {
        "request_key": str(uuid4()),
        "expected_revision": current["revision"],
        "style": {
            **{key: style[key] for key in fields},
            "shots": [
                {
                    "id": "scene",
                    "name": "合成主题镜头",
                    "material_id": image["id"] if image else None,
                    "position": "50% 35%",
                    "subject_slots": ["only"],
                    "enabled": True,
                    "source_record": "合成验收色块，自制测试记录，不代表真实素材授权",
                    "display": True,
                    "derivative": True,
                    "model_processing": True,
                    **shot_patch,
                }
            ],
        },
    }


def publish(client, value):
    """保存即发布，不需要第二次审核请求。"""
    result = client.post(PATH, json=value)
    assert result.status_code == 200, result.text
    return result.json()


def changed_image():
    """明显不同的字节，用于检查旧任务绝不被替换图片。"""
    output = BytesIO()
    Image.new("RGB", (160, 200), "#551199").save(output, "PNG")
    return output.getvalue()


def test_upload_publish_visible_across_instances_no_restart(client, app):
    """API与Worker实例先启动，保存后均读取新版；上传本身不能公开图片。"""
    login(client)
    project = create_project(client)
    admin(client)
    worker = create_app(app.state.settings, engine=app.state.engine)
    assert current_catalog(worker)["version"] == app.state.catalog["version"]
    key = str(uuid4())
    image = upload(client, key=key).json()
    assert upload(client, key=key).json() == image
    assert upload(client, changed_image(), key=key).status_code == 409
    assert client.get(image["image"]).status_code == 200
    assert client.get("/api/v1/web/inspiration/portrait_portrait_01/new/content").status_code == 422
    assert client.get(PATH).json()["revision"] == 0
    value = body(client, image)
    saved = publish(client, value)
    assert client.post(PATH, json=value).json() == saved
    assert saved["revision"] == 1
    shot = next(
        s for s in client.get("/api/v1/web/catalog").json()["styles"] if s["id"] == value["style"]["id"]
    )["shots"][0]
    assert shot["rights_approved"] and not shot["development_only"]
    assert client.get(shot["image"]).content == client.get(image["image"]).content
    assert current_catalog(worker)["styles"][2]["shots"][0]["checksum"] == image["checksum"]
    assert "storage_key" not in str(saved) and "source_record" not in client.get("/api/v1/web/catalog").text
    assert len(client.get(PATH + "/releases").json()) == 1
    with app.state.sessions() as db:
        assert db.scalar(select(func.count()).select_from(CatalogMaterial)) == 1
        assert db.scalar(select(func.count()).select_from(CatalogRelease)) == 1
        assert (
            db.scalar(select(func.count()).select_from(Audit).where(Audit.action == "catalog.publish")) == 1
        )
        assert db.scalar(select(func.count()).select_from(Job)) == 0
    # 切换用途后新目录已变化；重复旧请求仍返回同一版本，不覆盖新指针。
    publish(client, body(client, image, model_processing=False))
    assert client.post(PATH, json=value).json()["revision"] == 1
    assert client.get(PATH).json()["revision"] == 2
    assert client.get(f"/api/v1/web/projects/{project['id']}/jobs").json() == []


def test_display_only_hide_and_restore_source_rules(client, app):
    """展示用途与真实生成区分，来源缺失拒绝，撤回展示后公开URL也不可访问。"""
    login(client)
    project, _, _ = prepare(client)
    admin(client)
    image = upload(client).json()
    value = body(client, image, derivative=False, model_processing=False)
    publish(client, value)
    catalog = client.get("/api/v1/web/catalog").json()
    style = next(s for s in catalog["styles"] if s["id"] == "portrait_portrait_01")
    shot = style["shots"][0]
    assert not shot["rights_approved"] and client.get(shot["image"]).status_code == 200
    ref = client.get(f"/api/v1/web/projects/{project['id']}/assets").json()[0]["id"]
    plan = client.post(
        f"/api/v1/web/projects/{project['id']}/plans",
        headers={"Idempotency-Key": str(uuid4())},
        json={
            "mode": "portrait",
            "style_id": style["id"],
            "style_version": style["version"],
            "aspect_ratio": "3:4",
            "count": 1,
            "mood": "柔光",
            "notes": "测试",
            "reference_asset_ids": [ref],
            "style_shot_ids": [shot["id"]],
            "expected_revision": project["brief_revision"],
        },
    )
    assert plan.status_code == 422 and plan.json()["error"]["code"] == "SHOT_USAGE_NOT_ALLOWED"
    invalid = body(client, image, source_record="   ")
    assert client.post(PATH, json=invalid).status_code == 422
    publish(client, body(client, image, display=False))
    assert client.get(shot["image"]).status_code == 422
    assert client.get(PATH + f"/styles/{style['id']}/shots/{shot['id']}/content").status_code == 200
    assert next(s for s in current_catalog(app)["styles"] if s["id"] == style["id"])["shots"] == []


def test_frozen_confirmation_and_queued_worker_reject_changed_images_or_usage(client, app):
    """新素材可走真实路由能力检查；未确认不出图，换图/撤回用途后旧任务不付费提交。"""
    login(client)
    project, _, _ = prepare(client)
    ref = client.get(f"/api/v1/web/projects/{project['id']}/assets").json()[0]["id"]
    admin(client)
    old_worker = create_app(app.state.settings, engine=app.state.engine)
    image = upload(client).json()
    saved = publish(client, body(client, image))
    style = next(s for s in saved["styles"] if s["id"] == "portrait_portrait_01")
    # 只用本地合成适配器验证真实路由门禁，没有网络调用或真实质量结论。
    app.state.gateway.definitions["local-image"]["development_only"] = False
    plan = save_plan(
        client,
        project,
        mode="portrait",
        count=1,
        style_version=style["version"],
        style_shot_ids=["scene"],
        reference_asset_ids=[ref],
    )
    assert client.get(f"/api/v1/web/projects/{project['id']}/jobs").json() == []
    job = accept(client, plan).json()["job_ids"][0]
    replacement = upload(client, changed_image()).json()
    publish(client, body(client, replacement))
    assert process_job(old_worker, job)
    with app.state.sessions() as db:
        assert db.get(Job, job).status == "failed" and db.get(Job, job).error_code == "TEMPLATE_CHANGED"
    assert account(client, project)["available"] == 8
    new_style = next(s for s in current_catalog(app)["styles"] if s["id"] == style["id"])
    plan2 = save_plan(
        client,
        project,
        mode="portrait",
        count=1,
        style_version=new_style["version"],
        style_shot_ids=["scene"],
        reference_asset_ids=[ref],
    )
    publish(client, body(client, replacement, model_processing=False))
    response = accept(client, plan2)
    assert response.status_code == 409 and response.json()["error"]["code"] == "TEMPLATE_CHANGED"
    assert account(client, project)["available"] == 8


def test_publish_request_conflict_and_concurrent_head(client, app):
    """同键重复不重复发布；并发编辑一个版本只有一个不同请求可生效。"""
    admin(client)
    image = upload(client).json()
    value = body(client, image)

    def post(payload):
        """独立数据库连接竞争同一个发布指针。"""
        with TestClient(app) as other:
            other.cookies.update(client.cookies)
            return other.post(PATH, json=payload)

    with ThreadPoolExecutor(2) as pool:
        responses = list(pool.map(post, [value, value]))
    assert [response.status_code for response in responses] == [200, 200]
    conflict = deepcopy(value)
    conflict["style"]["name"] = "同键不同名称"
    assert client.post(PATH, json=conflict).json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    first, second = body(client, image), body(client, image)
    second["style"]["name"] = "并发名称"
    with ThreadPoolExecutor(2) as pool:
        responses = list(pool.map(post, [first, second]))
    assert sorted(response.status_code for response in responses) == [200, 409]
    assert client.get(PATH).json()["revision"] == 2


def test_upload_authorization_validation_and_publish_atomicity(client, app):
    """管理权限、图片验证及审计回滚，不创建没有来源/流水的公开素材。"""
    login(client)
    assert upload(client).status_code == 401
    admin(client)
    identity = client.get("/api/v1/admin/me").json()
    assert upload(client, b"not-an-image").status_code == 422
    old_limit = app.state.settings.max_upload_bytes
    app.state.settings.max_upload_bytes = 4
    assert upload(client).status_code == 413
    app.state.settings.max_upload_bytes = old_limit
    image = upload(client).json()
    with app.state.sessions() as db:
        db.get(User, identity["id"]).role = "staff"
        db.commit()
    assert client.get(PATH).status_code == 403
    assert client.get(image["image"]).status_code == 403
    assert upload(client).status_code == 403
    with app.state.sessions() as db:
        db.get(User, identity["id"]).role = "admin"
        db.commit()
    value = body(client, image)

    def fail(mapper, connection, target):
        """审计失败必须回滚目录版本和指针。"""
        if target.action == "catalog.publish":
            raise RuntimeError("synthetic publication audit failure")

    event.listen(Audit, "before_insert", fail)
    try:
        with TestClient(app, raise_server_exceptions=False) as other:
            other.cookies.update(client.cookies)
            assert other.post(PATH, json=value).status_code == 500
    finally:
        event.remove(Audit, "before_insert", fail)
    assert client.get(PATH).json()["revision"] == 0
    with app.state.sessions() as db:
        assert db.scalar(select(func.count()).select_from(CatalogRelease)) == 0
    assert publish(client, value)["revision"] == 1


def test_bootstrap_promotion_new_style_and_image_checksum(client, app):
    """可为既有图片补来源用途，也可新增套系；未改配置文件和目录原始图片。"""
    admin(client)
    original = app.state.settings.catalog_file.read_bytes()
    publish(client, body(client))
    public = client.get("/api/v1/web/catalog").json()
    shot = next(s for s in public["styles"] if s["id"] == "portrait_portrait_01")["shots"][0]
    assert shot["rights_approved"] and not shot["development_only"]
    image = upload(client, changed_image()).json()
    value = body(client, image)
    value["style"].update(id="new_theme", name="新合成套系")
    publish(client, value)
    assert any(s["id"] == "new_theme" for s in client.get("/api/v1/web/catalog").json()["styles"])
    assert app.state.settings.catalog_file.read_bytes() == original
    assert client.get(shot["image"].split("?")[0] + "?checksum=old").status_code == 409
    with app.state.sessions() as db:
        row = db.get(CatalogMaterial, image["id"])
        app.state.gateway.get("storage").put(row.storage_key, image_bytes())
    url = next(s for s in client.get("/api/v1/web/catalog").json()["styles"] if s["id"] == "new_theme")[
        "shots"
    ][0]["image"]
    assert client.get(url).status_code == 409


def test_catalog_migration_roundtrip_and_non_destructive_guard(client, app):
    """空目录版本可回退；有发布记录后拒绝无声删除历史。"""
    login(client)
    project = create_project(client)
    config = Config("alembic.ini")
    command.downgrade(config, "f25b09310a11")
    assert client.get("/ready").status_code == 503
    command.upgrade(config, "head")
    command.check(config)
    assert client.get(f"/api/v1/web/projects/{project['id']}").status_code == 200
    admin(client)
    publish(client, body(client))
    with pytest.raises(RuntimeError, match="archival"):
        command.downgrade(config, "f25b09310a11")
    assert client.get(PATH).json()["revision"] == 1
    with app.state.sessions() as db:
        assert db.get(CatalogHead, "catalog").revision == 1


def test_history_keeps_original_image_and_usage_without_republishing(client):
    """历史预览读取该版不可变对象；撤回展示后也只有管理员可以核对旧图片。"""
    admin(client)
    first_image = upload(client).json()
    publish(client, body(client, first_image))
    first = client.get(PATH + "/releases").json()[0]
    new_image = upload(client, changed_image()).json()
    publish(client, body(client, new_image, model_processing=False))
    history = client.get(PATH + f"/releases/{first['id']}").json()
    old_shot = next(style for style in history["styles"] if style["id"] == first["style_id"])["shots"][0]
    assert history["revision"] == 1 and old_shot["model_processing"]
    assert client.get(old_shot["image"]).content == client.get(first_image["image"]).content
    assert client.get(PATH).json()["revision"] == 2
    with TestClient(client.app) as visitor:
        assert visitor.get(old_shot["image"]).status_code == 401


def test_existing_worker_uses_new_catalog_image_after_confirmation(client, app):
    """在发布前启动Worker；发布后确认的任务使用新图片，保存本身不出图。"""
    login(client)
    project, _, _ = prepare(client)
    reference = client.get(f"/api/v1/web/projects/{project['id']}/assets").json()[0]["id"]
    admin(client)
    worker = create_app(app.state.settings, engine=app.state.engine)
    image = upload(client, changed_image()).json()
    snapshot = publish(client, body(client, image))
    style = next(s for s in snapshot["styles"] if s["id"] == "portrait_portrait_01")
    provider = worker.state.gateway.get("image")
    calls = []
    original = provider.generate

    def generate(request):
        """本地显式开发卡片，记录冻结角色和字节，不调用收费供应商。"""
        calls.append(request)
        return original(request)

    provider.generate = generate
    plan = save_plan(
        client,
        project,
        mode="portrait",
        count=1,
        style_version=style["version"],
        style_shot_ids=["scene"],
        reference_asset_ids=[reference],
    )
    assert not calls and not client.get(f"/api/v1/web/projects/{project['id']}/jobs").json()
    job_id = accept(client, plan).json()["job_ids"][0]
    assert process_job(worker, job_id)
    assert len(calls) == 1 and calls[0].input_roles == ("person", "style")
    assert calls[0].references[-1] == client.get(image["image"]).content
    assert account(client, project)["consumed"] == 1


def test_catalog_data_version_invalidates_late_agent_without_changing_code_release(client, app):
    """目录数据单独冻结，保存无需重做代码质量审批；迟到提案仍不可覆盖新版。"""
    from test_agent import install, send, snapshot

    from app.modules.agents.releases import release_snapshot
    from app.workers.agent_runtime import process_run

    login(client)
    project = create_project(client)
    admin(client)
    policy = app.state.gateway.snapshot("llm")
    before = release_snapshot(app, policy)

    def publish_during_reply(messages):
        """模拟模型调用期间另一位管理员已提交新素材用途。"""
        publish(client, body(client))
        return {"outcome": "answer", "reply": "旧目录下的回复"}

    install(app, [publish_during_reply, {"outcome": "answer", "reply": "已使用最新目录"}])
    run, _ = send(client, project)
    assert not process_run(app, run["id"])
    view = snapshot(client, project)
    assert view["runs"][-1]["error_code"] == "CATALOG_CHANGED"
    assert len(view["messages"]) == 1
    after = release_snapshot(app, policy)
    assert before["release_digest"] == after["release_digest"]
    assert before["runtime_catalog_digest"] != after["runtime_catalog_digest"]
    next_run, _ = send(client, project, "继续按新主题整理")
    assert process_run(app, next_run["id"])


def test_model_processing_permission_is_independent_from_derivative_creation(client, app):
    """允许模型分析但不允许衍生出图的素材，仅能按主动看图路径分析。"""
    from test_agent import ScriptedLLM, send

    from app.workers.agent_runtime import process_run

    login(client)
    project = create_project(client)
    admin(client)
    publish(client, body(client, derivative=False, model_processing=True))
    definition = deepcopy(app.state.gateway.definitions["local-llm"])
    definition.update(
        kind="vision", capabilities={"max_input_images": 2, "max_dimension": 512, "max_bytes": 1000000}
    )
    app.state.gateway.definitions["test-vision"] = definition
    app.state.gateway.routes["vision"] = "test-vision"
    app.state.gateway.providers["test-vision"] = ScriptedLLM(
        [{"outcome": "answer", "reply": "这是合成测试的光线分析。"}]
    )
    run, _ = send(
        client,
        project,
        "分析当前样片",
        analysis_shots=[{"style_id": "portrait_portrait_01", "shot_id": "scene"}],
        analysis_consent=True,
        analysis_purpose="合成光线分析",
    )
    assert process_run(app, run["id"])
    publish(client, body(client, derivative=False, model_processing=False))
    response = client.post(
        f"/api/v1/web/projects/{project['id']}/messages",
        json={
            "client_message_id": str(uuid4()),
            "text": "再次分析",
            "expected_revision": project["brief_revision"],
            "draft": __import__("test_agent").draft(),
            "analysis_shots": [{"style_id": "portrait_portrait_01", "shot_id": "scene"}],
            "analysis_consent": True,
            "analysis_purpose": "合成光线分析",
        },
    )
    assert response.status_code == 422 and response.json()["error"]["code"] == "TEMPLATE_NOT_RELEASED"
