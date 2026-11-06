"""完整M2的知识发布/RAG、角色隔离、人工交接、步骤与Release门禁；零付费替身。"""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from test_agent import install, proposal, send
from test_agent_memory_tools import tools
from test_creative_flow import create_project, login

from app.core.db import now
from app.integrations.contracts import ProviderFailure
from app.modules.agents.models import AgentRun
from app.modules.conversations.models import Conversation, Message
from app.modules.executions.models import Approval, Plan
from app.modules.knowledge.models import KnowledgeChunk, KnowledgeIndexJob, KnowledgeVersion
from app.modules.knowledge.service import embedder, search, spec
from app.modules.knowledge.worker import pending
from app.modules.knowledge.worker import process as index
from app.modules.media_jobs.models import Job
from app.workers.agent_runtime import maintain_runs, process_run

KNOW = "/api/v1/admin/knowledge/documents"
SUP = "/api/v1/web/conversations"


def admin(client, app):
    """显式开发管理员，测试从隔离设置读取，不读取真实密钥。"""
    response = client.post(
        "/api/v1/admin/auth/login", json={"username": "admin", "password": app.state.settings.admin_password}
    )
    assert response.status_code == 200, response.text
    return response.json()


def knowledge(
    client, app, text="参考照要求：请使用清晰、自然光、无遮挡的正面照片。不要使用严重滤镜。", publish=True
):
    """同真实API导入→Worker索引→显式管理员发布，无内置假发布内容。"""
    admin(client, app)
    app.state.settings.knowledge_development_embedding = True
    doc = client.post(KNOW).json()
    response = client.post(
        f"{KNOW}/{doc['id']}/versions",
        json={
            "expected_revision": 0,
            "request_key": str(uuid4()),
            "title": "参考照准备指南",
            "summary": "拍摄准备",
            "category": "photography",
            "text": text,
        },
    )
    assert response.status_code == 202, response.text
    version = response.json()
    assert index(app, pending(app)[-1])
    if publish:
        response = client.post(
            f"{KNOW}/{doc['id']}/publish", json={"expected_revision": 1, "version_id": version["id"]}
        )
        assert response.status_code == 200, response.text
        doc = response.json()
    return doc, version


def open_chat(client, project_id=None):
    """没有项目也能问公开规则，打开不调用模型。"""
    response = client.post(SUP, json={"project_id": project_id})
    assert response.status_code == 200, response.text
    return response.json()


def support_send(client, view, text="请帮我说明使用规则", **changes):
    """显式版本和隐私代次，重试保留客户端消息键。"""
    body = {
        "client_message_id": str(uuid4()),
        "text": text,
        "expected_revision": view["revision"],
        "expected_privacy_epoch": view["privacy_epoch"],
        **changes,
    }
    response = client.post(f"{SUP}/{view['id']}/messages", json=body)
    assert response.status_code == 202, response.text
    return response.json(), body


def citations_answer(messages):
    """只引用工具实际返回的第一块，标题/正文由后端生成。"""
    observations = json.loads(
        next(
            m["content"].split("：", 1)[1]
            for m in messages
            if m["content"].startswith("本轮服务端只读查询结果")
        )
    )
    evidence = [e for obs in observations for e in (obs.get("data") or {}).get("evidence", [])]
    return {
        "outcome": "answer",
        "reply": (
            "请使用清晰自然光的正面参考照。[1]" if evidence else "尚未找到已发布证据，可请求人工客服。"
        ),
        "tool_sources": [obs["id"] for obs in observations],
        "citations": [evidence[0]["chunk_id"]] if evidence else [],
    }


def test_knowledge_publish_search_citation_and_revocation(client, app):
    """草稿不可查，发布后有真实引用，下架后检索和旧引用都立即失效。"""
    doc, version = knowledge(client, app, publish=False)
    assert client.get("/api/v1/web/guides").json() == []
    with app.state.sessions() as db:
        vector = embedder(app).embed(["参考照要求"])[0][0]
        assert search(app, db, "参考照要求", vector, spec(app))["evidence"] == []
    assert (
        client.post(
            f"{KNOW}/{doc['id']}/publish", json={"expected_revision": 1, "version_id": version["id"]}
        ).status_code
        == 200
    )
    assert client.get("/api/v1/web/guides").json()[0]["version_id"] == version["id"]
    login(client)
    view = open_chat(client)
    install(app, [tools(("search_knowledge", {"query": "参考照要求"})), citations_answer])
    result, _ = support_send(client, view, "参考照有什么要求？")
    assert process_run(app, result["runs"][-1]["id"])
    final = client.get(f"{SUP}/{view['id']}").json()
    message = final["messages"][-1]
    assert message["citations_json"][0]["version_id"] == version["id"]
    path = f"/api/v1/web/messages/{message['id']}/citations/1"
    assert client.get(path).json()["text"].startswith("参考照要求")
    assert client.get(path.replace("/1", "/99")).status_code == 404
    with TestClient(app) as other:
        login(other, "13900000331")
        assert other.get(path).status_code == 404
    assert (
        client.post(
            f"{KNOW}/{doc['id']}/unpublish", json={"expected_revision": 2, "version_id": version["id"]}
        ).status_code
        == 200
    )
    assert client.get(path).status_code == 410
    assert client.get("/api/v1/web/guides").json() == []
    with app.state.sessions() as db:
        assert search(app, db, "参考照")["evidence"] == []


def test_knowledge_import_idempotency_stale_and_failure_preserves_old(client, app):
    """索引失败/陈旧发布不影响旧版本；重复请求不产生第二个embedding任务。"""
    doc, version = knowledge(client, app)
    body = {
        "expected_revision": 2,
        "request_key": "new-v2",
        "title": "新草稿标题",
        "text": "新版本参考照使用要求。",
    }
    first = client.post(f"{KNOW}/{doc['id']}/versions", json=body)
    assert first.status_code == 202
    assert client.post(f"{KNOW}/{doc['id']}/versions", json=body).json()["id"] == first.json()["id"]
    assert client.post(f"{KNOW}/{doc['id']}/versions", json={**body, "text": "不同原文"}).status_code == 409
    assert (
        client.post(
            f"{KNOW}/{doc['id']}/publish", json={"expected_revision": 2, "version_id": first.json()["id"]}
        ).status_code
        == 409
    )
    # 固定空间变化使索引失败，绝不静默混用。
    app.state.config["knowledge"]["embedding_options"]["model"] = "different-space"
    assert not index(app, pending(app)[-1])
    assert client.get("/api/v1/web/guides").json()[0]["version_id"] == version["id"]
    assert client.get(f"{KNOW}/{doc['id']}/versions").json()[0]["status"] == "failed"
    assert (
        client.post(
            f"{KNOW}/{doc['id']}/publish", json={"expected_revision": 3, "version_id": first.json()["id"]}
        ).status_code
        == 409
    )


def test_knowledge_fake_citation_and_late_unpublish_cannot_commit(client, app):
    """伪造引用需格式修正；模型等待时下架的证据也不能发布。"""
    doc, version = knowledge(client, app)
    login(client)
    view = open_chat(client)
    install(
        app,
        [
            {"outcome": "answer", "reply": "虚构规则[1]", "citations": ["fake-chunk"]},
            {"outcome": "answer", "reply": "虚构规则[1]", "citations": ["fake-chunk"]},
        ],
    )
    result, _ = support_send(client, view)
    assert not process_run(app, result["runs"][-1]["id"])
    assert client.get(f"{SUP}/{view['id']}").json()["runs"][-1]["error_code"] == "AGENT_INVALID_OUTPUT"

    def late(messages):
        """调用期间下架，最终重新锁发布指针复核。"""
        answer = citations_answer(messages)
        assert (
            client.post(
                f"{KNOW}/{doc['id']}/unpublish", json={"expected_revision": 2, "version_id": version["id"]}
            ).status_code
            == 200
        )
        return answer

    install(app, [tools(("search_knowledge", {"query": "参考照"})), late])
    result, _ = support_send(client, view, "参考照要求")
    assert not process_run(app, result["runs"][-1]["id"])
    final = client.get(f"{SUP}/{view['id']}").json()
    assert final["runs"][-1]["error_code"] == "KNOWLEDGE_CHANGED"
    assert all(m["role"] != "assistant" for m in final["messages"])


def test_support_isolation_role_routing_and_no_image_side_effects(client, app):
    """独立客服无项目不读创作数据，纯状态走support，混合创作走creative。"""
    login(client)
    project = create_project(client)
    pure, _ = send(client, project, "查询生成进度和失败原因")
    with app.state.sessions() as db:
        run = db.get(AgentRun, pure["id"])
        assert run.primary_role == "support"
        assert "draft" not in run.context_json["facts"] and "materials" not in run.context_json["facts"]
    client.post(f"/api/v1/web/agent-runs/{pure['id']}/cancel")
    mixed, _ = send(client, project, "看看次数够不够，再做四张海边照")
    assert mixed["primary_role"] == "creative"
    view = open_chat(client)
    assert view["project_id"] is None
    same = open_chat(client)
    assert same["id"] == view["id"]
    install(app, [proposal(), {"outcome": "answer", "reply": "请返回工作室整理创作提案。"}])
    result, _ = support_send(client, view, "请直接帮我生成图片")
    assert process_run(app, result["runs"][-1]["id"])
    with app.state.sessions() as db:
        run = db.get(AgentRun, result["runs"][-1]["id"])
        assert run.primary_role == "support"
        assert not any(x in run.context_json["facts"] for x in ("draft", "materials", "catalog"))
        assert not any(db.scalar(select(func.count()).select_from(model)) for model in (Plan, Approval, Job))


def test_handoff_cancels_late_reply_staff_messages_and_release_no_replay(client, app):
    """人工待领取允许机器人继续响应，领取才能人工回复，交还不重放旧消息。"""
    admin(client, app)
    login(client)
    view = open_chat(client)

    def request_during_call(messages):
        """无数据库事务的模型等待期间，可由用户并发请求人工。"""
        response = client.post(f"{SUP}/{view['id']}/handoff", json={"expected_revision": 0})
        assert response.status_code == 200, response.text
        return {"outcome": "answer", "reply": "迟到自动回复"}

    install(app, [request_during_call])
    result, body = support_send(client, view)
    assert process_run(app, result["runs"][-1]["id"])
    requested = client.get(f"{SUP}/{view['id']}").json()
    assert requested["handoff_status"] == "requested"
    assert len(requested["messages"]) == 2
    assert client.get("/api/v1/admin/support").json()[0]["id"] == view["id"]
    assert (
        client.post(
            f"/api/v1/admin/support/{view['id']}/messages",
            json={
                "expected_revision": 1,
                "expected_privacy_epoch": 0,
                "client_message_id": str(uuid4()),
                "text": "未经领取",
            },
        ).status_code
        == 403
    )
    claimed = client.post(f"/api/v1/admin/support/{view['id']}/claim", json={"expected_revision": 1}).json()
    assert claimed["handoff_status"] == "human"
    human, _ = support_send(client, claimed, "人工期间的新消息")
    assert len(human["runs"]) == 1
    reply = {
        "expected_revision": 2,
        "expected_privacy_epoch": 0,
        "client_message_id": "staff-reply",
        "text": "人工客服已收到，我们一起核对。",
    }
    response = client.post(f"/api/v1/admin/support/{view['id']}/messages", json=reply)
    assert response.status_code == 200, response.text
    assert response.json()["messages"][-1]["role"] == "staff"
    assert response.json()["messages"][-1]["actor_id"]
    assert (
        client.post(f"/api/v1/admin/support/{view['id']}/messages", json=reply).json()["messages"][-1]["id"]
        == response.json()["messages"][-1]["id"]
    )
    returned = client.post(
        f"/api/v1/admin/support/{view['id']}/release", json={"expected_revision": 2}
    ).json()
    assert returned["handoff_status"] == "bot" and len(returned["runs"]) == 1
    with app.state.sessions() as db:
        assert db.scalar(select(func.count()).select_from(AgentRun)) == 1
    install(app, [{"outcome": "answer", "reply": "已恢复机器人，仅响应这条新问题。"}])
    next_view, _ = support_send(client, returned, "新的问题")
    assert process_run(app, next_view["runs"][-1]["id"])
    steps = client.get(f"/api/v1/web/agent-runs/{result['runs'][-1]['id']}/steps").json()
    assert not any(step["status"] == "running" for step in steps)


def test_support_ownership_and_project_privacy_scrubs_staff_text(client, app):
    """跨用户不可读，授权变更后人工消息也不能保留敏感正文/迟到写入。"""
    admin(client, app)
    login(client)
    project = create_project(client)
    view = open_chat(client, project["id"])
    assert client.post(f"{SUP}/{view['id']}/handoff", json={"expected_revision": 0}).status_code == 200
    claimed = client.post(f"/api/v1/admin/support/{view['id']}/claim", json={"expected_revision": 1}).json()
    support_send(client, claimed, "旧代次人工消息")
    with TestClient(app) as other:
        login(other, "13900000332")
        assert other.get(f"{SUP}/{view['id']}").status_code == 404
        assert other.post(SUP, json={"project_id": project["id"]}).status_code == 404
    from app.modules.projects.models import Project

    with app.state.sessions() as db:
        db.get(Project, project["id"]).privacy_epoch += 1
        db.commit()
    assert client.get(f"{SUP}/{view['id']}").json()["messages"] == []
    assert (
        client.post(
            f"/api/v1/admin/support/{view['id']}/messages",
            json={
                "expected_revision": 2,
                "expected_privacy_epoch": 0,
                "client_message_id": "late",
                "text": "旧编辑内容",
            },
        ).status_code
        == 409
    )
    maintain_runs(app)
    with app.state.sessions() as db:
        assert (
            db.scalar(select(Message).where(Message.conversation_id == view["id"])).text
            == "[授权变化后已清除]"
        )


def test_steps_record_bounded_attempts_and_release_is_frozen(client, app):
    """公开步骤记录调用尝试/上下文摘要，失败格式计预算；旧Run不换当前模型。"""
    login(client)
    project = create_project(client)
    install(app, [{"unexpected": "bad"}, proposal()])
    run, _ = send(client, project)
    assert run["release_json"]["release_digest"]
    assert process_run(app, run["id"])
    steps = client.get(f"/api/v1/web/agent-runs/{run['id']}/steps").json()
    assert [s["kind"] for s in steps].count("model") == 2
    assert any(s["kind"] == "validation" and s["error_code"] == "AGENT_INVALID_OUTPUT" for s in steps)
    assert all(s["status"] in {"succeeded", "failed"} for s in steps)
    assert [s["manifest_json"]["attempt_no"] for s in steps if s["kind"] == "model"] == [1, 2]
    assert "不要头纱" not in json.dumps(steps, ensure_ascii=False)
    with TestClient(app) as other:
        login(other, "13900000333")
        assert other.get(f"/api/v1/web/agent-runs/{run['id']}/steps").status_code == 404


def test_knowledge_expiry_source_parser_and_index_bounds(client, app):
    """到期/扫描或非法文本不能发布，错误维度不进入索引。"""
    from app.core.errors import DomainError
    from app.integrations.embeddings import validate_vectors
    from app.modules.knowledge.service import decode_source

    doc, version = knowledge(client, app)
    with app.state.sessions() as db:
        db.get(KnowledgeVersion, version["id"]).valid_until = now() - timedelta(seconds=1)
        db.commit()
    assert client.get("/api/v1/web/guides").json() == []
    with app.state.sessions() as db:
        assert search(app, db, "参考照")["evidence"] == []
    for content, format in [(b"\xff", "txt"), (b"<script>ignored</script>", "html"), (b"not-pdf", "pdf")]:
        with pytest.raises(DomainError):
            decode_source(content, format, 60000)
    for vector in ([0] * 1536, [1] * 10, [float("nan")] * 1536):
        with pytest.raises(ProviderFailure):
            validate_vectors([vector], 1)


def test_knowledge_embedding_failure_keyword_fallback_and_tool_scope(client, app, monkeypatch):
    """真实向量故障只降级已评测关键词策略，无项目客服不能调用项目次数。"""
    from app.core.errors import DomainError
    from app.integrations.embeddings import DevelopmentEmbedding
    from app.modules.agents.tools import ToolScope

    knowledge(client, app)
    login(client)

    def unavailable(self, texts, timeout_seconds=30):
        """供应商故障替身，不访问网络。"""
        raise ProviderFailure("EMBEDDING_UNAVAILABLE")

    monkeypatch.setattr(DevelopmentEmbedding, "embed", unavailable)
    # login helper不返回User，从API当前用户取真实范围。
    owner = client.get("/api/v1/web/me").json()
    result = app.state.agent_tools.read(
        app, ToolScope(owner["id"], None, 0, "support"), "search_knowledge", {"query": "参考照"}
    )
    assert result["strategy"] == "keyword-fallback-v1" and result["evidence"]
    with pytest.raises(DomainError):
        app.state.agent_tools.read(app, ToolScope(owner["id"], None, 0, "support"), "get_entitlements", {})
    with pytest.raises(DomainError):
        app.state.agent_tools.read(
            app, ToolScope(owner["id"], None, 0, "support"), "search_project_history", {"query": "照片"}
        )


def test_staff_role_permissions_and_concurrent_claim(client, app):
    """两个独立员工争抢只允许一人领取；员工不能发布知识或修改模型。"""
    from app.modules.conversations.support import handoff, own_conversation
    from app.modules.identity.credentials import provision_admin
    from app.modules.identity.models import User
    from app.workers.runtime import begin_write

    with app.state.sessions() as db:
        first = provision_admin(db, "staffone", "staff-only-test-password", "客服一")
        second = provision_admin(db, "stafftwo", "staff-only-test-password", "客服二")
        first.role = second.role = "staff"
        first_id, second_id = first.id, second.id
        db.commit()
    login(client)
    view = open_chat(client)
    assert client.post(f"{SUP}/{view['id']}/handoff", json={"expected_revision": 0}).status_code == 200

    def claim_as(actor_id):
        """独立数据库连接竞争同一会话版本。"""
        from app.core.errors import DomainError

        with app.state.sessions() as db:
            try:
                begin_write(db)
                hint = db.get(Conversation, view["id"])
                conv, _ = own_conversation(db, view["id"], hint.owner_user_id, lock=True)
                handoff(db, db.get(User, actor_id), conv, 1, "claim")
                return True
            except DomainError:
                return False

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(claim_as, [first_id, second_id])) == [False, True]
    with TestClient(app) as staff:
        assert (
            staff.post(
                "/api/v1/admin/auth/login",
                json={"username": "staffone", "password": "staff-only-test-password"},
            ).status_code
            == 200
        )
        assert staff.get("/api/v1/admin/me").json()["role"] == "staff"
        assert staff.get("/api/v1/admin/support").status_code == 200
        assert staff.get(KNOW).status_code == 403
        assert staff.get("/api/v1/admin/model-settings/ai302").status_code == 403
        assert staff.get("/api/v1/admin/users").status_code == 403


def test_knowledge_index_worker_duplicate_delivery_and_interrupted_job(client, app):
    """重复投递只索引一次；已超时running不能重发embedding或污染旧发布。"""
    from app.modules.knowledge.worker import maintain

    doc, version = knowledge(client, app)
    with app.state.sessions() as db:
        job = db.scalar(select(KnowledgeIndexJob).where(KnowledgeIndexJob.version_id == version["id"]))
        job_id = job.id
        chunks = db.scalar(select(func.count()).select_from(KnowledgeChunk))
    assert index(app, job_id) is False
    with app.state.sessions() as db:
        assert db.scalar(select(func.count()).select_from(KnowledgeChunk)) == chunks
    response = client.post(
        f"{KNOW}/{doc['id']}/versions",
        json={
            "expected_revision": 2,
            "request_key": "interrupted",
            "title": "新版本",
            "text": "参考照要求的新版本",
        },
    )
    assert response.status_code == 202
    with app.state.sessions() as db:
        job = db.scalar(
            select(KnowledgeIndexJob).where(KnowledgeIndexJob.version_id == response.json()["id"])
        )
        job.status = "running"
        job.deadline_at = now() - timedelta(seconds=1)
        job_id = job.id
        db.commit()
    maintain(app)
    assert not index(app, job_id)
    assert client.get("/api/v1/web/guides").json()[0]["version_id"] == version["id"]


def test_support_sse_uses_same_authoritative_protocol(client, app):
    """客服SSE真实采样有原生前缀和人工状态变化，权限复核拒绝跨用户。"""
    from types import SimpleNamespace

    from app.modules.conversations.events import changes
    from app.modules.conversations.support_events import read_stamp

    login(client)
    view = open_chat(client)
    request = SimpleNamespace(app=app, cookies={"yx_web": client.cookies.get("yx_web")})
    before = read_stamp(request, view["id"])
    assert client.post(f"{SUP}/{view['id']}/handoff", json={"expected_revision": 0}).status_code == 200
    after = read_stamp(request, view["id"])
    assert any("stream.sync" in frame for frame in changes(before, after, view["id"]))
    with TestClient(app) as other:
        login(other, "13900000335")
        request.cookies = {"yx_web": other.cookies.get("yx_web")}
        from app.core.errors import DomainError

        with pytest.raises(DomainError):
            read_stamp(request, view["id"])


def test_release_gate_requires_matching_reviewed_live_report(client, app, tmp_path):
    """工程通过不能自动变为生产质量批准，报告须匹配精确Release与重复抽样。"""
    import yaml

    from app.core.config import ROOT
    from app.core.errors import DomainError
    from app.modules.agents.releases import release_snapshot

    definition = yaml.safe_load((ROOT / "resources/agent/release.yaml").read_text())
    definition["quality_report"] = str(tmp_path / "review.json")
    release_file = tmp_path / "release.yaml"
    release_file.write_text(yaml.safe_dump(definition))
    app.state.config["agent"]["release_file"] = str(release_file)
    policy = app.state.gateway.snapshot("llm")
    frozen = release_snapshot(app, policy)
    app.state.settings.app_env = "production"
    report = {
        "scope": "live_samples",
        "sample_count": 2,
        "dataset_version": definition["dataset_version"],
        "rubric_version": definition["rubric_version"],
        "candidate_release": frozen["release_digest"],
        "quality_approved": False,
        "critical_failures": [],
        "reviewed_by": None,
    }
    target = tmp_path / "review.json"
    target.write_text(json.dumps(report))
    with pytest.raises(DomainError):
        release_snapshot(app, policy)
    report.update(
        quality_approved=True,
        reviewed_by="synthetic-unit-reviewer",
        actual_cost_micros=0,
        bill_reference="synthetic-test-bill",
        quality_review="synthetic-test-review",
    )
    dataset = json.loads((ROOT / "resources/agent/m2-cases.json").read_text())
    report["cases"] = [{"case_id": c["id"], "passed": True} for c in dataset["routing"]] + [
        {
            "case_id": c["id"],
            "sample": n,
            "passed": True,
            "status": "succeeded",
            "release_digest": frozen["release_digest"],
        }
        for c in dataset["live"]
        for n in (1, 2)
    ]
    target.write_text(json.dumps(report))
    assert release_snapshot(app, policy)["release_digest"] == frozen["release_digest"]
    report["candidate_release"] = "stale-digest"
    target.write_text(json.dumps(report))
    with pytest.raises(DomainError):
        release_snapshot(app, policy)


def test_m2_migration_preserves_existing_chat_and_refuses_lossy_support_rollback(client, app):
    """旧消息往返保留；有独立客服数据时有损回退被拒绝且事务回滚。"""
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import text

    login(client)
    project = create_project(client)
    run, _ = send(client, project, "迁移前的创作要求")
    client.post(f"/api/v1/web/agent-runs/{run['id']}/cancel")
    command.downgrade(Config("alembic.ini"), "c64d48a13be9")
    with app.state.sessions() as db:
        assert db.execute(text("SELECT text FROM messages")).scalar_one() == "迁移前的创作要求"
    command.upgrade(Config("alembic.ini"), "head")
    command.check(Config("alembic.ini"))
    restored = client.get(f"/api/v1/web/projects/{project['id']}/conversation").json()
    assert restored["messages"][0]["text"] == "迁移前的创作要求"
    view = open_chat(client)
    with pytest.raises(RuntimeError, match="禁止有损回退"):
        command.downgrade(Config("alembic.ini"), "c64d48a13be9")
    assert client.get("/ready").status_code == 200
    assert client.get(f"{SUP}/{view['id']}").status_code == 200


def test_insufficient_evidence_refusal_does_not_force_irrelevant_citations(client, app):
    """检索到无关片段时允许明确证据不足，不能强迫引用或伪装提案。"""
    knowledge(client, app)
    login(client)
    view = open_chat(client)

    def refusal(messages):
        """模型显式标记不足，同时保留实际查询结果来源。"""
        observations = json.loads(
            next(
                m["content"].split("：", 1)[1]
                for m in messages
                if m["content"].startswith("本轮服务端只读查询结果")
            )
        )
        return {
            "outcome": "answer",
            "reply": "当前知识无法确认此项政策，请请求人工客服。",
            "tool_sources": [o["id"] for o in observations],
            "evidence_status": "insufficient",
            "citations": [],
        }

    install(app, [tools(("search_knowledge", {"query": "参考照"})), refusal])
    response, _ = support_send(client, view, "请确认一个没有依据的政策")
    assert process_run(app, response["runs"][-1]["id"])
    final = client.get(f"{SUP}/{view['id']}").json()
    assert final["messages"][-1]["citations_json"] == []
    assert "无法确认" in final["messages"][-1]["text"]
    from pydantic import ValidationError

    from app.modules.agents.schemas import AgentAnswer

    with pytest.raises(ValidationError):
        AgentAnswer.model_validate({**proposal(), "evidence_status": "insufficient"})


def test_knowledge_short_citation_keys_resolve_only_to_observed_chunks(client, app):
    """短引用键减少模型抄写长UUID的错误，后端仍只解析本轮真实证据。"""
    knowledge(client, app)
    login(client)
    view = open_chat(client)

    def cite_short(messages):
        """短键来自本轮工具数据，不能自行映射其他文档。"""
        observations = json.loads(
            next(
                m["content"].split("：", 1)[1]
                for m in messages
                if m["content"].startswith("本轮服务端只读查询结果")
            )
        )
        return {
            "outcome": "answer",
            "reply": "使用清晰自然光的参考照。[1]",
            "tool_sources": [o["id"] for o in observations],
            "citations": [observations[0]["data"]["evidence"][0]["citation_key"]],
        }

    install(app, [tools(("search_knowledge", {"query": "参考照"})), cite_short])
    result, _ = support_send(client, view, "参考照准备")
    assert process_run(app, result["runs"][-1]["id"])
    message = client.get(f"{SUP}/{view['id']}").json()["messages"][-1]
    assert (
        message["citations_json"][0]["chunk_id"]
        != message["observations_json"][0]["data"]["evidence"][0]["citation_key"]
    )
    assert client.get(f"/api/v1/web/messages/{message['id']}/citations/1").status_code == 200
