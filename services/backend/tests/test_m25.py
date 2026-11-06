"""M2.5真实业务边界回归：所有图像与网关结果为隔离合成数据。"""

import json
from copy import deepcopy
from datetime import timedelta

import pytest
from sqlalchemy import func, select
from test_agent import ScriptedLLM, draft, send
from test_creative_flow import accept, account, create_project, image_bytes, login, prepare, save_plan
from test_model_settings import admin

from app.core.db import now
from app.modules.agents.models import AgentRun
from app.modules.media_jobs.models import Job
from app.modules.projects.models import StudioDraft
from app.workers.agent_runtime import process_run
from app.workers.runtime import maintenance, process_job


def put_draft(client, project, value, revision=0):
    """持久化草稿不触发任何付费操作。"""
    return client.put(
        f"/api/v1/web/projects/{project['id']}/studio-draft",
        json={
            "expected_revision": revision,
            "expected_privacy_epoch": project["privacy_epoch"],
            "draft": value,
        },
    )


def test_draft_revision_invalidates_both_confirmation_entries(client, app):
    """跨窗口修改后旧确认不可执行，重复保存不创建Jobs，刷新能恢复私有文本。"""
    login(client)
    project = create_project(client)
    value = draft()
    assert put_draft(client, project, value).json()["revision"] == 1
    assert put_draft(client, project, value).json()["error"]["code"] == "DRAFT_CONFLICT"
    plan = save_plan(client, project, mode="text", count=1, notes=value["notes"], studio_draft_revision=1)
    changed = {**value, "notes": "新的明确要求"}
    assert put_draft(client, project, changed, 1).json()["revision"] == 2
    assert accept(client, plan).json()["error"]["code"] == "PLAN_STALE"
    assert client.get(f"/api/v1/web/projects/{project['id']}/studio-draft").json()["draft"] == changed
    with app.state.sessions() as db:
        assert db.scalar(select(func.count()).select_from(Job)) == 0
        assert db.scalar(select(func.count()).select_from(AgentRun)) == 0


def test_vision_explicit_inputs_and_late_revocation(client, app):
    """仅主动授权的图像进入多模态请求，撤销后不提交迟到视觉文本。"""
    login(client)
    project = create_project(client)
    uploaded = client.post(
        f"/api/v1/web/projects/{project['id']}/uploads",
        data={"purpose": "base", "declared": "true"},
        files={"file": ("synthetic.png", image_bytes(), "image/png")},
    ).json()
    project = client.get(f"/api/v1/web/projects/{project['id']}").json()
    definition = deepcopy(app.state.gateway.definitions["local-llm"])
    definition.update(
        kind="vision", capabilities={"max_input_images": 2, "max_dimension": 512, "max_bytes": 1000000}
    )
    app.state.gateway.definitions["test-vision"] = definition
    app.state.gateway.routes["vision"] = "test-vision"
    captured = []

    def inspect(messages):
        captured.extend(messages[-1]["content"])
        return {"outcome": "answer", "reply": "观察：色块较均匀；不能判断人物相似度。"}

    app.state.gateway.providers["test-vision"] = ScriptedLLM([inspect])
    run, _ = send(
        client,
        project,
        "帮我看看光线",
        analysis_asset_ids=[uploaded["id"]],
        analysis_consent=True,
        analysis_purpose="分析光线",
    )
    assert process_run(app, run["id"])
    assert sum(part["type"] == "image_url" for part in captured) == 1
    with app.state.sessions() as db:
        record = db.get(AgentRun, run["id"])
        assert "base64" not in json.dumps(record.context_json)
        assert record.manifest_json["vision"]["images"][0]["asset_id"] == uploaded["id"]
    run, _ = send(
        client,
        project,
        "再次分析",
        analysis_asset_ids=[uploaded["id"]],
        analysis_consent=True,
        analysis_purpose="核对",
    )
    assert client.delete(f"/api/v1/web/assets/{uploaded['id']}").status_code == 200
    assert not process_run(app, run["id"])


def test_compensation_is_one_review_one_confirmation_no_extra_quota(client, app):
    """领取限定看图，审核不出图；补偿确认防重，成功/取消不污染用户权益。"""
    login(client)
    admin(client)
    project, _, plan = prepare(client)
    job_id = accept(client, plan).json()["job_ids"][0]
    assert process_job(app, job_id)
    asset = client.get(f"/api/v1/web/projects/{project['id']}/assets").json()
    photo = next(item for item in asset if item["kind"] == "photo")
    reference = next(item for item in asset if item["kind"] == "reference")
    url = f"/api/v1/web/projects/{project['id']}/feedback"
    body = {
        "asset_id": photo["id"],
        "reference_asset_id": reference["id"],
        "reason": "测试主观质量问题",
        "grant_view": True,
    }
    row = client.post(url, json=body).json()
    assert client.post(url, json=body).json()["id"] == row["id"]
    image_url = f"/api/v1/admin/quality-feedback/{row['id']}/assets/{photo['id']}"
    assert client.get(image_url).status_code == 404
    action = f"/api/v1/admin/quality-feedback/{row['id']}/action"
    claimed = client.post(action, json={"expected_revision": 1, "action": "claim"})
    assert claimed.status_code == 200, claimed.text
    assert client.get(image_url).status_code == 200
    approved = client.post(
        action, json={"expected_revision": 2, "action": "approve_redo", "note": "人工确认允许一次重做"}
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["plan"] is None  # 员工不能取得未授权输入的完整规格
    comp = client.get(url).json()[0]["plan"]
    before = account(client, project)
    assert comp["quota_snapshot"]["photo"] == 0
    executed = accept(client, comp, "single-compensation")
    assert executed.status_code == 200, executed.text
    assert len(executed.json()["job_ids"]) == 1
    assert accept(client, comp, "single-compensation").json() == executed.json()
    assert process_job(app, executed.json()["job_ids"][0])
    assert account(client, project) == before
    assert (
        client.post(
            action, json={"expected_revision": 3, "action": "approve_redo", "note": "不能重复补偿"}
        ).status_code
        == 409
    )
    assert (
        client.post(
            f"/api/v1/web/quality-feedback/{row['id']}/action",
            json={"expected_revision": 3, "action": "withdraw"},
        ).status_code
        == 200
    )
    assert client.get(image_url).status_code == 403


def test_release_complete_cases_rejects_missing_duplicate_and_failure():
    """不能只写质量批准或空失败列表绕过完整题集。"""
    from app.core.config import ROOT
    from app.modules.agents.releases import complete_cases

    dataset = json.loads((ROOT / "resources/agent/m2-cases.json").read_text())
    cases = [{"case_id": c["id"], "passed": True} for c in dataset["routing"]] + [
        {"case_id": c["id"], "sample": n, "passed": True, "status": "succeeded", "release_digest": "digest"}
        for c in dataset["live"]
        for n in (1, 2)
    ]
    report = {"sample_count": 2, "cases": cases}
    assert complete_cases(report, "digest")
    assert not complete_cases({**report, "cases": cases[:-1]}, "digest")
    assert not complete_cases({**report, "cases": [*cases, cases[0]]}, "digest")
    assert not complete_cases({**report, "cases": [{**cases[0], "passed": False}, *cases[1:]]}, "digest")


def test_experiment_unknown_cost_and_expiry_cleanup(tmp_path):
    """未知费用停下一批，过期清理包含备份，主目录从不进入清理。"""
    from evals.m25 import begin_batch, cleanup, create, folder_for, reconcile

    value = create(tmp_path)
    with pytest.raises(ValueError):
        begin_batch(value, 1, "first batch")
    value["readiness"] = dict.fromkeys(value["readiness"], True)
    batch = begin_batch(value, 1, "synthetic accounting test")
    with pytest.raises(ValueError):
        begin_batch(value, 1, "unknown previous bill")
    reconcile(value, batch["id"], 99, "synthetic bill")
    with pytest.raises(ValueError):
        begin_batch(value, 2, "over planning budget")
    folder = folder_for(value["id"], tmp_path)
    (folder / "backups" / "synthetic.db").write_text("private fixture")
    value["expires_at"] = (now() - timedelta(seconds=1)).isoformat()
    (folder / "manifest.json").write_text(json.dumps(value))
    assert cleanup(tmp_path) == [value["id"]]
    assert not folder.exists()
    with pytest.raises(ValueError):
        folder_for(value["id"], tmp_path)


def test_delete_clears_private_draft_even_without_agent_history(client, app):
    """从未聊天的手动用户也必须得到完整隐私清理。"""
    login(client)
    project, _, _ = prepare(client)
    assert put_draft(client, project, draft()).status_code == 200
    asset = client.get(f"/api/v1/web/projects/{project['id']}/assets").json()[0]
    client.delete(f"/api/v1/web/assets/{asset['id']}")
    assert client.get(f"/api/v1/web/projects/{project['id']}/studio-draft").json()["draft"] is None
    maintenance(app)
    with app.state.sessions() as db:
        assert db.get(StudioDraft, project["id"]).draft_json == {}


def test_candidates_stay_inactive_and_require_complete_evidence(client, app, monkeypatch):
    """候选保存不切换，旧PUT不能绕过审核，缺一项能力证据拒绝启用。"""
    from test_model_settings import body

    admin(client)
    monkeypatch.setenv("AI302_API_KEY", "synthetic")
    value = body(client, enabled=True)
    row = client.post("/api/v1/admin/model-candidates", json=value).json()
    assert client.get("/api/v1/admin/model-settings/ai302").json()["revision"] == 0
    assert client.put("/api/v1/admin/model-settings/ai302", json=value).status_code == 409
    response = client.post(
        f"/api/v1/admin/model-candidates/{row['id']}/activate",
        json={
            "expected_revision": 0,
            "candidate_digest": row["digest"],
            "confirmed": True,
            "cases": {"image:text": "only-one-case"},
            "actual_cost_cny": 0,
            "bill_reference": "synthetic",
            "review_note": "missing reference and edit evidence",
        },
    )
    assert response.status_code == 422
    assert client.get("/api/v1/admin/model-settings/ai302").json()["revision"] == 0


def test_handoff_claim_cancels_inflight_and_owner_exit_denies_staff(client, app):
    """等待人工不静音，真正领取取消在途回复，退出使旧员工版本失效。"""
    from test_agent import install
    from test_m2_completion import open_chat, support_send

    admin(client)
    login(client)
    view = open_chat(client)
    requested = client.post(
        f"/api/v1/web/conversations/{view['id']}/handoff", json={"expected_revision": 0}
    ).json()
    assert requested["handoff_status"] == "requested"

    def claim_during_call(messages):
        assert (
            client.post(
                f"/api/v1/admin/support/{view['id']}/claim", json={"expected_revision": 1}
            ).status_code
            == 200
        )
        return {"outcome": "answer", "reply": "不能迟到发布"}

    install(app, [claim_during_call])
    sent, _ = support_send(client, requested)
    assert not process_run(app, sent["runs"][-1]["id"])
    returned = client.post(
        f"/api/v1/web/conversations/{view['id']}/handoff/withdraw", json={"expected_revision": 2}
    )
    assert returned.status_code == 200
    reply = client.post(
        f"/api/v1/admin/support/{view['id']}/messages",
        json={
            "expected_revision": 2,
            "expected_privacy_epoch": 0,
            "client_message_id": "late-staff",
            "text": "迟到消息",
        },
    )
    assert reply.status_code == 403


def test_generic_preferences_retained_only_by_explicit_selection(client, app):
    """删除参考时只迁移用户选中的原话；账户删除仍清空所有偏好和草稿。"""
    from app.modules.project_memory.models import ProjectMemory

    login(client)
    project, _, _ = prepare(client)
    memory = client.put(
        f"/api/v1/web/projects/{project['id']}/memory",
        json={
            "expected_revision": 0,
            "expected_privacy_epoch": project["privacy_epoch"],
            "requirements": ["喜欢暖色光", "不要水印"],
        },
    )
    assert memory.status_code == 200, memory.text
    asset = client.get(f"/api/v1/web/projects/{project['id']}/assets").json()[0]
    response = client.request(
        "DELETE",
        f"/api/v1/web/assets/{asset['id']}",
        json={
            "expected_memory_revision": memory.json()["revision"],
            "requirements": ["喜欢暖色光"],
            "generic_text_only": True,
        },
    )
    assert response.status_code == 200, response.text
    assert client.get(f"/api/v1/web/projects/{project['id']}/memory").json()["requirements"] == ["喜欢暖色光"]
    assert client.request("DELETE", "/api/v1/web/account", json={"confirmed": True}).status_code == 200
    assert client.get(f"/api/v1/web/projects/{project['id']}").status_code == 401
    with app.state.sessions() as db:
        assert db.get(ProjectMemory, project["id"]).requirements_json == []


def test_experiment_runtime_isolation_batch_guard_and_pending_accounting(tmp_path, monkeypatch):
    """运行屏障验证专属目录和开放批次；未决任务不能用下一批继续扣费。"""
    import sqlite3

    from app.core.config import Settings
    from app.core.errors import DomainError
    from evals import m25_runtime
    from evals.m25 import begin_batch, create, ensure_idle, folder_for, reconcile

    value = create(tmp_path)
    folder = folder_for(value["id"], tmp_path)
    monkeypatch.setattr(m25_runtime, "folder_for", lambda run: folder_for(run, tmp_path))
    settings = Settings(
        m25_run_id=value["id"],
        database_url="sqlite:///" + str(folder / "database.db"),
        storage_root=folder / "objects",
    )
    m25_runtime.check(settings)
    with pytest.raises(DomainError):
        m25_runtime.check(settings, paid=True)
    value["readiness"] = dict.fromkeys(value["readiness"], True)
    batch = begin_batch(value, 1, "synthetic")
    (folder / "manifest.json").write_text(json.dumps(value))
    m25_runtime.check(settings, paid=True)
    with sqlite3.connect(folder / "database.db") as connection:
        connection.execute("CREATE TABLE jobs (status TEXT)")
        connection.execute("INSERT INTO jobs VALUES ('reconciliation_required')")
    with pytest.raises(ValueError):
        ensure_idle(folder)
    with sqlite3.connect(folder / "database.db") as connection:
        connection.execute("UPDATE jobs SET status='failed'")
    ensure_idle(folder)
    reconcile(value, batch["id"], 1, "synthetic-bill")
    (folder / "manifest.json").write_text(json.dumps(value))
    with pytest.raises(DomainError):
        m25_runtime.check(settings, paid=True)
    settings.storage_root = tmp_path
    with pytest.raises(DomainError):
        m25_runtime.check(settings)
    settings.storage_root = folder / "objects"
    value["expires_at"] = (now() - timedelta(seconds=1)).isoformat()
    (folder / "manifest.json").write_text(json.dumps(value))
    with pytest.raises(DomainError):
        m25_runtime.check(settings)


def test_draft_concurrent_edits_preserve_one_winner(client, app):
    """并发编辑同一草稿版本只能一个成功，冲突不得覆盖或生成图片。"""
    from concurrent.futures import ThreadPoolExecutor

    from fastapi.testclient import TestClient

    login(client)
    project = create_project(client)
    assert put_draft(client, project, draft()).status_code == 200
    cookie = client.cookies.get("yx_web")

    def edit(index):
        """各窗口独立会话携带相同期望版本。"""
        with TestClient(app) as peer:
            peer.cookies.set("yx_web", cookie)
            return put_draft(peer, project, {**draft(), "notes": f"窗口 {index}"}, 1)

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(edit, range(2)))
    assert sorted(response.status_code for response in responses) == [200, 409]
    winner = next(response.json() for response in responses if response.status_code == 200)
    assert client.get(f"/api/v1/web/projects/{project['id']}/studio-draft").json() == winner
    assert client.get(f"/api/v1/web/projects/{project['id']}/jobs").json() == []


def test_vision_suggestions_require_adoption_and_cross_project_is_denied(client, app):
    """视觉建议不自动应用；有授权勾选也不能分析其他项目图片。"""
    login(client)
    project = create_project(client)
    uploaded = client.post(
        f"/api/v1/web/projects/{project['id']}/uploads",
        data={"purpose": "base", "declared": "true"},
        files={"file": ("synthetic.png", image_bytes(), "image/png")},
    ).json()
    project = client.get(f"/api/v1/web/projects/{project['id']}").json()
    definition = deepcopy(app.state.gateway.definitions["local-llm"])
    definition.update(
        kind="vision", capabilities={"max_input_images": 2, "max_dimension": 512, "max_bytes": 1000000}
    )
    app.state.gateway.definitions["test-vision"] = definition
    app.state.gateway.routes["vision"] = "test-vision"
    app.state.gateway.providers["test-vision"] = ScriptedLLM(
        [
            {
                "outcome": "plan_ready",
                "reply": "观察与建议",
                "proposal": {"intent": "user_request", "notes": "建议调整光线"},
            }
        ]
    )
    run, _ = send(
        client,
        project,
        "看看图片并建议",
        analysis_asset_ids=[uploaded["id"]],
        analysis_consent=True,
        analysis_purpose="调整光线",
    )
    assert process_run(app, run["id"])
    view = client.get(f"/api/v1/web/projects/{project['id']}/conversation").json()
    assert view["messages"][-1]["proposal_json"]["intent"] == "suggestion"
    other = create_project(client)
    from uuid import uuid4

    response = client.post(
        f"/api/v1/web/projects/{other['id']}/messages",
        json={
            "text": "看看图片",
            "draft": draft(),
            "expected_revision": other["brief_revision"],
            "expected_memory_revision": 0,
            "client_message_id": str(uuid4()),
            "analysis_asset_ids": [uploaded["id"]],
            "analysis_consent": True,
            "analysis_purpose": "分析",
        },
    )
    assert response.status_code == 404
    assert response.json()["error"]["message"] == "图片不可访问"


def test_candidate_export_and_launcher_keep_separate_credentials(client, app, tmp_path, monkeypatch):
    """导出与启动装配仅使用实验密钥/数据库/存储，模拟进程不接真实网络。"""
    import yaml
    from test_model_settings import body

    from app.core.config import ApplicationConfig
    from evals import m25_runtime
    from evals.m25 import begin_batch, create, folder_for

    admin(client)
    candidate = client.post("/api/v1/admin/model-candidates", json=body(client, enabled=True)).json()
    value = create(tmp_path)
    folder = folder_for(value["id"], tmp_path)
    monkeypatch.setattr(m25_runtime, "folder_for", lambda run: folder_for(run, tmp_path))
    monkeypatch.setattr("app.main.create_app", lambda: app)
    monkeypatch.setattr(m25_runtime, "ROOT", tmp_path)
    m25_runtime.export_candidate(value["id"], candidate["id"])
    config = yaml.safe_load((folder / "application.yaml").read_text())
    ApplicationConfig.model_validate(config)
    assert config["providers"][config["routes"]["image"]]["options"]["api_key_env"] == "AI302_EVAL_API_KEY"
    assert config["knowledge"]["embedding_options"]["api_key_env"] == "AI302_EVAL_API_KEY"
    assert client.get("/api/v1/admin/model-settings/ai302").json()["revision"] == 0
    value = json.loads((folder / "manifest.json").read_text())
    value["readiness"] = dict.fromkeys(value["readiness"], True)
    begin_batch(value, 1, "synthetic")
    (folder / "manifest.json").write_text(json.dumps(value))
    monkeypatch.setenv("AI302_EVAL_API_KEY", "synthetic-eval-only")
    captured = {}

    class Process:
        """已退出的合成监督进程，不启动网络或工作器。"""

        def __init__(self, command, **kwargs):
            captured.update(kwargs)

        def poll(self):
            return 0

        def terminate(self):
            pass

        def wait(self, **kwargs):
            return 0

    monkeypatch.setattr(m25_runtime.subprocess, "Popen", Process)
    m25_runtime.launch(value["id"])
    assert captured["env"]["AI302_API_KEY"] == ""
    assert captured["env"]["AI302_EVAL_API_KEY"] == "synthetic-eval-only"
    assert captured["env"]["DATABASE_URL"] == "sqlite:///" + str(folder / "database.db")
    assert captured["env"]["STORAGE_ROOT"] == str(folder / "objects")


def test_explicit_agent_configuration_patch_is_structured_without_execution(client, app):
    """模式、画幅、张数和光线以配置补丁返回；理解要求不创建图片或改长期记忆。"""
    from test_agent import install, snapshot

    login(client)
    project = create_project(client)
    install(
        app,
        [
            {
                "outcome": "plan_ready",
                "reply": "已整理为横版暖光写真，两张。",
                "proposal": {
                    "intent": "user_request",
                    "mode": "portrait",
                    "aspect_ratio": "4:3",
                    "count": 2,
                    "mood": "暖色柔光",
                    "notes": "不要头纱；横版暖色柔光写真",
                },
            }
        ],
    )
    run, _ = send(client, project, "用人物参考设计横版暖光写真，两张，不要头纱")
    assert process_run(app, run["id"])
    view = snapshot(client, project)
    patch = view["messages"][-1]["proposal_json"]
    assert {key: patch[key] for key in ("intent", "mode", "aspect_ratio", "count", "mood")} == {
        "intent": "user_request",
        "mode": "portrait",
        "aspect_ratio": "4:3",
        "count": 2,
        "mood": "暖色柔光",
    }
    assert client.get(f"/api/v1/web/projects/{project['id']}/plans").json() == []
    assert client.get(f"/api/v1/web/projects/{project['id']}/jobs").json() == []
    assert client.get(f"/api/v1/web/projects/{project['id']}/memory").json()["requirements"] == []
