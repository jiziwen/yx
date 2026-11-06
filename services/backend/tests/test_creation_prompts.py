"""生图提示词边界：实际中文HTTP正文、图片位置、画面限制和冻结规则升级。"""

import json
import re

import httpx
from sqlalchemy import select
from test_creative_flow import accept, create_project, login, save_plan

from app.integrations.ai302_gpt import AI302GPTImage
from app.modules.executions.models import Plan
from app.modules.executions.prompts import compose, prompt_policy_hash, visual_requirements
from app.modules.operations.models import ModelCall
from app.workers.runtime import process_job


def test_text_worker_sends_only_chinese_picture_requirements_on_actual_wire(client, app, monkeypatch):
    """复现用户截图；真实Worker→适配器→HTTP及后台日志一致，不发送应用路由说明。"""
    login(client)
    project = create_project(client)
    client.post(f"/api/v1/web/projects/{project['id']}/trial-grants")
    notes = (
        "纯文字生成一张大海画面，画面中央有一位美女，人物不使用已上传的人物参考照片，"
        "大海场景与光线氛围自由发挥。"
    )
    plan = save_plan(client, project, mode="text", count=1, notes=notes, mood="海面自然光")
    with app.state.sessions() as db:
        frozen = db.get(Plan, plan["id"]).spec_json["items"][0]["prompt"]
    assert "大海画面，画面中央有一位美女" in frozen
    assert "光线氛围自由发挥" in frozen and "海面自然光" in frozen
    assert all(value not in frozen for value in ["已上传", "纯文字生成", "雾光艺廊", "[]"])
    assert not re.search(r"[A-Za-z]", frozen)
    assert accept(client, plan).status_code == 200
    monkeypatch.setenv("AI302_API_KEY", "synthetic-key")
    transport_client = httpx.Client
    wire = []

    def handler(request):
        """只接受合成提交，禁止下载或调用真实供应商。"""
        assert request.url.path == "/v1/images/generations"
        wire.append(json.loads(request.content))
        return httpx.Response(200, json={"task_id": "chinese-prompt-test"})

    monkeypatch.setattr(
        httpx, "Client", lambda **kw: transport_client(transport=httpx.MockTransport(handler), **kw)
    )
    app.state.gateway.providers["local-image"] = AI302GPTImage(
        {"models": {"text": "test-image"}}, app.state.settings
    )
    job = client.get(f"/api/v1/web/projects/{project['id']}/jobs").json()[0]
    assert process_job(app, job["id"])
    assert len(wire) == 1 and wire[0]["prompt"] == frozen
    with app.state.sessions() as db:
        row = db.scalar(select(ModelCall).where(ModelCall.job_id == job["id"]))
        assert row.request_json["json"] == wire[0]


def test_image_order_maps_people_without_internal_identifiers():
    """同一人物多张参考仍对应同一侧，风格图不变成人物或底图。"""
    inputs = [
        {"role": "base", "asset_id": "private-base"},
        {"role": "person", "subject_id": "private-person-a"},
        {"role": "person", "subject_id": "private-person-b"},
        {"role": "person", "subject_id": "private-person-a"},
    ]
    prompt = compose(
        {
            "mode": "template",
            "subject_only": True,
            "subject_bindings": [
                {"subject_id": "private-person-a", "position": "left"},
                {"subject_id": "private-person-b", "position": "right"},
            ],
        },
        inputs,
        {},
    )
    assert "第1张图是底图" in prompt
    assert "第2张图是底图中的左侧人物的参考照" in prompt
    assert "第3张图是底图中的右侧人物的参考照" in prompt
    assert "第4张图是底图中的左侧人物的参考照" in prompt
    assert "private-" not in prompt and not re.search(r"[A-Za-z]", prompt)
    portrait = compose(
        {"mode": "portrait", "notes": "海边写真", "mood": "冷色自然光"},
        [inputs[1], {"role": "style", "asset_id": "private-style"}],
        {},
    )
    assert "第1张图是人物1的参考照" in portrait
    assert "第2张图是风格参考" in portrait and "不复制人物身份与构图" in portrait
    assert "private-" not in portrait


def test_picture_negatives_and_requested_foreign_text_remain_intact():
    """不靠删除英文或所有否定句清理提示词，避免破坏用户要求的文字和画面禁用项。"""
    notes = "海报标题写“SEA”，不要文字水印，不使用参考图的服装，不要阴天。"
    assert visual_requirements(notes, "text") == notes.rstrip("。")
    assert visual_requirements("不使用参考图", "edit") == "不使用参考图"
    prompt = compose({"mode": "text", "notes": notes, "mood": ""}, [], {})
    assert "“SEA”" in prompt and "不要文字水印" in prompt
    assert "不使用参考图的服装" in prompt and "不要阴天" in prompt
    assert "Create" not in prompt and "Input roles" not in prompt


def test_unconfirmed_old_prompt_is_rebuilt_but_cannot_be_accepted(client, app):
    """规则更新不会消耗旧卡次数，也不会悄悄改旧卡；新卡绑定新规则。"""
    login(client)
    project = create_project(client)
    client.post(f"/api/v1/web/projects/{project['id']}/trial-grants")
    old = save_plan(client, project, mode="text", count=1, notes="大海画面")
    with app.state.sessions() as db:
        old_prompt = db.get(Plan, old["id"]).spec_json["items"][0]["prompt"]
    app.state.gateway.prompt_config = {**app.state.gateway.prompt_config, "version": "next-zh"}
    assert accept(client, old).json()["error"]["code"] == "PLAN_STALE"
    assert client.get(f"/api/v1/web/projects/{project['id']}/jobs").json() == []
    fresh = save_plan(client, project, mode="text", count=1, notes="大海画面")
    expected = prompt_policy_hash(app.state.gateway.prompt_config)
    assert fresh["spec_json"]["prompt_policy_hash"] == expected
    assert client.get("/api/v1/web/catalog").json()["creation_prompt_policy_hash"] == expected
    assert accept(client, fresh).status_code == 200
    with app.state.sessions() as db:
        assert db.get(Plan, old["id"]).spec_json["items"][0]["prompt"] == old_prompt
