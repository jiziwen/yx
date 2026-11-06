"""真实确认与Worker路径验证原图画幅、逐镜头冻结和手动覆盖；不调用付费模型。"""

from copy import deepcopy
from hashlib import sha256
from io import BytesIO
from uuid import uuid4

import pytest
from PIL import Image
from test_creation_modes import capture_requests, refresh
from test_creative_flow import accept, create_project, login, prepare, save_plan

from app.modules.assets.service import normalize_image
from app.workers.runtime import tick


def picture(width, height):
    """生成隔离的合成图片，不使用客户素材。"""
    buffer = BytesIO()
    Image.new("RGB", (width, height), "#756f66").save(buffer, "PNG")
    return buffer.getvalue()


def upload_base(client, project, width=200, height=300):
    """通过正式接口记录真实尺寸。"""
    response = client.post(
        f"/api/v1/web/projects/{project['id']}/uploads",
        data={"purpose": "base", "declared": "true"},
        files={"file": ("ratio.png", picture(width, height), "image/png")},
    )
    assert response.status_code == 200
    return response.json()


@pytest.mark.parametrize("choice,expected", [("auto", "2:3"), ("16:9", "16:9"), ("9:16", "9:16")])
def test_base_ratio_reaches_worker_and_output(client, app, choice, expected):
    """默认继承2:3底图，明确选择的横屏/竖屏不会被底图覆盖。"""
    login(client)
    project = create_project(client)
    client.post(f"/api/v1/web/projects/{project['id']}/trial-grants")
    base = upload_base(client, project)
    project = refresh(client, project)
    captured = capture_requests(app)
    plan = save_plan(
        client,
        project,
        mode="edit",
        reference_asset_ids=[],
        base_asset_id=base["id"],
        change="只调整光线",
        count=1,
        aspect_ratio=choice,
    )
    assert plan["spec_json"]["aspect_ratio_choice"] == choice
    assert plan["spec_json"]["items"][0]["aspect_ratio"] == expected
    assert accept(client, plan).status_code == 200
    assert tick(app) == 1 and captured[0].aspect_ratio == expected
    output = client.get(f"/api/v1/web/projects/{project['id']}/works").json()[0]
    x, y = map(int, expected.split(":"))
    assert output["width"] * y == output["height"] * x


def test_each_template_follows_its_own_source(client, app):
    """同一批镜头可保留各自比例，不能用第一张底图统一裁切。"""
    login(client)
    project, subjects, _ = prepare(client)
    catalog = deepcopy(app.state.catalog)
    style = next(style for style in catalog["styles"] if style["id"] == "portrait_portrait_01")
    for shot, size in zip(style["shots"], [(240, 320), (320, 180)]):
        content, width, height = normalize_image(picture(*size))
        shot.update(width=width, height=height, checksum=sha256(content).hexdigest())
        catalog["_images"][(style["id"], shot["id"])] = content
    app.state.catalog = catalog
    refs = client.get(f"/api/v1/web/projects/{project['id']}/assets").json()
    captured = capture_requests(app)
    plan = save_plan(
        client,
        project,
        mode="template",
        aspect_ratio="auto",
        reference_asset_ids=[refs[0]["id"]],
        shot_ids=[shot["id"] for shot in style["shots"]],
        count=2,
        subject_bindings=[{"subject_id": subjects[0]["id"], "position": "only"}],
    )
    assert [item["aspect_ratio"] for item in plan["spec_json"]["items"]] == ["3:4", "16:9"]
    assert accept(client, plan).status_code == 200
    assert tick(app) == 2
    assert {request.aspect_ratio for request in captured} == {"3:4", "16:9"}


@pytest.mark.parametrize("mode", ["portrait", "text"])
def test_no_base_uses_default_even_with_references(client, app, mode):
    """人物和风格参考不作为底图；无底图时明确冻结3:4。"""
    login(client)
    project, _, _ = prepare(client)
    refs = client.get(f"/api/v1/web/projects/{project['id']}/assets").json()
    plan = save_plan(
        client,
        project,
        mode=mode,
        aspect_ratio="auto",
        count=1,
        reference_asset_ids=[refs[0]["id"]] if mode == "portrait" else [],
        style_shot_ids=["scene"] if mode == "portrait" else [],
    )
    assert plan["spec_json"]["aspect_ratio"] == "3:4"


def test_arbitrary_original_size_is_frozen_and_reaches_worker_without_whitelist(client, app):
    """即便旧模型只声明三种比例，也不拦截非16倍数的小尺寸底图。"""
    login(client)
    project = create_project(client)
    base = upload_base(client, project, 202, 300)
    project = refresh(client, project)
    client.post(f"/api/v1/web/projects/{project['id']}/trial-grants")
    app.state.gateway.definitions["local-image"]["capabilities"]["aspect_ratios"] = ["3:4", "4:3", "1:1"]
    captured = capture_requests(app)
    response = client.post(
        f"/api/v1/web/projects/{project['id']}/plans",
        headers={"Idempotency-Key": str(uuid4())},
        json={
            "style_id": "portrait_portrait_01",
            "style_version": "1",
            "mode": "edit",
            "aspect_ratio": "auto",
            "count": 1,
            "base_asset_id": base["id"],
            "reference_asset_ids": [],
            "mood": "柔光",
            "change": "调整光线",
            "expected_revision": project["brief_revision"],
        },
    )
    assert response.status_code == 200
    plan = response.json()
    assert plan["spec_json"]["items"][0]["aspect_ratio"] == "101:150"
    assert plan["spec_json"]["items"][0]["size"] == "202x300"
    assert client.get(f"/api/v1/web/projects/{project['id']}/jobs").json() == []
    assert accept(client, plan).status_code == 200
    assert tick(app) == 1
    assert captured[0].size == "202x300" and captured[0].aspect_ratio == "101:150"


@pytest.mark.parametrize("choice,size,ratio", [("7:5", "1022x730", "7:5"), ("202x300", "202x300", "101:150")])
def test_custom_ratio_and_pixels_do_not_use_catalog_allowlist(client, app, choice, size, ratio):
    """列表以外的比例、明确像素尺寸都可冻结，确认前没有图片任务。"""
    login(client)
    project = create_project(client)
    plan = save_plan(client, project, mode="text", count=1, aspect_ratio=choice)
    assert plan["spec_json"]["aspect_ratio_choice"] == choice
    assert plan["spec_json"]["items"][0]["aspect_ratio"] == ratio
    assert plan["spec_json"]["items"][0]["size"] == size
    assert client.get(f"/api/v1/web/projects/{project['id']}/jobs").json() == []
