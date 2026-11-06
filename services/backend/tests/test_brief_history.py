"""结构化需求显式确认、稳定翻页、历史只读来源及遗忘/隐私/并发边界。"""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from test_agent import draft, install, proposal, send, snapshot
from test_agent_memory_tools import answer_with_sources, tools
from test_creative_flow import create_project, login

from app.core.db import now, uid
from app.modules.agents.models import AgentRun
from app.modules.agents.tools import ToolScope
from app.modules.conversations.models import Conversation, Message
from app.modules.executions.models import Approval, Plan
from app.modules.media_jobs.models import Job
from app.modules.project_memory.models import ProjectMemory
from app.modules.projects.models import Project
from app.workers.agent_runtime import maintain_runs, process_run


def memory(client, project):
    """读取当前确认值，不从历史推断。"""
    return client.get(f"/api/v1/web/projects/{project['id']}/memory").json()


def save(client, project, fields, **extra):
    """真实用户确认 API，带当前版本和授权代次。"""
    state = memory(client, project)
    return client.put(
        f"/api/v1/web/projects/{project['id']}/memory",
        json={
            "expected_revision": state["revision"],
            "expected_privacy_epoch": state["privacy_epoch"],
            "requirements": state["requirements"],
            "fields": fields,
            **extra,
        },
    )


def seed_history(app, project, turns=40, keyword="纸鸢星球"):
    """仅测试环境构造明确的历史夹具，不添加生产种子端点或伪造供应商调用。"""
    with app.state.sessions() as db:
        conversation = db.scalar(select(Conversation).where(Conversation.project_id == project["id"]))
        if not conversation:
            conversation = Conversation(project_id=project["id"])
            db.add(conversation)
            db.flush()
        for index in range(turns):
            created = now() - timedelta(days=1, seconds=turns - index)
            run = AgentRun(
                id=uid(),
                conversation_id=conversation.id,
                project_id=project["id"],
                client_message_id=uid(),
                request_hash="synthetic-fixture",
                status="succeeded",
                stage="completed",
                outcome="answer",
                brief_revision=project["brief_revision"],
                privacy_epoch=project["privacy_epoch"],
                policy_json={},
                context_json={"facts": {"draft": draft()}},
                manifest_json={},
                budget_json={},
                model="synthetic-history-fixture",
                development_sample=True,
                account_scope="fixture",
                deadline_at=created,
                created_at=created,
                finished_at=created,
            )
            db.add(run)
            db.flush()
            for role, text in (
                ("user", f"很久以前的{keyword}第{index + 1}次想法"),
                ("assistant", f"合成历史回复{index + 1}"),
            ):
                db.add(
                    Message(
                        conversation_id=conversation.id,
                        run_id=run.id,
                        seq=conversation.next_seq,
                        role=role,
                        text=text,
                        privacy_epoch=project["privacy_epoch"],
                        created_at=created,
                    )
                )
                conversation.next_seq += 1
        db.commit()


def test_brief_suggestion_requires_confirmation_and_preserves_notes(client, app):
    """建议只存消息，确认才共享记忆版本；后续提案原话保留，不改变当前草稿/图片。"""
    login(client)
    project = create_project(client)
    fields = {"scene": "薰衣草色丝绸", "lighting": "自然柔光", "avoid": "不要人物和水印"}
    provider = install(
        app, [{"outcome": "answer", "reply": "请确认需求卡", "brief_suggestion": fields}, proposal()]
    )
    run, _ = send(client, project)
    assert process_run(app, run["id"])
    assert memory(client, project)["fields"] == {}
    assert snapshot(client, project)["messages"][-1]["brief_suggestion_json"] == fields
    assert save(client, project, fields, source_run_id=run["id"]).status_code == 200
    assert memory(client, project)["revision"] == 1
    next_run, _ = send(client, project)
    assert process_run(app, next_run["id"])
    notes = snapshot(client, project)["messages"][-1]["proposal_json"]["notes"]
    assert all(value in notes for value in fields.values())
    assert "薰衣草色丝绸" in provider.messages[1][1]["content"]
    with app.state.sessions() as db:
        assert all(db.scalar(select(func.count()).select_from(model)) == 0 for model in (Plan, Approval, Job))
        assert db.get(Project, project["id"]).brief_revision == project["brief_revision"]


@pytest.mark.parametrize("fields", [{"user_id": "other"}, {"scene": "长" * 161}, {"scene": 7}])
def test_brief_fields_are_configured_and_bounded(client, fields):
    """未知、超长、非文本字段不能保存为需求，也不能写入权限。"""
    login(client)
    project = create_project(client)
    assert save(client, project, fields).status_code == 422
    assert memory(client, project)["revision"] == 0


def test_brief_configuration_and_legacy_memory_compatibility(client, app):
    """新字段由配置定义；旧文字记忆客户端省略 fields 时保留当前已确认需求。"""
    login(client)
    project = create_project(client)
    app.state.config["agent"]["brief_fields"] = [{"key": "wardrobe", "label": "服装", "max_length": 20}]
    assert save(client, project, {"wardrobe": "白色长裙"}).status_code == 200
    assert save(client, project, {"scene": "已停用"}).status_code == 422
    assert (
        client.put(
            f"/api/v1/web/projects/{project['id']}/memory",
            json={
                "expected_revision": 1,
                "expected_privacy_epoch": 0,
                "requirements": ["不要头纱"],
            },
        ).status_code
        == 200
    )
    assert memory(client, project)["fields"] == {"wardrobe": "白色长裙"}
    app.state.config["agent"]["brief_fields"] = []
    assert memory(client, project)["fields"] == {} and memory(client, project)["field_definitions"] == []


def test_brief_model_cannot_suggest_unconfigured_fields(client, app):
    """结构化输出校验和修正仍不能把未配置字段作为可确认建议发布。"""
    login(client)
    project = create_project(client)
    invalid = {"outcome": "answer", "reply": "不应发布", "brief_suggestion": {"execute_image": "yes"}}
    install(app, [invalid, invalid])
    run, _ = send(client, project)
    assert not process_run(app, run["id"])
    view = snapshot(client, project)
    assert view["runs"][-1]["error_code"] == "AGENT_INVALID_OUTPUT"
    assert not [item for item in view["messages"] if item["role"] == "assistant"]


def test_brief_configuration_change_stops_frozen_run(client, app):
    """排队后部署字段变化需要重新确认上下文，旧冻结配置不能继续出建议。"""
    login(client)
    project = create_project(client)
    provider = install(app, [proposal()])
    run, _ = send(client, project)
    app.state.config["agent"]["brief_fields"] = []
    assert not process_run(app, run["id"])
    assert snapshot(client, project)["runs"][-1]["error_code"] == "MEMORY_CONFIG_CHANGED"
    assert not provider.messages


def test_brief_concurrent_confirm_and_running_change(client, app):
    """同一版本只有一次编辑成功；进行中的回复不能绕过后来的需求确认。"""
    login(client)
    project = create_project(client)
    path = f"/api/v1/web/projects/{project['id']}/memory"

    def confirm(value):
        return client.put(
            path,
            json={
                "expected_revision": 0,
                "expected_privacy_epoch": 0,
                "requirements": [],
                "fields": {"scene": value},
            },
        ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(confirm, ["海边", "花园"])) == [200, 409]

    def changed(_messages):
        assert save(client, project, {"scene": "雪山"}).status_code == 200
        return proposal()

    install(app, [changed])
    run, _ = send(client, project)
    assert not process_run(app, run["id"])
    assert snapshot(client, project)["runs"][-1]["error_code"] == "MEMORY_CHANGED"
    assert not [item for item in snapshot(client, project)["messages"] if item["role"] == "assistant"]


def test_history_paging_is_stable_under_new_messages_and_is_scoped(client, app):
    """超过60条仍能无重复到达开头；新消息、坏游标、跨项目/用户/隐私代次均有边界。"""
    login(client)
    project = create_project(client)
    seed_history(app, project)
    view = snapshot(client, project)
    assert len(view["messages"]) == 60 and view["messages"][0]["seq"] == 21
    cursor, seqs = view["older_cursor"], [item["seq"] for item in view["messages"]]
    path = f"/api/v1/web/projects/{project['id']}/conversation/history"
    first = client.get(path, params={"cursor": cursor, "limit": 7}).json()
    assert [item["seq"] for item in first["items"]] == list(range(14, 21))
    install(app, [proposal()])
    run, _ = send(client, project)
    assert process_run(app, run["id"])
    while cursor:
        page = client.get(path, params={"cursor": cursor, "limit": 7}).json()
        seqs.extend(item["seq"] for item in page["items"])
        assert {m["run_id"] for m in page["items"]}.issubset({r["id"] for r in page["runs"]})
        cursor = page["next_cursor"]
    assert len(seqs) == len(set(seqs)) == 80 and sorted(seqs) == list(range(1, 81))
    assert client.get(path, params={"limit": 101}).status_code == 422
    assert client.get(path, params={"cursor": "tampered"}).status_code == 409
    other_project = create_project(client)
    assert (
        client.get(
            f"/api/v1/web/projects/{other_project['id']}/conversation/history",
            params={"cursor": view["older_cursor"]},
        ).status_code
        == 409
    )
    with TestClient(app) as other:
        login(other, "13900000912")
        assert other.get(path).status_code == 404
    with app.state.sessions() as db:
        db.get(Project, project["id"]).privacy_epoch += 1
        db.commit()
    assert client.get(path, params={"cursor": view["older_cursor"]}).status_code == 409
    assert client.get(path).json()["items"] == []


def test_history_tool_respects_forgetting_and_returns_real_sources(client, app):
    """需求删除后，旧原话仍供用户翻阅，但最近上下文与工具均不能将它重新取回。"""
    user = login(client)
    project = create_project(client)
    seed_history(app, project, turns=4)
    scope = ToolScope(user["id"], project["id"], 0)
    facts = app.state.agent_tools.read(app, scope, "search_project_history", {"query": "纸鸢星球"})
    assert len(facts["messages"]) == 3 and facts["more_available"]
    assert all(message["message_id"] and message["seq"] for message in facts["messages"])
    assert save(client, project, {"scene": "纸鸢星球"}).status_code == 200
    assert save(client, project, {}).status_code == 200
    assert (
        app.state.agent_tools.read(app, scope, "search_project_history", {"query": "纸鸢星球"})["messages"]
        == []
    )
    assert any(
        "纸鸢星球" in item["text"]
        for item in client.get(f"/api/v1/web/projects/{project['id']}/conversation/history").json()["items"]
    )
    provider = install(app, [tools(("search_project_history", {"query": "纸鸢星球"})), answer_with_sources])
    run, _ = send(client, project, text="请按关键词查找过去的想法")
    assert process_run(app, run["id"])
    assert not any("纸鸢星球" in item["content"] for item in provider.messages[0] if item["role"] != "system")
    result = snapshot(client, project)["messages"][-1]["observations_json"][0]
    assert result["data"]["messages"] == [] and result["data"]["history_cutoff_at"]


def test_history_tool_literals_failure_states_and_project_scope(client, app):
    """通配符按字面读取，失败轮次和其他项目不能进入模型历史查询。"""
    user = login(client)
    project = create_project(client)
    seed_history(app, project, turns=1, keyword="100% 保留")
    other = create_project(client)
    seed_history(app, other, turns=1, keyword="秘密场景")
    scope = ToolScope(user["id"], project["id"], 0)
    assert (
        len(app.state.agent_tools.read(app, scope, "search_project_history", {"query": "%"})["messages"]) == 1
    )
    assert not app.state.agent_tools.read(app, scope, "search_project_history", {"query": "秘密场景"})[
        "messages"
    ]
    with app.state.sessions() as db:
        row = db.scalar(select(AgentRun).where(AgentRun.project_id == project["id"]))
        row.status = "failed"
        db.commit()
    assert not app.state.agent_tools.read(app, scope, "search_project_history", {"query": "%"})["messages"]


def test_brief_privacy_cleanup_and_migration_roundtrip(client, app):
    """新字段随隐私清理；迁移往返保留旧记忆和正式消息，字段回填为空。"""
    login(client)
    project = create_project(client)
    assert save(client, project, {"scene": "海边"}).status_code == 200
    install(app, [{"outcome": "answer", "reply": "请确认", "brief_suggestion": {"lighting": "柔光"}}])
    run, _ = send(client, project)
    assert process_run(app, run["id"])
    # 本用例只验旧业务迁移；显式丢弃隔离库中可重建的模型观测夹具。
    from sqlalchemy import delete

    from app.modules.operations.models import ModelCall

    with app.state.sessions() as db:
        db.execute(delete(ModelCall))
        db.commit()
    command.downgrade(Config("alembic.ini"), "a38f94cce1d2")
    command.upgrade(Config("alembic.ini"), "head")
    command.check(Config("alembic.ini"))
    assert memory(client, project)["fields"] == {}
    assert len(snapshot(client, project)["messages"]) == 2
    assert save(client, project, {"scene": "花园"}).status_code == 200
    with app.state.sessions() as db:
        db.get(Project, project["id"]).privacy_epoch += 1
        db.commit()
    assert memory(client, project)["fields"] == {}
    maintain_runs(app)
    with app.state.sessions() as db:
        assert db.get(ProjectMemory, project["id"]).fields_json == {}
        assert all(
            message.brief_suggestion_json is None
            for message in db.scalars(select(Message).where(Message.run_id == run["id"]))
        )
