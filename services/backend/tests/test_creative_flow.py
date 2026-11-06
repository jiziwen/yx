"""核心业务验收：确认原子性、身份隔离、授权、取消、失败和崩溃恢复。"""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from io import BytesIO
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.core.db import now
from app.integrations.contracts import ProviderFailure
from app.modules.media_jobs.models import Job
from app.workers.runtime import maintenance, process_job, tick


def login(client, phone="13800000001"):
    """开发验证码只在测试里消费，不使用真实短信。"""
    code = client.post("/api/v1/web/auth/code", json={"phone": phone})
    assert code.status_code == 200, code.text
    response = client.post("/api/v1/web/auth/login", json={"phone": phone, "code": code.json()["debug_code"]})
    assert response.status_code == 200, response.text
    return response.json()


def create_project(client, kind="portrait"):
    """通过真实 HTTP 动作创建项目并领取一次账号试用。"""
    response = client.post(
        "/api/v1/web/projects",
        json={"title": "测试影像项目", "kind": kind},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert response.status_code == 201, response.text
    project = response.json()
    return project


def image_bytes():
    """生成无人物测试图片，避免把真实个人资料放进仓库。"""
    buffer = BytesIO()
    Image.new("RGB", (160, 200), "#d4b5ab").save(buffer, "PNG")
    return buffer.getvalue()


def prepare(client, kind="portrait"):
    """建立人物、上传、冻结方案；此步骤不应创建任何图片任务。"""
    project = create_project(client, kind)
    grant = client.post(f"/api/v1/web/projects/{project['id']}/trial-grants")
    assert grant.status_code == 200, grant.text
    subjects = []
    for key in ["person_a", "person_b"] if kind == "wedding" else ["person_a"]:
        subject = client.post(
            f"/api/v1/web/projects/{project['id']}/subjects",
            json={"subject_key": key, "display_name": key, "declared": True},
        )
        assert subject.status_code == 200, subject.text
        subjects.append(subject.json())
        upload = client.post(
            f"/api/v1/web/projects/{project['id']}/uploads",
            data={"subject_id": subject.json()["id"]},
            files={"file": ("synthetic.png", image_bytes(), "image/png")},
        )
        assert upload.status_code == 200, upload.text
    project = client.get(f"/api/v1/web/projects/{project['id']}").json()
    plan = save_plan(client, project)
    return project, subjects, plan


def save_plan(client, project, **changes):
    """保存一个版本化方案；style_id 与界面主题是独立概念。"""
    body = {
        "style_id": "portrait_portrait_01" if project["kind"] == "portrait" else "rose_wedding_01",
        "style_version": "1",
        "aspect_ratio": "3:4",
        "count": 2,
        "mood": "自然柔光",
        "notes": "验证固定方案",
        "expected_revision": project["brief_revision"],
        **changes,
    }
    response = client.post(
        f"/api/v1/web/projects/{project['id']}/plans", json=body, headers={"Idempotency-Key": str(uuid4())}
    )
    assert response.status_code == 200, response.text
    return response.json()


def accept(client, plan, key=None):
    """确认动作要求显式幂等键，不把保存方案当成执行。"""
    return client.post(
        f"/api/v1/web/approvals/{plan['approval_id']}/accept",
        headers={"Idempotency-Key": key or str(uuid4())},
    )


def account(client, project):
    """从权威 API 读取三个权益桶。"""
    return client.get(f"/api/v1/web/projects/{project['id']}/entitlements").json()


def test_full_flow_and_exactly_once_acceptance(client, app):
    """保存不执行，重复确认不重复预占，Worker 重投不会重复交付。"""
    login(client)
    project, _, plan = prepare(client)
    assert client.get(f"/api/v1/web/projects/{project['id']}/jobs").json() == []
    key = str(uuid4())
    first, second = accept(client, plan, key), accept(client, plan, key)
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert accept(client, plan).status_code == 409
    assert account(client, project) == {"available": 6, "reserved": 2, "consumed": 0, "kind": "photo"}
    assert tick(app) == 2
    assert tick(app) == 0
    assert account(client, project) == {"available": 6, "reserved": 0, "consumed": 2, "kind": "photo"}
    works = client.get(f"/api/v1/web/projects/{project['id']}/works").json()
    assert len(works) == 2 and all(work["development_sample"] for work in works)
    assert {work["source_job_id"] for work in works} == set(first.json()["job_ids"])
    response = client.get(f"/api/v1/web/assets/{works[0]['id']}/content?download=true")
    assert response.status_code == 200 and response.headers["content-type"] == "image/png"
    assert response.headers["cache-control"] == "no-store"


def test_concurrent_same_confirmation(client, app):
    """五个并发 HTTP 确认相同卡，仅产生一组 Job 和一次预占。"""
    login(client)
    project, _, plan = prepare(client)
    key = str(uuid4())
    cookie = client.cookies.get("yx_web")

    def call(_):
        """每个线程独立客户端，模拟浏览器重试而非共享请求对象。"""
        with TestClient(app) as peer:
            peer.cookies.set("yx_web", cookie)
            return accept(peer, plan, key)

    with ThreadPoolExecutor(max_workers=5) as pool:
        responses = list(pool.map(call, range(5)))
    assert all(response.status_code == 200 for response in responses), [r.text for r in responses]
    assert all(r.json() == responses[0].json() for r in responses)
    assert account(client, project)["reserved"] == 2


def test_older_plan_and_insufficient_quota(client):
    """新版本作废旧卡；余额不足时确认与 Job 创建全部回滚。"""
    login(client)
    project, _, old = prepare(client)
    latest = save_plan(client, project, count=8)
    assert accept(client, old).json()["error"]["code"] == "PLAN_STALE"
    assert accept(client, latest).status_code == 200
    another = save_plan(client, project, count=1)
    response = accept(client, another)
    assert response.status_code == 409 and response.json()["error"]["code"] == "INSUFFICIENT_ENTITLEMENTS"
    assert len(client.get(f"/api/v1/web/projects/{project['id']}/jobs").json()) == 8


def test_identity_isolation_admin_and_csrf(client, app):
    """别人的 ID 返回 404；普通登录不具有管理权限；跨站写请求被拒绝。"""
    login(client)
    project, _, _ = prepare(client)
    assert client.get("/api/v1/admin/overview").status_code == 401
    with TestClient(app) as other:
        login(other, "13800000002")
        assert other.get(f"/api/v1/web/projects/{project['id']}").status_code == 404
        assert other.get(f"/api/v1/web/projects/{project['id']}/assets").status_code == 404
    response = client.post(
        "/api/v1/web/projects",
        json={"title": "bad", "kind": "portrait"},
        headers={"Origin": "https://attacker.example", "Idempotency-Key": str(uuid4())},
    )
    assert response.status_code == 403
    admin = client.post(
        "/api/v1/admin/auth/login", json={"username": "admin", "password": app.state.settings.admin_password}
    )
    assert admin.status_code == 200
    assert client.get("/api/v1/admin/overview").status_code == 200
    assert "storage_key" not in client.get("/api/v1/admin/catalog").text


def test_revocation_blocks_download_immediately_and_cleanup_recovers(client, app):
    """撤销即阻断读取，清理幂等且可在进程重启后继续。"""
    login(client)
    project, subjects, plan = prepare(client)
    accept(client, plan)
    tick(app)
    works = client.get(f"/api/v1/web/projects/{project['id']}/works").json()
    assert client.post(f"/api/v1/web/subjects/{subjects[0]['id']}/revoke").status_code == 200
    assert client.get(f"/api/v1/web/assets/{works[0]['id']}/content").status_code == 404
    assert client.get(f"/api/v1/web/projects/{project['id']}/works").json() == []
    maintenance(app)
    maintenance(app)
    assert not list(app.state.settings.storage_root.rglob("*.png"))


def test_revocation_during_remote_generation_discards_output(client, app):
    """外部返回前撤销授权，迟到结果不能交付或占用用户权益。"""
    login(client)
    project, subjects, plan = prepare(client)
    job = accept(client, plan).json()["job_ids"][0]
    provider = app.state.gateway.get("image")
    generate = provider.generate

    def revoked(request):
        """模拟模型请求在飞行期间用户撤销人物授权。"""
        client.post(f"/api/v1/web/subjects/{subjects[0]['id']}/revoke")
        return generate(request)

    provider.generate = revoked
    process_job(app, job)
    assert client.get(f"/api/v1/web/projects/{project['id']}/works").json() == []
    jobs = client.get(f"/api/v1/web/projects/{project['id']}/jobs").json()
    assert next(item for item in jobs if item["id"] == job)["status"] == "cancelled"
    assert account(client, project)["reserved"] == 1


@pytest.mark.parametrize("unknown,expected", [(False, "failed"), (True, "reconciliation_required")])
def test_provider_failure_settlement(client, app, unknown, expected):
    """确定拒绝返还；超时等未知结果保留预占并禁止自动重发。"""
    login(client)
    project, _, plan = prepare(client)
    job = accept(client, plan).json()["job_ids"][0]

    def fail(_):
        """供应商故障注入，不发起真实网络请求。"""
        raise ProviderFailure("TEST_FAILURE", unknown=unknown)

    app.state.gateway.get("image").generate = fail
    assert process_job(app, job)
    assert not process_job(app, job)
    with app.state.sessions() as db:
        assert db.get(Job, job).status == expected
    assert account(client, project)["reserved"] == (2 if unknown else 1)


def test_cancel_releases_once_and_crash_holds(client, app):
    """重复取消只返还一次，已提交任务租约过期转待核对。"""
    login(client)
    project, _, plan = prepare(client)
    jobs = accept(client, plan).json()["job_ids"]
    assert client.post(f"/api/v1/web/jobs/{jobs[0]}/cancel").status_code == 200
    assert client.post(f"/api/v1/web/jobs/{jobs[0]}/cancel").status_code == 200
    with app.state.sessions() as db:
        job = db.get(Job, jobs[1])
        job.status, job.lease_until = "running", now() - timedelta(seconds=1)
        db.commit()
    maintenance(app)
    assert account(client, project)["reserved"] == 1
    with app.state.sessions() as db:
        assert db.get(Job, jobs[1]).status == "reconciliation_required"


def test_trial_is_account_scoped_and_codes_single_use(client, app):
    """新建项目不能重复领活动；验证码不能重复消费。"""
    phone = "13800000003"
    code = client.post("/api/v1/web/auth/code", json={"phone": phone}).json()["debug_code"]
    body = {"phone": phone, "code": code}
    assert client.post("/api/v1/web/auth/login", json=body).status_code == 200
    assert client.post("/api/v1/web/auth/login", json=body).status_code == 400
    first, second = create_project(client), create_project(client)
    assert client.post(f"/api/v1/web/projects/{first['id']}/trial-grants").status_code == 200
    assert client.post(f"/api/v1/web/projects/{first['id']}/trial-grants").status_code == 200
    assert client.post(f"/api/v1/web/projects/{second['id']}/trial-grants").status_code == 409
    assert (
        client.post(
            "/api/v1/web/projects",
            json={"title": "bad", "kind": "portrait", "role": "admin"},
            headers={"Idempotency-Key": str(uuid4())},
        ).status_code
        == 422
    )


def test_provider_change_requires_new_plan(client, app):
    """保存后变更模型配置不能借旧确认执行新供应商。"""
    login(client)
    _, _, plan = prepare(client)
    app.state.gateway.definitions["local-image"]["version"] = "changed"
    assert accept(client, plan).json()["error"]["code"] == "PROVIDER_CONFIG_CHANGED"


def test_wedding_requires_both_subjects(client, app):
    """双人项目完整输入后可以独立交付每张照片。"""
    login(client)
    project, subjects, plan = prepare(client, "wedding")
    assert len(subjects) == 2 and plan["spec_json"]["reference_count"] == 2
    assert accept(client, plan).status_code == 200
    assert tick(app) == 2


def test_accepted_jobs_keep_frozen_provider_after_default_route_change(client, app):
    """部署变更默认模型但保留旧插件时，已批准任务仍调用原供应商。"""
    from copy import deepcopy

    from app.integrations.local import MockImageProvider

    login(client)
    project, _, plan = prepare(client)
    assert accept(client, plan).status_code == 200
    replacement = MockImageProvider({}, app.state.settings)

    def wrong_provider(_):
        """如果旧任务被切到新默认供应商，立即使测试失败。"""
        raise AssertionError("accepted job must not switch providers")

    replacement.generate = wrong_provider
    app.state.gateway.providers["replacement"] = replacement
    app.state.gateway.definitions["replacement"] = deepcopy(app.state.gateway.definitions["local-image"])
    app.state.gateway.routes["image"] = "replacement"
    assert tick(app) == 2
    assert account(client, project)["consumed"] == 2
