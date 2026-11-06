"""管理员补发权益：身份、归属、防重并发、原子流水及可查询的历史。"""

from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select
from test_creative_flow import account, create_project, login
from test_model_settings import admin

from app.modules.commerce.models import Account, EntitlementEvent
from app.modules.identity.models import User
from app.modules.media_jobs.models import Job
from app.modules.operations.models import Audit
from app.modules.projects.models import Project

PATH = "/api/v1/admin/entitlements"


def setup_grant(client):
    """创建隔离客户与项目并登录独立管理员，不调用出图。"""
    customer = login(client)
    project = create_project(client)
    admin(client)
    body = {
        "request_key": str(uuid4()),
        "user_id": customer["id"],
        "project_id": project["id"],
        "amount": 8,
        "reason": "补充内测创作次数",
    }
    return customer, project, body


def test_grant_transaction_history_and_retry(client, app):
    """补发只增加可用桶，原试用与人工流水均可查；重发返回原发放快照。"""
    customer, project, body = setup_grant(client)
    assert client.post(f"/api/v1/web/projects/{project['id']}/trial-grants").status_code == 200
    with app.state.sessions() as db:
        quota = db.scalar(select(Account).where(Account.project_id == project["id"]))
        quota.available, quota.reserved, quota.consumed = 0, 2, 6
        db.commit()
    response = client.post(PATH + "/grants", json=body)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["amount"] == 8 and result["available_after"] == 8
    assert result["actor_id"] and result["source"] == "manual"
    assert account(client, project) == {"available": 8, "reserved": 2, "consumed": 6, "kind": "photo"}
    assert client.post(PATH + "/grants", json=body).json() == result
    # 后续新增一笔后重试旧请求，仍返回原记录和当时快照，不再次累加。
    assert (
        client.post(PATH + "/grants", json={**body, "request_key": str(uuid4()), "amount": 3}).status_code
        == 200
    )
    assert client.post(PATH + "/grants", json=body).json() == result
    assert account(client, project)["available"] == 11
    rows = client.get(
        PATH + "/grants", params={"user_id": customer["id"], "project_id": project["id"]}
    ).json()
    assert rows["total"] == 3 and {item["source"] for item in rows["items"]} == {"manual", "trial"}
    assert client.get(PATH + "/grants", params={"offset": 1, "limit": 1}).json()["total"] == 3
    assert "login_hash" not in str(rows) and "phone" not in str(rows)
    with app.state.sessions() as db:
        assert (
            db.scalar(select(func.count()).select_from(Audit).where(Audit.action == "entitlements.grant"))
            == 2
        )
        assert db.scalar(select(func.count()).select_from(Job)) == 0


@pytest.mark.parametrize(
    "patch",
    [
        {"amount": 0},
        {"amount": -1},
        {"amount": 1.5},
        {"amount": True},
        {"amount": 10001},
        {"reason": "   "},
        {"reason": "x" * 121},
        {"request_key": "not-a-key"},
        {"reserved": 9},
    ],
)
def test_invalid_grants_do_not_change_quota(client, patch):
    """数量、原因、请求键和额外权益字段在写入前拒绝。"""
    _, project, body = setup_grant(client)
    assert client.post(PATH + "/grants", json={**body, **patch}).status_code == 422
    assert account(client, project)["available"] == 0


def test_grant_permissions_owner_and_project_state(client, app):
    """用户和客服不能发放；过期用户、错配项目、归档及删除项目不能领到次数。"""
    customer = login(client)
    project = create_project(client)
    body = {
        "request_key": str(uuid4()),
        "user_id": customer["id"],
        "project_id": project["id"],
        "amount": 8,
        "reason": "测试",
    }
    assert client.post(PATH + "/grants", json=body).status_code == 401
    admin(client)
    identity = client.get("/api/v1/admin/me").json()
    with app.state.sessions() as db:
        db.get(User, identity["id"]).role = "staff"
        db.commit()
    for path in ("/users", f"/users/{customer['id']}/projects", "/grants"):
        assert client.get(PATH + path).status_code == 403
    assert client.post(PATH + "/grants", json=body).status_code == 403
    with app.state.sessions() as db:
        db.get(User, identity["id"]).role = "admin"
        db.commit()
    other = login(client, "13800000999")
    assert client.post(PATH + "/grants", json={**body, "user_id": other["id"]}).status_code == 404
    for state in ("archived", "deleting", "deleted"):
        with app.state.sessions() as db:
            db.get(Project, project["id"]).lifecycle = state
            db.commit()
        assert client.post(PATH + "/grants", json=body).status_code in {404, 409}
    with app.state.sessions() as db:
        db.get(Project, project["id"]).lifecycle = "active"
        db.get(User, customer["id"]).status = "blocked"
        db.commit()
    assert client.post(PATH + "/grants", json=body).status_code == 404
    assert client.get(PATH + f"/users/{customer['id']}/projects").status_code == 404
    assert client.post(PATH + "/grants", json={**body, "user_id": identity["id"]}).status_code == 404


def test_grant_key_conflict_and_concurrency(client, app):
    """并发相同键只发一次，独立键正确相加，同键改原因/次数/项目拒绝。"""
    _, project, body = setup_grant(client)

    def submit(value):
        """不同会话连接竞争同一个权益账户。"""
        with TestClient(app) as other:
            other.cookies.update(client.cookies)
            return other.post(PATH + "/grants", json=value)

    with ThreadPoolExecutor(3) as pool:
        responses = list(pool.map(submit, [body] * 3))
    assert all(response.status_code == 200 for response in responses)
    assert len({response.json()["id"] for response in responses}) == 1
    for patch in ({"reason": "不同原因"}, {"amount": 9}, {"project_id": str(uuid4())}):
        response = client.post(PATH + "/grants", json={**body, **patch})
        assert response.status_code == 409 and response.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    with ThreadPoolExecutor(3) as pool:
        responses = list(pool.map(submit, [{**body, "request_key": str(uuid4())} for _ in range(3)]))
    assert all(response.status_code == 200 for response in responses)
    assert account(client, project)["available"] == 32
    with app.state.sessions() as db:
        assert db.scalar(select(func.count()).select_from(EntitlementEvent)) == 4


def test_grant_audit_failure_rolls_back_everything(client, app):
    """审计写入失败时，权益增加与流水均回滚，不能留下无记录的次数。"""
    _, project, body = setup_grant(client)

    def fail(mapper, connection, target):
        """仅在本测试人工发放审计处注入数据库失败。"""
        if target.action == "entitlements.grant":
            raise RuntimeError("synthetic audit failure")

    event.listen(Audit, "before_insert", fail)
    try:
        with TestClient(app, raise_server_exceptions=False) as other:
            other.cookies.update(client.cookies)
            assert other.post(PATH + "/grants", json=body).status_code == 500
    finally:
        event.remove(Audit, "before_insert", fail)
    assert account(client, project)["available"] == 0
    assert client.get(PATH + "/grants").json()["total"] == 0
    assert client.post(PATH + "/grants", json=body).status_code == 200


def test_grant_options_are_searchable_paginated_and_owner_scoped(client, app):
    """超过一页的客户仍可选，昵称相同可按ID定位，用户切换不串项目。"""
    customer, project, _ = setup_grant(client)
    other = login(client, "13800000999")
    other_project = create_project(client)
    with app.state.sessions() as db:
        for i in range(51):
            db.add(User(login_hash=f"grant-fixture-{i}", display_name="发放分页客户"))
        db.commit()
    first = client.get(PATH + "/users", params={"q": "发放分页客户"}).json()
    second = client.get(PATH + "/users", params={"q": "发放分页客户", "offset": 50}).json()
    assert first["total"] == 51 and len(first["items"]) == 50 and len(second["items"]) == 1
    found = client.get(PATH + "/users", params={"q": customer["id"]}).json()
    assert len(found["items"]) == 1 and found["items"][0]["id"] == customer["id"]
    own = client.get(PATH + f"/users/{customer['id']}/projects").json()
    assert [item["id"] for item in own["items"]] == [project["id"]]
    assert client.get(PATH + f"/users/{other['id']}/projects").json()["items"][0]["id"] == other_project["id"]
    assert client.get(PATH + "/users", params={"q": "%"}).json()["total"] == 0
