"""真实创作方式验收：输入角色、模型限制、跨项目隔离和多代编辑血缘。"""

import base64
from copy import deepcopy
from uuid import uuid4

import pytest
from test_creative_flow import accept, account, create_project, image_bytes, login, prepare, save_plan

from app.core.errors import DomainError
from app.integrations.contracts import ImageRequest
from app.integrations.openai_compatible import CompatibleImage
from app.integrations.registry import Gateway
from app.modules.catalog.configuration import load_catalog
from app.workers.runtime import maintenance, tick


def refresh(client, project):
    """上传后读取权威项目修订。"""
    return client.get(f"/api/v1/web/projects/{project['id']}").json()


def base_upload(client, project, declared="true"):
    """底图独立上传，仍必须声明使用权。"""
    return client.post(
        f"/api/v1/web/projects/{project['id']}/uploads",
        data={"purpose": "base", "declared": declared},
        files={"file": ("synthetic.png", image_bytes(), "image/png")},
    )


def capture_requests(app):
    """记录实际进入适配器的请求，保留开发卡片生成。"""
    captured = []
    provider = app.state.gateway.get("image")
    generate = provider.generate

    def capture(request):
        """不发送外部请求，只观察真实请求编译。"""
        captured.append(request)
        return generate(request)

    provider.generate = capture
    return captured


def test_text_zero_images_and_base_only_edit(client, app):
    """文生图无人物，编辑只传底图；两者保存不执行、确认后真实结算。"""
    login(client)
    project = create_project(client)
    client.post(f"/api/v1/web/projects/{project['id']}/trial-grants")
    captured = capture_requests(app)
    plan = save_plan(client, project, mode="text", reference_asset_ids=[], count=1)
    assert plan["spec_json"]["items"][0]["inputs"] == []
    assert client.get(f"/api/v1/web/projects/{project['id']}/jobs").json() == []
    assert accept(client, plan).status_code == 200
    assert tick(app) == 1
    assert captured[0].operation == "text" and captured[0].references == ()
    assert base_upload(client, project, "false").json()["error"]["code"] == "IMAGE_RIGHTS_REQUIRED"
    base = base_upload(client, project).json()
    project = refresh(client, project)
    plan = save_plan(
        client,
        project,
        mode="edit",
        reference_asset_ids=[],
        base_asset_id=base["id"],
        change="暖光",
        keep=["人物与表情"],
        count=1,
    )
    assert accept(client, plan).status_code == 200
    assert tick(app) == 1
    assert captured[-1].operation == "edit" and captured[-1].input_roles == ("base",)
    assert len(captured[-1].references) == 1 and "暖光" in captured[-1].prompt
    assert account(client, project)["consumed"] == 2


def test_template_items_and_reference_selection(client, app):
    """套系按镜头与版本拆分，不发送其他底图或未选择的人物参考。"""
    login(client)
    project, subjects, _ = prepare(client)
    ref = client.get(f"/api/v1/web/projects/{project['id']}/assets").json()[0]
    client.post(
        f"/api/v1/web/projects/{project['id']}/uploads",
        data={"subject_id": subjects[0]["id"]},
        files={"file": ("second.png", image_bytes(), "image/png")},
    )
    project = refresh(client, project)
    captured = capture_requests(app)
    plan = save_plan(
        client,
        project,
        mode="template",
        reference_asset_ids=[ref["id"]],
        shot_ids=["scene", "portrait"],
        variants=2,
        count=4,
        subject_bindings=[{"subject_id": subjects[0]["id"], "position": "only"}],
    )
    assert len(plan["spec_json"]["items"]) == 4
    assert plan["spec_json"]["reference_count"] == 1
    assert accept(client, plan).status_code == 200
    assert tick(app) == 4
    assert all(
        request.input_roles == ("base", "person") and len(request.references) == 2 for request in captured
    )
    assert captured[0].references[0] == captured[1].references[0]
    assert captured[0].references[0] != captured[2].references[0]
    plan = save_plan(
        client, project, mode="portrait", reference_asset_ids=[ref["id"]], style_shot_ids=["scene"], count=1
    )
    accept(client, plan)
    assert tick(app) == 1 and captured[-1].input_roles == ("person", "style")


@pytest.mark.parametrize(
    "changes,code",
    [
        ({"mode": "text", "notes": ""}, "PROMPT_REQUIRED"),
        ({"mode": "edit", "change": "暖光"}, "BASE_REQUIRED"),
        ({"mode": "template", "shot_ids": ["scene"], "reference_asset_ids": []}, "REFERENCES_REQUIRED"),
    ],
)
def test_missing_inputs_fail_before_jobs(client, changes, code):
    """输入不足在保存阶段拒绝，不能产生任务。"""
    login(client)
    project = create_project(client)
    body = {
        "style_id": "portrait_portrait_01",
        "style_version": "1",
        "aspect_ratio": "3:4",
        "mood": "柔光",
        "notes": "画面描述",
        "count": 1,
        "expected_revision": project["brief_revision"],
        **changes,
    }
    response = client.post(
        f"/api/v1/web/projects/{project['id']}/plans", headers={"Idempotency-Key": str(uuid4())}, json=body
    )
    assert response.status_code == 422 and response.json()["error"]["code"] == code
    assert client.get(f"/api/v1/web/projects/{project['id']}/plans").json() == []


def test_limits_foreign_inputs_and_disabled_modes(client, app):
    """伪造输入上限、素材归属或模式均不能绕过服务端。"""
    login(client)
    first, second = create_project(client), create_project(client)
    foreign = base_upload(client, first).json()
    endpoint = f"/api/v1/web/projects/{second['id']}/plans"
    body = {
        "style_id": "portrait_portrait_01",
        "style_version": "1",
        "aspect_ratio": "3:4",
        "mood": "柔光",
        "notes": "场景",
        "count": 1,
        "expected_revision": second["brief_revision"],
        "mode": "edit",
        "base_asset_id": foreign["id"],
        "change": "暖光",
    }
    assert (
        client.post(endpoint, headers={"Idempotency-Key": str(uuid4())}, json=body).json()["error"]["code"]
        == "INVALID_INPUT"
    )
    own = base_upload(client, second).json()
    body.update(base_asset_id=own["id"], expected_revision=refresh(client, second)["brief_revision"])
    app.state.gateway.definitions["local-image"]["capabilities"]["max_input_images"] = 0
    assert (
        client.post(endpoint, headers={"Idempotency-Key": str(uuid4())}, json=body).json()["error"]["code"]
        == "PROVIDER_CAPABILITY_MISMATCH"
    )
    app.state.catalog["enabled_modes"].remove("edit")
    assert (
        client.post(endpoint, headers={"Idempotency-Key": str(uuid4())}, json=body).json()["error"]["code"]
        == "OPERATION_UNAVAILABLE"
    )


def test_updated_template_requires_new_plan(client, app):
    """样片修改后旧确认不能偷偷换图，拒绝前不预占次数。"""
    login(client)
    project, subjects, _ = prepare(client)
    ref = client.get(f"/api/v1/web/projects/{project['id']}/assets").json()[0]
    plan = save_plan(
        client,
        project,
        mode="template",
        reference_asset_ids=[ref["id"]],
        shot_ids=["scene"],
        count=1,
        subject_bindings=[{"subject_id": subjects[0]["id"], "position": "only"}],
    )
    style = next(style for style in app.state.catalog["styles"] if style["id"] == "portrait_portrait_01")
    style["shots"][0]["checksum"] = "changed"
    assert accept(client, plan).json()["error"]["code"] == "TEMPLATE_CHANGED"
    assert account(client, project)["reserved"] == 0


def test_multi_generation_edit_lineage_revoked_immediately(client, app):
    """连续编辑两代后，撤销原人物立即阻断后代，随后全部物理清理。"""
    login(client)
    project, subjects, plan = prepare(client)
    accept(client, plan)
    tick(app)
    endpoint = f"/api/v1/web/projects/{project['id']}/works"
    parent = client.get(endpoint).json()[0]["id"]
    for _ in range(2):
        plan = save_plan(
            client,
            project,
            mode="edit",
            reference_asset_ids=[],
            base_asset_id=parent,
            change="调整光线",
            count=1,
        )
        assert accept(client, plan).status_code == 200
        assert tick(app) == 1
        parent = client.get(endpoint).json()[-1]["id"]
    client.post(f"/api/v1/web/subjects/{subjects[0]['id']}/revoke")
    assert client.get(f"/api/v1/web/assets/{parent}/content").status_code == 404
    assert client.get(endpoint).json() == []
    for _ in range(6):
        maintenance(app)
    assert not list(app.state.settings.storage_root.rglob("*.png"))


def test_catalog_routes_and_production_samples(app, client):
    """公开能力不暴露配置文件路径与凭证，生产过滤内测镜头。"""
    response = client.get("/api/v1/web/catalog")
    assert {mode["id"] for mode in response.json()["creation_modes"]} == {
        "template",
        "portrait",
        "edit",
        "text",
    }
    assert all(secret not in response.text for secret in ['"_images"', "base_url", "api_key_env", '"file":'])
    app.state.gateway.definitions["local-image"]["capabilities"]["operations"] = ["text"]
    assert [mode["id"] for mode in client.get("/api/v1/web/catalog").json()["creation_modes"]] == ["text"]
    assert all(
        not style["shots"]
        for style in load_catalog(app.state.settings.catalog_file, allow_development=False)["styles"]
    )
    config = deepcopy(app.state.config)
    config["image_routes"] = {"text": "local-llm"}
    with pytest.raises(ValueError):
        Gateway(config, app.state.settings)
    with pytest.raises(DomainError):
        app.state.gateway.image_policy("edit")


def test_compatible_adapter_generations_and_edits(app, monkeypatch):
    """纯文字走 generations，有图走 edits；这里只检查参数，不访问供应商。"""
    monkeypatch.setenv("TEST_IMAGE_KEY", "isolated-test-key")
    provider = CompatibleImage(
        {"base_url": "https://example.invalid/v1", "model": "test-model", "api_key_env": "TEST_IMAGE_KEY"},
        app.state.settings,
    )
    calls = []

    def post(path, **kwargs):
        """替换外部请求，返回合成的无人物图片。"""
        calls.append((path, kwargs))
        return {"data": [{"b64_json": base64.b64encode(image_bytes()).decode()}]}

    provider.post = post
    provider.generate(ImageRequest("sunlight", "3:4", (), "one", operation="text"))
    provider.generate(ImageRequest("warmer", "3:4", (image_bytes(),), "two", operation="edit"))
    assert calls[0][0] == "/images/generations" and "files" not in calls[0][1]
    assert calls[1][0] == "/images/edits" and len(calls[1][1]["files"]) == 1
    provider.generate(ImageRequest("海面", "7:5", (), "three", operation="text"))
    provider.generate(
        ImageRequest("光线", "4097:513", (image_bytes(),), "four", operation="edit", size="4097x513")
    )
    assert calls[2][1]["json"]["size"] == "1022x730"
    assert calls[3][1]["data"]["size"] == "4097x513"
