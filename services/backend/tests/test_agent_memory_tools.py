"""第二批 Agent：确认记忆、遗忘、只读工具、实时事实与取消/越权/迁移保护。"""

import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from test_agent import draft, install, proposal, send, snapshot
from test_creative_flow import accept, create_project, login, prepare

from app.modules.agents.models import AgentRun
from app.modules.agents.tools import EntitlementsTool
from app.modules.commerce.models import Account, EntitlementEvent
from app.modules.conversations.models import Message
from app.modules.executions.models import Plan
from app.modules.media_jobs.models import Job
from app.modules.media_jobs.service import settle
from app.modules.operations.models import Audit
from app.modules.project_memory.models import ProjectMemory
from app.workers.agent_runtime import maintain_runs, process_run


def memory(client, project):
    """拥有者读取记忆，无隐式保存。"""
    response = client.get(f"/api/v1/web/projects/{project['id']}/memory")
    assert response.status_code == 200, response.text
    return response.json()


def remember(client, project, requirements, **extra):
    """模拟用户明确确认，带当前版本和隐私代次。"""
    current = memory(client, project)
    return client.put(
        f"/api/v1/web/projects/{project['id']}/memory",
        json={
            "expected_revision": current["revision"],
            "expected_privacy_epoch": current["privacy_epoch"],
            "requirements": requirements,
            **extra,
        },
    )


def tools(*calls):
    """供应商替身请求受控工具，不调用真实模型。"""
    return {"tool_calls": [{"name": name, "arguments": arguments} for name, arguments in calls]}


def answer_with_sources(messages):
    """从本轮真实工具结果引用来源，测试不自己伪造数字。"""
    raw = next(
        m["content"].split("：", 1)[1] for m in messages if m["content"].startswith("本轮服务端只读查询结果")
    )
    return {
        "outcome": "answer",
        "reply": "请以本轮查询快照为准，图片仍需确认。",
        "tool_sources": [item["id"] for item in json.loads(raw)],
    }


def counts(app, project_id):
    """核对只读操作没有制造任何权益或媒体写入。"""
    with app.state.sessions() as db:
        account = db.scalar(select(Account).where(Account.project_id == project_id))
        return (
            account.available,
            account.reserved,
            account.consumed,
            db.scalar(select(func.count()).select_from(Job)),
            db.scalar(select(func.count()).select_from(EntitlementEvent)),
        )


def test_memory_requires_confirmation_and_survives_history_trimming(client, app):
    """提议不是记忆；明确确认后即使只保留一轮历史也持续进入上下文。"""
    login(client)
    project = create_project(client)
    provider = install(
        app,
        [
            {"outcome": "answer", "reply": "请确认这条要求", "memory_suggestion": ["不要头纱"]},
            proposal(),
            proposal(),
        ],
    )
    run, _ = send(client, project, "我不想要头纱")
    assert process_run(app, run["id"])
    assert memory(client, project)["requirements"] == []
    before = counts(app, project["id"])
    saved = remember(client, project, ["不要头纱"], source_run_id=run["id"])
    assert saved.status_code == 200 and saved.json()["revision"] == 1
    app.state.config["agent"]["history_turns"] = 1
    for text in ("现在调整光线", "再帮我整理一次"):
        next_run, _ = send(client, project, text)
        assert process_run(app, next_run["id"])
    facts = json.loads(provider.messages[-1][1]["content"].split("：", 1)[1])
    assert facts["memory"]["requirements"] == ["不要头纱"]
    assert counts(app, project["id"]) == before
    with app.state.sessions() as db:
        assert db.scalar(select(func.count()).select_from(Plan)) == 0
        audits = list(db.scalars(select(Audit).where(Audit.action == "project_memory.confirm")))
        assert len(audits) == 1 and "不要头纱" not in json.dumps(audits[0].summary)


def test_memory_clear_does_not_resurrect_older_chat(client, app):
    """移除长期要求后，旧历史不再把已忘记的文字送回模型。"""
    login(client)
    project = create_project(client)
    install(app, [{"outcome": "answer", "reply": "好的。"}])
    first, _ = send(client, project, "不要头纱", draft={**draft(), "notes": ""})
    assert process_run(app, first["id"])
    assert remember(client, project, ["不要头纱"]).status_code == 200
    assert remember(client, project, []).status_code == 200
    provider = install(app, [{"outcome": "answer", "reply": "我们继续。"}])
    new, _ = send(client, project, "继续整理", draft={**draft(), "notes": ""})
    assert process_run(app, new["id"])
    assert "不要头纱" not in str(provider.messages)
    assert memory(client, project)["revision"] == 2


def test_memory_concurrent_confirm_and_stale_send(client, app):
    """同一版本两个窗口只允许一个写入，旧记忆版本不能启动新对话。"""
    login(client)
    project = create_project(client)
    body = {"expected_revision": 0, "expected_privacy_epoch": 0, "requirements": ["保留自然肤色"]}

    def confirm(_):
        """每个请求独立数据库事务。"""
        with TestClient(app) as other:
            other.cookies.update(client.cookies)
            return other.put(f"/api/v1/web/projects/{project['id']}/memory", json=body)

    with ThreadPoolExecutor(2) as pool:
        responses = list(pool.map(confirm, range(2)))
    assert sorted(r.status_code for r in responses) == [200, 409]
    response = client.post(
        f"/api/v1/web/projects/{project['id']}/messages",
        json={
            "client_message_id": "stale-memory",
            "text": "继续",
            "expected_revision": project["brief_revision"],
            "expected_memory_revision": 0,
            "draft": draft(),
        },
    )
    assert response.json()["error"]["code"] == "MEMORY_CHANGED"


def test_memory_changed_during_model_call_discards_late_proposal(client, app):
    """确认新要求立即撤销旧上下文的提交权，不自动覆盖右侧方案。"""
    login(client)
    project = create_project(client)

    def confirm_during_call(_):
        """真实确认入口独立提交。"""
        assert remember(client, project, ["保留自然肤色"]).status_code == 200
        return proposal()

    install(app, [confirm_during_call])
    run, _ = send(client, project)
    assert not process_run(app, run["id"])
    view = snapshot(client, project)
    assert view["runs"][-1]["error_code"] == "MEMORY_CHANGED"
    assert len(view["messages"]) == 1


def test_read_tools_use_real_quota_job_states_and_safe_failure_reasons(client, app):
    """待核对保持预占，失败只解释公开分类，查询不触发结算或重发。"""
    login(client)
    project, _, plan = prepare(client)
    accepted = accept(client, plan).json()
    with app.state.sessions() as db:
        first, second = [db.get(Job, job_id) for job_id in accepted["job_ids"]]
        settle(db, first, "failed", "PROVIDER_TASK_FAILED")
        second.status, second.error_code = "reconciliation_required", "PROVIDER_RESULT_UNKNOWN"
        db.commit()
    before = counts(app, project["id"])
    provider = install(app, [tools(("get_entitlements", {}), ("get_job_status", {})), answer_with_sources])
    run, _ = send(client, project, "还有几次，生成到哪了，失败原因是什么？")
    assert process_run(app, run["id"])
    view = snapshot(client, project)
    observations = view["messages"][-1]["observations_json"]
    assert observations[0]["data"]["available"] == 7 and observations[0]["data"]["reserved"] == 1
    assert observations[1]["data"]["counts"] == {"failed": 1, "reconciliation_required": 1}
    assert any("更具体" in (job["reason"] or "") for job in observations[1]["data"]["jobs"])
    assert "upstream_task_id" not in str(observations) and all(o["observed_at"] for o in observations)
    assert counts(app, project["id"]) == before
    assert view["runs"][-1]["tool_calls"] == 2 and len(provider.messages) == 2


@pytest.mark.parametrize(
    "name,arguments,error",
    [
        ("get_entitlements", {"user_id": "other"}, "TOOL_INVALID_ARGUMENTS"),
        ("get_job_status", {"project_id": "other"}, "TOOL_INVALID_ARGUMENTS"),
        ("get_job_status", {"job_id": "missing-other-project"}, "TOOL_NOT_FOUND"),
        ("generate_image", {}, "TOOL_NOT_ALLOWED"),
    ],
)
def test_read_tools_deny_extra_scope_and_write_commands(client, app, name, arguments, error):
    """越权和写入工具只返回受控失败，身份参数不能覆盖服务器绑定。"""
    login(client)
    project = create_project(client)
    before = counts(app, project["id"])
    install(app, [tools((name, arguments)), answer_with_sources])
    run, _ = send(client, project, "查询一下，直接帮我生成")
    assert process_run(app, run["id"])
    observation = snapshot(client, project)["messages"][-1]["observations_json"][0]
    assert observation["status"] == "error" and observation["error_code"] == error
    assert counts(app, project["id"]) == before


def test_tools_database_readonly_and_pool_reset(client, app, monkeypatch):
    """插件即使误写 SQL 也被数据库拒绝，连接归还后正常业务写入仍可用。"""
    login(client)
    project = create_project(client)

    def attempted_write(self, app, db, scope, arguments):
        """刻意模拟存在写入 bug 的受信任插件。"""
        db.execute(update(Account).where(Account.project_id == scope.project_id).values(available=999))
        db.commit()
        return {"available": 999, "reserved": 0, "consumed": 0}

    monkeypatch.setattr(EntitlementsTool, "read", attempted_write)
    install(app, [tools(("get_entitlements", {})), answer_with_sources])
    run, _ = send(client, project)
    assert process_run(app, run["id"])
    assert (
        snapshot(client, project)["messages"][-1]["observations_json"][0]["error_code"] == "TOOL_UNAVAILABLE"
    )
    assert counts(app, project["id"])[0] == 0
    assert client.post(f"/api/v1/web/projects/{project['id']}/trial-grants").status_code == 200


def test_tool_loop_budget_and_repeated_query_detection(client, app):
    """相同查询只真实读取一次，错误尝试照样计入预算和来源。"""
    login(client)
    project = create_project(client)
    provider = install(
        app, [tools(("get_entitlements", {})), tools(("get_entitlements", {})), answer_with_sources]
    )
    run, _ = send(client, project)
    assert process_run(app, run["id"])
    view = snapshot(client, project)
    assert view["messages"][-1]["observations_json"][-1]["error_code"] == "TOOL_REPEAT"
    assert view["runs"][-1]["tool_calls"] == 2 and len(provider.messages) == 3
    app.state.config["agent"]["max_tool_calls"] = 1
    install(app, [tools(("get_entitlements", {}), ("get_job_status", {}))])
    limited, _ = send(client, project)
    assert not process_run(app, limited["id"])
    assert snapshot(client, project)["runs"][-1]["error_code"] == "AGENT_TOOL_BUDGET_EXCEEDED"


def test_tool_values_are_read_after_enqueue_not_frozen_as_current(client, app):
    """入队后次数变化，本轮查询拿到的是实际读取时的值。"""
    login(client)
    project = create_project(client)
    install(app, [tools(("get_entitlements", {})), answer_with_sources])
    run, _ = send(client, project)
    assert client.post(f"/api/v1/web/projects/{project['id']}/trial-grants").status_code == 200
    assert process_run(app, run["id"])
    assert snapshot(client, project)["messages"][-1]["observations_json"][0]["data"]["available"] == 8


def test_cancel_while_read_tool_waits_discards_result(client, app, monkeypatch):
    """只读查询期间取消不等待模型，迟到结果不写入助手消息。"""
    login(client)
    project = create_project(client)
    started, release = Event(), Event()
    original = EntitlementsTool.read

    def delayed(self, app, db, scope, arguments):
        """可控测试查询时机。"""
        started.set()
        assert release.wait(5)
        return original(self, app, db, scope, arguments)

    monkeypatch.setattr(EntitlementsTool, "read", delayed)
    install(app, [tools(("get_entitlements", {})), answer_with_sources])
    run, _ = send(client, project)
    with ThreadPoolExecutor(1) as pool:
        future = pool.submit(process_run, app, run["id"])
        try:
            assert started.wait(5)
            assert client.post(f"/api/v1/web/agent-runs/{run['id']}/cancel").status_code == 200
        finally:
            release.set()
        assert not future.result()
    assert len(snapshot(client, project)["messages"]) == 1


def test_memory_privacy_scope_and_physical_scrub(client, app):
    """越权不能查看/确认；撤销后记忆、建议和查询证据都立即隐藏并最终清除。"""
    login(client)
    project = create_project(client)
    subject = client.post(
        f"/api/v1/web/projects/{project['id']}/subjects",
        json={"subject_key": "person_a", "display_name": "合成主角", "declared": True},
    ).json()
    project = client.get(f"/api/v1/web/projects/{project['id']}").json()
    assert remember(client, project, ["保留自然肤色"]).status_code == 200
    install(app, [tools(("get_entitlements", {})), answer_with_sources])
    run, _ = send(client, project)
    assert process_run(app, run["id"])
    with TestClient(app) as other:
        login(other, "13800000888")
        assert other.get(f"/api/v1/web/projects/{project['id']}/memory").status_code == 404
        assert (
            other.put(
                f"/api/v1/web/projects/{project['id']}/memory",
                json={"expected_revision": 1, "expected_privacy_epoch": 0, "requirements": ["越权"]},
            ).status_code
            == 404
        )
    assert client.post(f"/api/v1/web/subjects/{subject['id']}/revoke").status_code == 200
    assert memory(client, project)["requirements"] == []
    assert snapshot(client, project)["messages"] == []
    maintain_runs(app)
    with app.state.sessions() as db:
        assert db.get(ProjectMemory, project["id"]).requirements_json == []
        assert db.get(AgentRun, run["id"]).tool_trace_json == []
        assert db.scalar(select(Message).where(Message.run_id == run["id"])).observations_json is None


def test_memory_migration_preserves_old_agent_turns(client, app):
    """新增列回填旧 Run，升级回退不删除项目或既有聊天。"""
    login(client)
    project = create_project(client)
    install(app, [proposal()])
    run, _ = send(client, project)
    assert process_run(app, run["id"])
    # 本用例只验旧业务迁移；显式丢弃隔离库中可重建的模型观测夹具。
    from sqlalchemy import delete

    from app.modules.operations.models import ModelCall

    with app.state.sessions() as db:
        db.execute(delete(ModelCall))
        db.commit()
    command.downgrade(Config("alembic.ini"), "b9ff639728f2")
    assert client.get("/ready").status_code == 503
    command.upgrade(Config("alembic.ini"), "head")
    command.check(Config("alembic.ini"))
    view = snapshot(client, project)
    assert len(view["messages"]) == 2 and view["runs"][-1]["memory_revision"] == 0
    assert view["runs"][-1]["tool_calls"] == 0 and memory(client, project)["requirements"] == []


def test_confirmed_requirements_are_kept_in_proposal_even_if_model_omits_them(client, app):
    """确认记忆作为草稿原话约束保留，模型重写不能无声丢失它。"""
    login(client)
    project = create_project(client)
    assert remember(client, project, ["不要文字水印"]).status_code == 200
    install(app, [proposal(notes="薰衣草柔光静物")])
    run, _ = send(client, project)
    assert process_run(app, run["id"])
    assert "不要文字水印" in snapshot(client, project)["messages"][-1]["proposal_json"]["notes"]


def test_read_tool_rejects_existing_job_from_another_owner(client, app):
    """真实存在的跨拥有者任务也统一不可见，不只是拒绝不存在的 ID。"""
    login(client)
    own = create_project(client)
    with TestClient(app) as other:
        login(other, "13800000777")
        _, _, plan = prepare(other)
        foreign_job = accept(other, plan).json()["job_ids"][0]
    install(app, [tools(("get_job_status", {"job_id": foreign_job})), answer_with_sources])
    run, _ = send(client, own)
    assert process_run(app, run["id"])
    fact = snapshot(client, own)["messages"][-1]["observations_json"][0]
    assert fact["error_code"] == "TOOL_NOT_FOUND" and fact["data"] is None


def test_read_tools_disabled_in_config_are_not_callable(client, app):
    """发布后的运行如果遇到工具停用，不能继续使用冻结入口绕过停用。"""
    from app.modules.agents.tools import ReadToolRegistry

    login(client)
    project = create_project(client)
    install(app, [tools(("get_entitlements", {})), answer_with_sources])
    run, _ = send(client, project)
    app.state.agent_tools = ReadToolRegistry([])
    assert process_run(app, run["id"])
    assert (
        snapshot(client, project)["messages"][-1]["observations_json"][0]["error_code"] == "TOOL_NOT_ALLOWED"
    )


def test_tool_source_validation_repairs_without_requery(client, app):
    """伪造来源被拒绝，修正最终回复不重复查询和消耗工具预算。"""
    login(client)
    project = create_project(client)
    provider = install(
        app,
        [
            tools(("get_entitlements", {})),
            {"outcome": "answer", "reply": "查询完成", "tool_sources": ["invented"]},
            answer_with_sources,
        ],
    )
    run, _ = send(client, project)
    assert process_run(app, run["id"])
    view = snapshot(client, project)
    assert len(provider.messages) == 3 and view["runs"][-1]["tool_calls"] == 1
    assert len(view["messages"][-1]["observations_json"]) == 1
