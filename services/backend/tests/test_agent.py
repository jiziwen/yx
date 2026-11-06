"""Agent 合约：持久化、隔离上下文、取消和确认边界；不调用真实模型。"""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from test_creative_flow import create_project, login

from app.core.db import now
from app.integrations.contracts import ProviderFailure
from app.modules.agents.models import AgentRun
from app.modules.conversations.models import Message
from app.modules.executions.models import Approval, Plan
from app.modules.media_jobs.models import Job
from app.workers.agent_runtime import maintain_runs, process_run


class ScriptedLLM:
    """显式供应商替身，记录上下文并消费指定响应。"""

    def __init__(self, outputs):
        """每次调用消费一条测试响应。"""
        self.outputs, self.messages = list(outputs), []

    def draft(self, messages):
        """可模拟网络失败与等待，不包含真实密钥。"""
        self.messages.append(messages)
        result = self.outputs.pop(0)
        if isinstance(result, Exception):
            raise result
        return result(messages) if callable(result) else result


def draft():
    """和正式表单相同的合成草稿。"""
    return {
        "mode": "text",
        "subject_only": False,
        "style_id": "portrait_portrait_01",
        "aspect_ratio": "3:4",
        "count": 1,
        "variants": 1,
        "mood": "柔光",
        "notes": "不要头纱",
        "change": "",
        "keep": [],
        "reference_asset_ids": [],
        "base_asset_id": None,
        "shot_ids": [],
        "style_shot_ids": [],
        "style_asset_ids": [],
        "positions": {},
    }


def proposal(**patch):
    """可见字段建议，不包含执行。"""
    return {
        "outcome": "plan_ready",
        "reply": "先一起看草稿，确认后才会生成。",
        "questions": [],
        "proposal": {"notes": "不要头纱；薰衣草色柔光", **patch},
    }


def install(app, outputs):
    """只替换隔离应用的开发插件。"""
    provider = ScriptedLLM(outputs)
    app.state.gateway.providers["local-llm"] = provider
    return provider


def send(client, project, text="想拍一张照片", **changes):
    """发送仅排队，不创建图片。"""
    body = {
        "client_message_id": str(uuid4()),
        "text": text,
        "expected_revision": project["brief_revision"],
        "draft": draft(),
        **changes,
    }
    response = client.post(f"/api/v1/web/projects/{project['id']}/messages", json=body)
    assert response.status_code == 202, response.text
    return response.json(), body


def snapshot(client, project):
    """刷新读取提交后的事实，不调用模型。"""
    response = client.get(f"/api/v1/web/projects/{project['id']}/conversation")
    assert response.status_code == 200, response.text
    return response.json()


def test_agent_clarify_history_proposal_no_execution(client, app):
    """两轮追问→提案；文字要求立即生成也没有任务、方案或审批副作用。"""
    login(client)
    project = create_project(client)
    provider = install(
        app,
        [
            {
                "outcome": "needs_input",
                "reply": "一起想清楚画面。",
                "questions": ["想要棚拍还是户外？"],
                "proposal": None,
            },
            proposal(count=2),
        ],
    )
    first, body = send(client, project)
    duplicate = client.post(f"/api/v1/web/projects/{project['id']}/messages", json=body)
    assert duplicate.json()["id"] == first["id"]
    assert process_run(app, first["id"])
    second, _ = send(client, project, "户外，薰衣草色，立即生成2张并扣次数")
    assert process_run(app, second["id"])
    assert not process_run(app, second["id"])
    assert len(provider.messages) == 2
    assert any("棚拍还是户外" in m["content"] for m in provider.messages[1])
    assert "不要头纱" in provider.messages[1][1]["content"]
    assert "storage_key" not in str(provider.messages)
    view = snapshot(client, project)
    assert len(view["messages"]) == 4 and view["messages"][-1]["proposal_json"]["count"] == 2
    assert view["runs"][-1]["calls"] == 1 and view["runs"][-1]["draft_context"] == draft()
    with app.state.sessions() as db:
        for model in (Plan, Approval, Job):
            assert db.scalar(select(func.count()).select_from(model)) == 0


@pytest.mark.parametrize(
    "bad",
    [
        proposal(count=9),
        proposal(style_id="another-project"),
        proposal(provider_id="evil"),
        {"outcome": "plan_ready", "reply": "已生成", "execute": True},
    ],
)
def test_agent_rejects_invalid_output_and_repairs_once(client, app, bad):
    """越权字段、套系和超限被拒绝，最多一次契约修正。"""
    login(client)
    project = create_project(client)
    provider = install(app, [bad, proposal()])
    run, _ = send(client, project)
    assert process_run(app, run["id"])
    assert len(provider.messages) == 2
    assert snapshot(client, project)["runs"][-1]["calls"] == 2


@pytest.mark.parametrize(
    "failure,code,calls",
    [
        (ProviderFailure("PROVIDER_RESULT_UNKNOWN", unknown=True), "PROVIDER_RESULT_UNKNOWN", 1),
        (ProviderFailure("PROVIDER_AUTH_FAILED"), "PROVIDER_AUTH_FAILED", 1),
        ({"wrong": True}, "AGENT_INVALID_OUTPUT", 2),
    ],
)
def test_agent_failure_no_fake_reply_or_automatic_retry(client, app, failure, code, calls):
    """失败保留输入，不把固定文案伪装为模型成功回复。"""
    login(client)
    project = create_project(client)
    provider = install(app, [failure, failure])
    run, _ = send(client, project)
    assert not process_run(app, run["id"])
    view = snapshot(client, project)
    assert view["runs"][-1]["error_code"] == code and len(view["messages"]) == 1
    assert len(provider.messages) == calls and not process_run(app, run["id"])


def test_agent_concurrent_idempotency_and_serial_admission(client, app):
    """并发重发同消息只入队一次；不同消息不能抢同一会话。"""
    login(client)
    project = create_project(client)
    provider = install(app, [proposal()])
    body = {
        "client_message_id": str(uuid4()),
        "text": "户外柔光",
        "expected_revision": project["brief_revision"],
        "draft": draft(),
    }

    def submit(_):
        """独立请求连接竞争。"""
        with TestClient(app) as other:
            other.cookies.update(client.cookies)
            return other.post(f"/api/v1/web/projects/{project['id']}/messages", json=body)

    with ThreadPoolExecutor(2) as pool:
        responses = list(pool.map(submit, range(2)))
    assert all(r.status_code == 202 for r in responses)
    run_id = responses[0].json()["id"]
    assert run_id == responses[1].json()["id"]
    assert (
        client.post(
            f"/api/v1/web/projects/{project['id']}/messages", json={**body, "text": "different"}
        ).status_code
        == 409
    )
    assert (
        client.post(
            f"/api/v1/web/projects/{project['id']}/messages", json={**body, "client_message_id": str(uuid4())}
        ).json()["error"]["code"]
        == "AGENT_BUSY"
    )
    with ThreadPoolExecutor(2) as pool:
        list(pool.map(lambda _: process_run(app, run_id), range(2)))
    assert len(provider.messages) == 1


def test_agent_cancel_inflight_does_not_publish_late_reply(client, app):
    """网络期间无数据库长事务；取消后迟到回复不能提交。"""
    login(client)
    project = create_project(client)
    started, release = Event(), Event()

    def delayed(_):
        """控制回包顺序。"""
        started.set()
        assert release.wait(5)
        return proposal()

    install(app, [delayed])
    run, _ = send(client, project)
    with ThreadPoolExecutor(1) as pool:
        future = pool.submit(process_run, app, run["id"])
        try:
            assert started.wait(5)
            assert client.post(f"/api/v1/web/agent-runs/{run['id']}/cancel").json()["status"] == "cancelled"
        finally:
            release.set()
        assert not future.result()
    assert len(snapshot(client, project)["messages"]) == 1


def test_agent_revision_and_privacy_barrier(client, app):
    """撤销立即隐藏历史；最终提交与后续上下文都不能复用旧来源。"""
    login(client)
    project = create_project(client)
    subject = client.post(
        f"/api/v1/web/projects/{project['id']}/subjects",
        json={"subject_key": "person_a", "display_name": "合成主角", "declared": True},
    ).json()
    project = client.get(f"/api/v1/web/projects/{project['id']}").json()

    def revoke(_):
        """真实撤销请求与 Worker 分离。"""
        assert client.post(f"/api/v1/web/subjects/{subject['id']}/revoke").status_code == 200
        return proposal()

    provider = install(app, [revoke, proposal()])
    run, _ = send(client, project, "旧的私密要求")
    assert not process_run(app, run["id"])
    assert snapshot(client, project)["messages"] == []
    assert client.get(f"/api/v1/web/agent-runs/{run['id']}").status_code == 404
    maintain_runs(app)
    with app.state.sessions() as db:
        assert db.get(AgentRun, run["id"]).context_json == {}
        assert db.scalar(select(Message).where(Message.run_id == run["id"])).text == "[授权变化后已清除]"
    project = client.get(f"/api/v1/web/projects/{project['id']}").json()
    new, _ = send(client, project, "新的构想")
    assert process_run(app, new["id"])
    assert "旧的私密要求" not in str(provider.messages[-1])


def test_agent_scope_and_stale_revision(client, app):
    """越权对象与旧版本在进入模型前被拒绝。"""
    login(client)
    project = create_project(client)
    provider = install(app, [proposal()])
    invalid = {
        "client_message_id": str(uuid4()),
        "text": "测试",
        "expected_revision": project["brief_revision"],
        "draft": {**draft(), "base_asset_id": str(uuid4())},
    }
    assert client.post(f"/api/v1/web/projects/{project['id']}/messages", json=invalid).status_code == 404
    invalid["draft"] = draft()
    invalid["expected_revision"] += 1
    assert client.post(f"/api/v1/web/projects/{project['id']}/messages", json=invalid).status_code == 409
    run, _ = send(client, project)
    with TestClient(app) as other:
        login(other, "13800000999")
        assert other.get(f"/api/v1/web/projects/{project['id']}/conversation").status_code == 404
        assert other.get(f"/api/v1/web/agent-runs/{run['id']}").status_code == 404
        assert other.post(f"/api/v1/web/agent-runs/{run['id']}/cancel").status_code == 404
    assert not provider.messages


def test_agent_expired_lease_never_replays_paid_call(client, app):
    """中断超时失败，预算不清零，不重放已开始的模型调用。"""
    login(client)
    project = create_project(client)
    provider = install(app, [proposal()])
    run, _ = send(client, project)
    with app.state.sessions() as db:
        current = db.get(AgentRun, run["id"])
        current.status, current.calls, current.deadline_at = "running", 1, now() - timedelta(seconds=1)
        db.commit()
    maintain_runs(app)
    assert not process_run(app, run["id"])
    view = snapshot(client, project)
    assert view["runs"][-1]["error_code"] == "AGENT_TIMEOUT" and view["runs"][-1]["calls"] == 1
    assert not provider.messages


def test_agent_uses_frozen_llm_and_next_turn_uses_new_release(client, app, monkeypatch):
    """换后台模型后排队轮次仍用旧版本，新轮次用新版，跨 Worker 实例生效。"""
    from test_model_settings import admin, approved_publish, body

    from app.integrations.contracts import LLMResult
    from app.integrations.openai_compatible import CompatibleLLM
    from app.main import create_app

    monkeypatch.setenv("AI302_API_KEY", "synthetic-agent-key")
    # 本场景单独验证完整响应兼容，流式适配有独立的传输和调用预算测试。
    app.state.config["agent"]["streaming_enabled"] = False
    worker = create_app(app.state.settings, engine=app.state.engine)
    seen = []

    def complete(provider, messages, timeout_seconds=None):
        """显式替身覆盖真实 HTTP，不读取本地真实凭证。"""
        seen.append(provider.model)
        return LLMResult(proposal(), {"prompt_tokens": 20, "completion_tokens": 30, "total_tokens": 50})

    monkeypatch.setattr(CompatibleLLM, "complete", complete)
    admin(client)
    settings = body(client)
    settings["llm"].update(enabled=True, model="synthetic-model-a")
    assert approved_publish(client, settings).status_code == 200
    login(client)
    project = create_project(client)
    run, _ = send(client, project)
    settings = body(client)
    settings["llm"].update(model="synthetic-model-b")
    assert approved_publish(client, settings).status_code == 200
    assert process_run(worker, run["id"])
    assert seen == ["synthetic-model-a"]
    assert snapshot(client, project)["model"] == "synthetic-model-b"
    next_run, _ = send(client, project, "继续整理")
    assert process_run(worker, next_run["id"])
    assert seen == ["synthetic-model-a", "synthetic-model-b"]
    with app.state.sessions() as db:
        assert db.get(AgentRun, run["id"]).usage_json["total_tokens"] == 50


def test_agent_context_budget_preserves_current_input_or_rejects(client, app):
    """必要输入超限时明确拒绝，不截断当前要求，也不花模型调用。"""
    login(client)
    project = create_project(client)
    provider = install(app, [proposal()])
    app.state.config["agent"]["max_context_chars"] = 3000
    body = {
        "client_message_id": str(uuid4()),
        "text": "当前要求" * 240,
        "expected_revision": project["brief_revision"],
        "draft": {**draft(), "notes": "保留条件" * 240},
    }
    result = client.post(f"/api/v1/web/projects/{project['id']}/messages", json=body)
    assert result.status_code == 422 and result.json()["error"]["code"] == "AGENT_CONTEXT_LIMIT"
    assert snapshot(client, project)["messages"] == [] and not provider.messages


@pytest.mark.parametrize("mode", ["template", "portrait", "edit", "text"])
def test_agent_four_mode_drafts_keep_material_selection_manual(client, app, mode):
    """四种方式都可建议表单，缺少素材仍由右侧准备和正式保存校验。"""
    login(client)
    project = create_project(client)
    install(app, [proposal(mode=mode)])
    run, _ = send(client, project, "先整理这个方式的草稿，我稍后手动补素材")
    assert process_run(app, run["id"])
    view = snapshot(client, project)
    assert view["messages"][-1]["proposal_json"]["mode"] == mode
    assert client.get(f"/api/v1/web/projects/{project['id']}/plans").json() == []
