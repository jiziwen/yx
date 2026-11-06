"""聊天意图跨方式迁移、样片角色、保留约束与冻结提示词；不发付费请求。"""

from copy import deepcopy

import pytest
from sqlalchemy import func, select
from test_agent import draft, install, send, snapshot
from test_creative_flow import accept, account, login, prepare, save_plan

from app.modules.agents.context import validate_proposal
from app.modules.agents.models import AgentRun
from app.modules.agents.schemas import AgentAnswer
from app.modules.agents.transitions import SUBJECT_ONLY_NOTES, explicit_subject_only
from app.modules.executions.models import Approval, Plan
from app.modules.executions.prompts import compose
from app.modules.media_jobs.models import Job
from app.workers.agent_runtime import process_run
from app.workers.runtime import process_job


@pytest.mark.parametrize("text", ["只替换人物", "把人物替换就行了", "只换人物，其他不动", "请只更换一下主角"])
def test_direct_subject_request_is_unambiguous(text):
    """历史实际短指令有确定兜底，不把所有复杂自然语言简化为关键词。"""
    assert explicit_subject_only(text)


@pytest.mark.parametrize(
    "text", ["不要只替换人物", "只替换人物是什么意思？", "如果只替换人物呢", "换个姿势", "风格参考换第二张"]
)
def test_negation_questions_and_gallery_changes_are_not_subject_only(text):
    """否定、问句和选片不误触发模式转换。"""
    assert not explicit_subject_only(text)


def prepared_context(client, app):
    """真实授权合成参考图，选第二张风格图以发现错误默认回第一张。"""
    login(client)
    project, subjects, _ = prepare(client)
    assets = client.get(f"/api/v1/web/projects/{project['id']}/assets").json()
    reference = next(item for item in assets if item["kind"] == "reference")
    current = {
        **draft(),
        "mode": "portrait",
        "style_shot_ids": ["portrait"],
        "shot_ids": ["scene"],
        "reference_asset_ids": [reference["id"]],
        "positions": {subjects[0]["id"]: "only"},
        "mood": "更暖更柔和",
        "notes": "色调更温暖，重新设计场景",
    }
    return project, current, subjects[0]


@pytest.mark.parametrize("choice", ["9:16", "7:5", "202x300"])
def test_agent_changes_any_size_even_with_old_three_ratio_model(client, app, choice):
    """旧发布的三种画幅不再进入Agent限制，明确尺寸直接同步配置。"""
    project, current, _ = prepared_context(client, app)
    app.state.gateway.definitions["local-image"]["capabilities"]["aspect_ratios"] = ["3:4", "4:3", "1:1"]
    install(
        app,
        [
            {
                "outcome": "plan_ready",
                "reply": "已调整尺寸",
                "proposal": {"intent": "user_request", "aspect_ratio": choice},
            }
        ],
    )
    run, _ = send(client, project, f"画幅改成{choice}", draft=current)
    assert process_run(app, run["id"])
    assert snapshot(client, project)["messages"][-1]["proposal_json"]["aspect_ratio"] == choice
    with app.state.sessions() as db:
        modes = db.get(AgentRun, run["id"]).context_json["facts"]["catalog"]["modes"]
        assert modes and all(mode["arbitrary_size"] for mode in modes)
        assert db.scalar(select(func.count()).select_from(Job)) == 0


def test_real_user_phrase_promotes_selected_style_to_base_no_generation(client, app):
    """即便旧LLM只改notes或混用旧字段，实际提案也必须对齐所选第二张底图。"""
    project, current, _ = prepared_context(client, app)
    install(
        app,
        [
            {
                "outcome": "plan_ready",
                "reply": "已替换人物",
                "proposal": {
                    "intent": "user_request",
                    "notes": "替换人物，色调温暖",
                    "style_shot_ids": ["portrait"],
                },
            }
        ],
    )
    run, _ = send(client, project, "把人物替换就行了", draft=current)
    assert process_run(app, run["id"])
    patch = snapshot(client, project)["messages"][-1]["proposal_json"]
    assert patch["mode"] == "template" and patch["subject_only"] is True
    assert patch["shot_ids"] == ["portrait"] and patch["style_shot_ids"] == []
    assert patch["notes"] == SUBJECT_ONLY_NOTES and "温暖" not in patch["notes"]
    assert patch["reference_asset_ids"] is None
    with app.state.sessions() as db:
        for model in (Job,):
            assert db.scalar(select(func.count()).select_from(model)) == 0
        assert db.scalar(select(func.count()).select_from(Approval).where(Approval.status == "accepted")) == 0


def test_all_mode_switches_remain_reversible_and_do_not_choose_private_assets(client, app):
    """template→portrait→text→edit均可，下一轮不被subject_only锁住。"""
    project, current, _ = prepared_context(client, app)
    install(
        app,
        [
            {
                "outcome": "plan_ready",
                "reply": "样片作底图",
                "proposal": {"intent": "user_request", "mode": "template"},
            }
        ],
    )
    run, _ = send(client, project, "按这张样片拍同款", draft=current)
    assert process_run(app, run["id"])
    with app.state.sessions() as db:
        context = deepcopy(db.get(AgentRun, run["id"]).context_json)
    patch = snapshot(client, project)["messages"][-1]["proposal_json"]
    updated = {
        **current,
        **{key: value for key, value in patch.items() if value is not None and key != "intent"},
    }
    assert updated["subject_only"] and updated["shot_ids"] == ["portrait"]
    for target in ["portrait", "text", "edit"]:
        context["facts"]["draft"] = updated
        context["text"] = "这次调整创作方式"
        answer = AgentAnswer(
            outcome="plan_ready",
            reply="已调整",
            proposal={"intent": "user_request", "mode": target, "subject_only": False, "notes": "按新意图"},
        )
        validate_proposal(answer, context)
        updated = {**updated, **answer.proposal.model_dump(exclude_none=True, exclude={"intent"})}
        assert updated["mode"] == target and not updated["subject_only"]
        assert updated["reference_asset_ids"] == current["reference_asset_ids"]
        assert updated["base_asset_id"] is None  # edit可以未就绪，但不能擅选其他私有底图。
        if target == "portrait":
            assert updated["style_shot_ids"] == ["portrait"] and updated["shot_ids"] == []
    invalid = AgentAnswer(
        outcome="plan_ready",
        reply="伪造底图",
        proposal={"mode": "edit", "base_asset_id": "someone-elses-photo"},
    )
    with pytest.raises(ValueError, match="unchosen base"):
        validate_proposal(invalid, context)


def test_explicit_clear_and_new_style_do_not_restore_old_gallery(client, app):
    """空选择与跨套系变化不能被默认迁移重新填回。"""
    project, current, _ = prepared_context(client, app)
    install(
        app, [{"outcome": "plan_ready", "reply": "仅清空", "proposal": {"mode": "template", "shot_ids": []}}]
    )
    run, _ = send(client, project, "先切换方式，底图暂不选", draft=current)
    assert process_run(app, run["id"])
    assert snapshot(client, project)["messages"][-1]["proposal_json"]["shot_ids"] == []


def test_template_freezes_strict_prompt_roles_and_preserves_low_config(client, app):
    """保存不出图，确认后底图在前；重启/插件变动不改已批准的文本。"""
    project, current, subject = prepared_context(client, app)
    request = {
        "mode": "template",
        "subject_only": True,
        "shot_ids": ["portrait"],
        "style_shot_ids": [],
        "reference_asset_ids": current["reference_asset_ids"],
        "subject_bindings": [{"subject_id": subject["id"], "position": "only"}],
        "count": 1,
        "mood": "旧的暖色氛围",
        "notes": "旧便签：重新设计场景",
    }
    plan = save_plan(client, project, **request)
    assert (
        plan["spec_json"]["subject_only"] is True and plan["spec_json"]["prompt_version"] == "creation-v5-zh"
    )
    with app.state.sessions() as db:
        stored = db.get(Plan, plan["id"])
        item = stored.spec_json["items"][0]
        frozen = item["prompt"]
        assert [entry["role"] for entry in item["inputs"]] == ["base", "person"]
        assert item["inputs"][0]["shot_id"] == "portrait"
        assert all(
            word in frozen
            for word in [
                "站位",
                "朝向",
                "姿势",
                "构图",
                "色调",
                "不要镜像",
                "第2张图是底图中的唯一人物的参考照",
            ]
        )
        assert "设计新的写真" not in frozen and "旧" not in frozen
        assert subject["id"] not in frozen
        assert db.scalar(select(func.count()).select_from(Job)) == 0
    before = account(client, project)
    captured = []
    provider = app.state.gateway.providers["local-image"]
    original = provider.generate

    def capture(value):
        """只观察合成卡片插件，不调用远端。"""
        captured.append(value)
        return original(value)

    provider.generate = capture
    assert accept(client, plan).status_code == 200
    app.state.gateway.prompt_config = {
        "entrypoint": "does.not.exist:plugin",
        "version": "later",
        "options": {},
    }
    assert process_job(app, client.get(f"/api/v1/web/projects/{project['id']}/jobs").json()[0]["id"])
    assert len(captured) == 1 and captured[0].prompt == frozen and captured[0].operation == "edit"
    assert captured[0].input_roles == ("base", "person")
    assert account(client, project)["consumed"] == before["consumed"] + 1
    # 提示词插件不负责供应商质量档位；原302部署的low默认不被这次改动覆盖。
    assert app.state.config["providers"]["ai302-image"]["options"].get("quality", "low") == "low"


def test_other_modes_have_no_template_identity_lock():
    """自由写真、普通编辑和文生图不混用严格换人约束。"""
    for mode in ["portrait", "edit", "text"]:
        value = compose(
            {
                "mode": mode,
                "subject_only": False,
                "style_name": "测试",
                "mood": "月光",
                "notes": "蓝色",
                "change": "调光",
                "keep": [],
            },
            [],
            {},
        )
        assert "严格保留底图人物" not in value and "月光" in value and "蓝色" in value


@pytest.mark.parametrize("streaming", [False, True])
def test_whole_json_fence_is_accepted_without_second_model_request(app, monkeypatch, streaming):
    """真实供应商的整段代码围栏可以去包装，正文和权限契约仍由Agent校验。"""
    import json

    import httpx
    from test_agent_streaming import event, transport_provider

    from app.integrations.openai_compatible import CompatibleLLM

    content = '```json\n{"outcome":"answer","reply":"只整理草稿"}\n```'
    if streaming:
        provider, requests = transport_provider(
            monkeypatch, event(content) + event(finish="stop") + "data: [DONE]\n\n"
        )
        result = provider.stream_complete([], lambda _: None)
        assert result.data["reply"] == "只整理草稿" and len(requests) == 1
    else:
        monkeypatch.setenv("JSON_TEST_KEY", "synthetic")
        original, requests = httpx.Client, []

        def handle(request):
            """模拟代码块响应，不访问供应商。"""
            requests.append(json.loads(request.content))
            return httpx.Response(
                200, json={"choices": [{"message": {"content": content}, "finish_reason": "stop"}]}
            )

        monkeypatch.setattr(
            httpx, "Client", lambda **kwargs: original(transport=httpx.MockTransport(handle), **kwargs)
        )
        provider = CompatibleLLM(
            {"model": "synthetic", "base_url": "https://local.test/v1", "api_key_env": "JSON_TEST_KEY"},
            app.state.settings,
        )
        assert provider.complete([]).data["reply"] == "只整理草稿" and len(requests) == 1


@pytest.mark.parametrize(
    "content",
    [
        "说明文字\n```json\n{}\n```",
        "```json\n{}\n```\n额外文字",
        "```python\n{}\n```",
        "```json\n[]\n```",
        "```json\n{invalid}\n```",
    ],
)
def test_json_wrapper_does_not_accept_prose_or_nonobjects(content):
    """围栏兼容不等于从任意文字或可执行内容里抓取JSON。"""
    from app.integrations.openai_compatible import json_object

    with pytest.raises(ValueError):
        json_object(content)
