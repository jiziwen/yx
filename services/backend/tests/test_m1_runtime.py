"""M1 的确定性契约验收；MockTransport 验证真实 302 适配器，不产生付费调用。"""

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
from uuid import uuid4

import httpx
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from test_creative_flow import accept, account, image_bytes, login, prepare, save_plan

from app.core.config import Settings
from app.core.db import now
from app.integrations.ai302 import AI302Image
from app.integrations.contracts import (
    ImageLookup,
    ImageRequest,
    ImageResult,
    ImageSubmission,
    ProviderFailure,
)
from app.integrations.registry import Gateway
from app.integrations.secrets import provider_secret
from app.modules.assets.models import Asset
from app.modules.commerce.models import EntitlementEvent
from app.modules.media_jobs.governance import aware
from app.modules.media_jobs.models import Job, ProviderAttempt, RuntimeGate
from app.modules.projects.models import Project
from app.workers.runtime import maintenance, process_job, queued_ids, reconcile_job, tick


class DeferredImage:
    """带计数和受控查询事实的异步供应商替身，仅用于故障注入。"""

    def __init__(self):
        """记录调用次数，不保存私有输入。"""
        self.submissions, self.queries = [], []
        self.response = ImageLookup("pending")

    def submit(self, request):
        """接单后返回唯一凭据，禁止恢复路径重调。"""
        self.submissions.append(request.request_key)
        return ImageSubmission("task-" + request.request_key)

    def lookup(self, task_id, request_key):
        """查询只返回测试指定事实。"""
        self.queries.append((task_id, request_key))
        return self.response


def deferred(app, **runtime):
    """在冻结方案前装配测试插件和限额。"""
    provider = DeferredImage()
    app.state.gateway.providers["local-image"] = provider
    app.state.gateway.definitions["local-image"]["runtime"].update(runtime)
    return provider


def pending(client, app):
    """创建两个批准交付项并只提交第一个。"""
    login(client)
    project, subjects, plan = prepare(client)
    ids = accept(client, plan).json()["job_ids"]
    assert process_job(app, ids[0])
    return project, subjects, ids


def test_recover_after_restart_exactly_once(client, app):
    """数据库保存接单凭据，重建插件后继续查询并只发布/结算一次。"""
    provider = deferred(app, estimated_cost_micros=70000, currency="USD")
    project, _, ids = pending(client, app)
    with app.state.sessions() as db:
        job = db.get(Job, ids[0])
        job.lease_until = now() - timedelta(seconds=1)
        attempt = db.scalar(select(ProviderAttempt).where(ProviderAttempt.job_id == job.id))
        assert attempt.request_key == job.id and attempt.upstream_task_id == "task-" + job.id
        db.commit()
    maintenance(app)
    replacement = DeferredImage()
    replacement.response = ImageLookup(
        "succeeded",
        ImageResult(
            image_bytes(),
            usage={"input_tokens": 15, "prompt": "private", "url": "private"},
            actual_cost_micros=65000,
            currency="USD",
        ),
    )
    app.state.gateway.providers["local-image"] = replacement
    assert reconcile_job(app, ids[0], force=True)
    assert not reconcile_job(app, ids[0], force=True)
    assert not process_job(app, ids[0])
    assert len(provider.submissions) == len(replacement.queries) == 1 and not replacement.submissions
    assert account(client, project)["consumed"] == 1
    with app.state.sessions() as db:
        assert db.scalar(select(func.count()).select_from(Asset).where(Asset.source_job_id == ids[0])) == 1
        assert (
            db.scalar(
                select(func.count())
                .select_from(EntitlementEvent)
                .where(EntitlementEvent.event_key == f"job:{ids[0]}:settle")
            )
            == 1
        )
        attempt = db.scalar(select(ProviderAttempt).where(ProviderAttempt.job_id == ids[0]))
        assert attempt.estimated_cost_micros == 70000 and attempt.actual_cost_micros == 65000
        assert attempt.usage_json == {"input_tokens": 15} and attempt.latency_ms >= 0


def test_known_pending_clears_old_reconciliation_error_without_resubmission(client, app):
    """查询恢复后不继续显示旧错误，后续成图仍只交付和扣费一次。"""
    provider = deferred(app)
    project, _, ids = pending(client, app)
    provider.response = ImageLookup("unknown", error_code="PROVIDER_RESULT_UNAVAILABLE")
    assert reconcile_job(app, ids[0], force=True)
    provider.response = ImageLookup("pending")
    assert reconcile_job(app, ids[0], force=True)
    with app.state.sessions() as db:
        job = db.get(Job, ids[0])
        assert job.status == "running" and job.error_code is None
    provider.response = ImageLookup("succeeded", ImageResult(image_bytes()))
    assert reconcile_job(app, ids[0], force=True)
    assert len(provider.submissions) == 1
    assert len(client.get(f"/api/v1/web/projects/{project['id']}/works").json()) == 1
    assert account(client, project)["consumed"] == 1


@pytest.mark.parametrize(
    "state,expected,reserved",
    [
        ("pending", "running", 2),
        ("unknown", "reconciliation_required", 2),
        ("failed", "failed", 1),
        ("cancelled", "cancelled", 1),
    ],
)
def test_query_facts_and_quota(client, app, state, expected, reserved):
    """只有供应商明确终态才释放，未知/在途继续保留预占。"""
    provider = deferred(app)
    project, _, ids = pending(client, app)
    provider.response = ImageLookup(state, error_code="TEST_STATE")
    assert reconcile_job(app, ids[0], force=True)
    with app.state.sessions() as db:
        assert db.get(Job, ids[0]).status == expected
    assert account(client, project)["reserved"] == reserved
    assert len(provider.submissions) == 1


def test_unknown_submission_without_receipt_never_retries(client, app):
    """接单响应丢失不能按本地键推测远端 ID，也不能释放共享在途槽位。"""
    provider = deferred(app, max_in_flight=1)

    def lost(request):
        """模拟上游已接单但连接中断。"""
        provider.submissions.append(request.request_key)
        raise ProviderFailure("PROVIDER_RESULT_UNKNOWN", unknown=True)

    provider.submit = lost
    project, _, ids = pending(client, app)
    assert not reconcile_job(app, ids[0], force=True)
    assert not process_job(app, ids[0]) and not process_job(app, ids[1])
    maintenance(app)
    assert not process_job(app, ids[1])
    assert account(client, project)["reserved"] == 2 and len(provider.submissions) == 1


def test_shared_slots_and_rate_across_provider_aliases(client, app):
    """同一账号的两个模型共享槽位；查询不占新提交次数，完成后仍遵守分钟速率。"""
    provider = deferred(app, account_scope="same-account", max_in_flight=1, requests_per_minute=1)
    project, _, ids = pending(client, app)
    app.state.gateway.providers["alias"] = provider
    app.state.gateway.definitions["alias"] = deepcopy(app.state.gateway.definitions["local-image"])
    app.state.gateway.routes["image"] = "alias"
    alias_plan = save_plan(client, project)
    alias_ids = accept(client, alias_plan).json()["job_ids"]
    assert not process_job(app, alias_ids[0])
    provider.response = ImageLookup("succeeded", ImageResult(image_bytes()))
    reconcile_job(app, ids[0], force=True)
    assert not process_job(app, alias_ids[0])
    with app.state.sessions() as db:
        gate = db.get(RuntimeGate, "provider:same-account")
        gate.window_started_at = now() - timedelta(minutes=2)
        db.commit()
    assert process_job(app, alias_ids[0])
    assert account(client, project)["reserved"] == 3


def test_revoke_while_async_pending_discards_late_result_preserves_cost(client, app):
    """迟到成功记外部成功与费用，但授权撤销后不交付，权益仅返还一次。"""
    provider = deferred(app)
    project, subjects, ids = pending(client, app)
    client.post(f"/api/v1/web/subjects/{subjects[0]['id']}/revoke")
    provider.response = ImageLookup(
        "succeeded", ImageResult(image_bytes(), actual_cost_micros=1234, currency="USD")
    )
    reconcile_job(app, ids[0], force=True)
    assert client.get(f"/api/v1/web/projects/{project['id']}/works").json() == []
    assert account(client, project)["reserved"] == 1
    with app.state.sessions() as db:
        assert db.get(Job, ids[0]).status == "cancelled"
        attempt = db.scalar(select(ProviderAttempt).where(ProviderAttempt.job_id == ids[0]))
        assert attempt.status == "succeeded" and attempt.actual_cost_micros == 1234
        assert db.scalar(select(func.count()).select_from(Asset).where(Asset.source_job_id == ids[0])) == 0


def test_query_exception_and_concurrent_lease(client, app):
    """并发查询只领取一个租约；查询网络失败不是远端失败，不退费/重发。"""
    provider = deferred(app)
    project, _, ids = pending(client, app)
    entered, release = threading.Event(), threading.Event()

    def blocked(task_id, key):
        """释放数据库事务后阻塞网络，另一 Worker 应立即看到查询租约。"""
        entered.set()
        assert release.wait(5)
        raise ProviderFailure("PROVIDER_REJECTED")

    provider.lookup = blocked
    with ThreadPoolExecutor(2) as executor:
        future = executor.submit(reconcile_job, app, ids[0], force=True)
        assert entered.wait(5)
        assert not reconcile_job(app, ids[0], force=True)
        release.set()
        assert future.result()
    assert account(client, project)["reserved"] == 2 and len(provider.submissions) == 1
    with app.state.sessions() as db:
        assert db.get(Job, ids[0]).status == "reconciliation_required"


def test_atomic_queue_limit_does_not_reserve_or_accept(client, app):
    """入口拒绝发生在权益变更之前，原请求键可在容量恢复后继续确认。"""
    deferred(app)
    login(client)
    project, _, plan = prepare(client)
    limits = app.state.gateway.queue_limits
    limits["max_user_pending"] = 1
    key = str(uuid4())
    assert accept(client, plan, key).json()["error"]["code"] == "USER_PENDING_LIMIT"
    assert account(client, project)["reserved"] == 0
    assert client.get(f"/api/v1/web/projects/{project['id']}/jobs").json() == []
    limits["max_user_pending"] = 2
    assert accept(client, plan, key).status_code == 200
    assert accept(client, plan, key).status_code == 200


def test_breaker_pauses_new_submissions(client, app):
    """持续拒绝熔断新任务，已知失败返还，冷却不会重发原任务。"""
    provider = deferred(app, failure_threshold=1)

    def rejected(request):
        """明确拒绝没有未知副作用。"""
        provider.submissions.append(request.request_key)
        raise ProviderFailure("PROVIDER_RATE_LIMITED")

    provider.submit = rejected
    project, _, ids = pending(client, app)
    assert not process_job(app, ids[1])
    with app.state.sessions() as db:
        gate = db.get(RuntimeGate, "provider:local-image")
        gate.paused_until = now() - timedelta(seconds=1)
        db.commit()
    assert process_job(app, ids[1])
    assert provider.submissions == ids
    assert account(client, project)["reserved"] == 0


def test_admin_query_is_authorized_audited_and_redacted(client, app):
    """用户 Cookie 无权操作后台；管理员只能查询既有凭据，费用未知保持 null。"""
    provider = deferred(app)
    _, _, ids = pending(client, app)
    path = f"/api/v1/admin/jobs/{ids[0]}"
    assert client.get(path).status_code == 401
    assert (
        client.post(
            "/api/v1/admin/auth/login", json={"username": "admin", "password": "yingxu-dev-admin"}
        ).status_code
        == 200
    )
    view = client.get(path).json()
    assert view["can_reconcile"] and view["attempt"]["receipt_recorded"]
    assert "upstream_task_id" not in json.dumps(view) and "storage_key" not in json.dumps(view)
    assert view["attempt"]["actual_cost_micros"] is None
    assert client.post(path + "/reconcile", json={"expected_revision": 9999}).status_code == 409
    provider.response = ImageLookup("succeeded", ImageResult(image_bytes()))
    result = client.post(path + "/reconcile", json={"expected_revision": view["revision"]})
    assert result.status_code == 200, result.text
    assert result.json()["job"]["status"] == "succeeded" and not result.json()["can_reconcile"]
    assert len(provider.queries) == 1
    assert any(row["action"] == "job.reconcile" for row in client.get("/api/v1/admin/audit").json())


def test_302_transport_submit_query_download_and_redaction(client, app, monkeypatch):
    """真实适配器按官方字段提交多图/文生图；下载不携带 API 令牌。"""
    monkeypatch.setenv("AI302_API_KEY", "synthetic-secret")
    calls = []
    real_client = httpx.Client

    def handler(request):
        """只处理明确接口，禁止契约测试偷偷联网。"""
        calls.append(request)
        if request.url.path == "/302/v2/image/generate":
            assert request.headers["authorization"] == "Bearer synthetic-secret"
            assert request.url.params["run_async"] == "true"
            return httpx.Response(200, json={"task_id": "receipt-test", "status": "pending"})
        if request.url.path == "/302/v2/image/fetch/receipt-test":
            return httpx.Response(
                200,
                json={
                    "task_id": "receipt-test",
                    "status": "completed",
                    "image_url": "https://file.302.ai/output.png",
                    "raw_response": {"usage": {"input_tokens": 12, "secret": "private"}},
                },
            )
        if request.url.host == "8.8.8.8":
            assert "authorization" not in request.headers
            assert request.headers["host"] == "file.302.ai"
            assert request.extensions["sni_hostname"] == "file.302.ai"
            return httpx.Response(200, content=image_bytes())
        raise AssertionError("unexpected endpoint")

    def transport_client(**kwargs):
        """下载专用传输用Mock替代，不建立真实连接。"""
        transport = kwargs.pop("transport", None)
        if transport:
            transport.close()
        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr("app.integrations.ai302.httpx.Client", transport_client)
    monkeypatch.setattr("app.integrations.ai302.configured_proxy", lambda host: None)
    monkeypatch.setattr(
        "app.integrations.result_download.socket.getaddrinfo",
        lambda *a, **k: [(2, 1, 6, "", ("8.8.8.8", 443))],
    )
    options = {"models": {"text": "test-t2i", "reference": "test-i2i", "edit": "test-i2i"}}
    app.state.gateway.providers["local-image"] = AI302Image(options, app.state.settings)
    login(client)
    project, _, plan = prepare(client)
    job_id = accept(client, plan).json()["job_ids"][0]
    assert process_job(app, job_id)
    body = json.loads(calls[0].content)
    assert body["model"] == "test-i2i" and body["image"][0].startswith("data:image/png;base64,")
    assert reconcile_job(app, job_id, force=True)
    assert len(calls) == 3 and account(client, project)["consumed"] == 1
    provider = app.state.gateway.get("image")
    provider.submit(ImageRequest("test", "1:1", (), "text-key", operation="text"))
    assert "image" not in json.loads(calls[-1].content)
    assert json.loads(calls[-1].content)["model"] == "test-t2i"


@pytest.mark.parametrize(
    "url",
    [
        "http://file.302.ai/a",
        "https://file.302.ai.evil.test/a",
        "https://127.0.0.1/a",
        "https://user:pass@file.302.ai/a",
        "https://file.302.ai:8443/a",
    ],
)
def test_302_result_host_boundary(app, monkeypatch, url):
    """上游不能借结果 URL 请求内网、窃取认证或跟随恶意域名。"""
    monkeypatch.setenv("AI302_API_KEY", "synthetic")
    provider = AI302Image({"models": {"text": "test"}}, app.state.settings)
    with pytest.raises(ProviderFailure, match="PROVIDER_UNSAFE_RESULT"):
        provider._download(url)


def test_gateway_rejects_conflicting_shared_limits_and_candidate_production(app):
    """账号别名不能各自扩大限额，生产不能启用未验收图片供应商。"""
    config = deepcopy(app.state.config)
    definition = config["providers"]["local-image"]
    definition["runtime"]["account_scope"] = "shared"
    config["providers"]["alias"] = deepcopy(definition)
    config["providers"]["alias"]["runtime"]["max_in_flight"] += 1
    with pytest.raises(ValueError, match="共享限额"):
        Gateway(config, app.state.settings)
    definition["development_only"] = False
    config["providers"] = {"local-image": definition}
    with pytest.raises(ValueError, match="样例验收"):
        Gateway(config, app.state.settings.model_copy(update={"app_env": "production"}))


def test_dotenv_credentials_are_server_only(tmp_path, monkeypatch):
    """本地 .env 可提供密钥；显式环境变量优先且空值不回退。"""
    path = tmp_path / ".env"
    path.write_text("AI302_API_KEY=file-secret\n", encoding="utf-8")

    class LocalSettings(Settings):
        """使用隔离的测试 dotenv，不读取用户凭证。"""

        model_config = {**Settings.model_config, "env_file": path}

    settings = LocalSettings()
    monkeypatch.delenv("AI302_API_KEY", raising=False)
    assert provider_secret(settings, "AI302_API_KEY") == "file-secret"
    monkeypatch.setenv("AI302_API_KEY", "")
    assert provider_secret(settings, "AI302_API_KEY") == ""


def test_m1_migration_backfills_existing_attempts(client, app):
    """旧调用记录升级回填稳定请求键，任务、作品和权益在迁移前后不丢失。"""
    login(client)
    project, _, plan = prepare(client)
    job_id = accept(client, plan).json()["job_ids"][0]
    assert process_job(app, job_id)
    before = account(client, project)
    config = Config("alembic.ini")
    # 本用例只验旧业务迁移；显式丢弃隔离库中可重建的模型观测夹具。
    from sqlalchemy import delete

    from app.modules.operations.models import ModelCall

    with app.state.sessions() as db:
        db.execute(delete(ModelCall))
        db.commit()
    command.downgrade(config, "e3abaca68af6")
    assert client.get("/ready").status_code == 503
    command.upgrade(config, "head")
    command.check(config)
    with app.state.sessions() as db:
        attempt = db.scalar(select(ProviderAttempt).where(ProviderAttempt.job_id == job_id))
        assert attempt.request_key == job_id and attempt.account_scope == "local-image"
        assert db.get(Job, job_id).status == "succeeded"
    assert account(client, project) == before
    assert len(client.get(f"/api/v1/web/projects/{project['id']}/works").json()) == 1


def test_concurrent_admission_and_shared_account_gate(client, app):
    """不同用户/项目并发确认不超队列，随后跨项目提交仍共享同一账号槽位。"""
    provider = deferred(app, max_in_flight=1)
    login(client)
    first, _, first_plan = prepare(client)
    other = TestClient(app)
    try:
        login(other, "13800000002")
        second, _, second_plan = prepare(other)
        app.state.gateway.queue_limits["max_pending"] = 2
        with ThreadPoolExecutor(2) as executor:
            futures = [
                executor.submit(accept, client, first_plan),
                executor.submit(accept, other, second_plan),
            ]
            results = [future.result() for future in futures]
        assert sorted(result.status_code for result in results) == [200, 409]
        assert account(client, first)["reserved"] + account(other, second)["reserved"] == 2
        app.state.gateway.queue_limits["max_pending"] = 4
        failed_index = next(index for index, result in enumerate(results) if result.status_code == 409)
        results[failed_index] = accept(*[(client, first_plan), (other, second_plan)][failed_index])
        ids = [result.json()["job_ids"][0] for result in results]
        with ThreadPoolExecutor(2) as executor:
            claims = list(executor.map(lambda job_id: process_job(app, job_id), ids))
        assert sorted(claims) == [False, True] and len(provider.submissions) == 1
        with app.state.sessions() as db:
            ordered = queued_ids(db)
            assert len(ordered) == 3
            # 同一用户的余下两项不能排在另一用户唯一待处理项之前。
            owners = [db.get(Project, db.get(Job, key).project_id).owner_user_id for key in ordered]
            assert owners[0] != owners[1]
    finally:
        other.close()


def test_celery_dispatch_and_local_tick_recover_same_receipt(client, app, monkeypatch):
    """实际 scheduler 投递既有查询，消息无图片；本地 tick 同样能恢复。"""
    from app.workers.scheduler import dispatch

    provider = deferred(app)
    project, _, ids = pending(client, app)
    with app.state.sessions() as db:
        attempt = db.scalar(select(ProviderAttempt).where(ProviderAttempt.job_id == ids[0]))
        attempt.next_poll_at = now() - timedelta(seconds=1)
        db.commit()
    calls = []
    monkeypatch.setattr("app.workers.scheduler.media.delay", lambda key: calls.append(("media", key)))
    monkeypatch.setattr("app.workers.scheduler.reconcile.delay", lambda key: calls.append(("query", key)))
    monkeypatch.setattr("app.workers.scheduler.maintain.delay", lambda: calls.append(("maintenance",)))
    dispatch(app)
    assert ("query", ids[0]) in calls and ("media", ids[1]) in calls
    provider.response = ImageLookup("succeeded", ImageResult(image_bytes()))
    tick(app)
    assert account(client, project)["consumed"] == 1
    assert provider.submissions == ids


def test_config_change_blocks_query_without_starving_later_recoveries(client, app):
    """冻结配置改变后不向新配置查询旧任务，延后该项让其他查询继续。"""
    provider = deferred(app)
    _, _, ids = pending(client, app)
    app.state.gateway.definitions["local-image"]["version"] = "changed"
    assert not reconcile_job(app, ids[0], force=True)
    assert not provider.queries
    with app.state.sessions() as db:
        attempt = db.scalar(select(ProviderAttempt).where(ProviderAttempt.job_id == ids[0]))
        assert aware(attempt.next_poll_at) > now()
        assert db.get(Job, ids[0]).status == "reconciliation_required"


def test_retry_after_survives_another_inflight_success(client, app):
    """429 的账号退避不能被另一项迟到成功清除，旧任务也不能自动重发。"""
    provider = deferred(app)
    project, _, ids = pending(client, app)

    def limited(_):
        """第二项明确限流，要求等待两分钟。"""
        raise ProviderFailure("PROVIDER_RATE_LIMITED", retry_after_seconds=120)

    provider.submit = limited
    assert process_job(app, ids[1])
    provider.response = ImageLookup("succeeded", ImageResult(image_bytes()))
    assert reconcile_job(app, ids[0], force=True)
    with app.state.sessions() as db:
        gate = db.get(RuntimeGate, "provider:local-image")
        assert aware(gate.retry_after_until) > now() + timedelta(seconds=110)
    plan = save_plan(client, project)
    more = accept(client, plan).json()["job_ids"]
    assert not process_job(app, more[0])
    assert account(client, project)["reserved"] == 2


@pytest.mark.parametrize(
    "method,status,unknown", [("POST", 429, False), ("POST", 503, True), ("GET", 404, True)]
)
def test_302_http_failure_classification(app, monkeypatch, method, status, unknown):
    """提交 5xx 与查询 404 均不能退款；明确 429 保留标准退避信息。"""
    monkeypatch.setenv("AI302_API_KEY", "synthetic")
    real_client = httpx.Client
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            status, headers={"Retry-After": "120"}, json={"private": "upstream-secret"}
        )
    )
    monkeypatch.setattr(
        "app.integrations.ai302.httpx.Client", lambda **kwargs: real_client(transport=transport, **kwargs)
    )
    provider = AI302Image({"models": {"text": "test"}}, app.state.settings)
    with pytest.raises(ProviderFailure) as failure:
        provider._request(method, "/test")
    assert failure.value.unknown is unknown and "upstream-secret" not in str(failure.value)
    if status == 429:
        assert failure.value.retry_after_seconds == 120
