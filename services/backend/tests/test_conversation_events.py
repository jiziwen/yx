"""实时通道的鉴权、完成竞态和撤销边界；使用本地模型，不产生付费调用。"""

import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from test_agent import install, proposal, send, snapshot
from test_creative_flow import create_project, login

from app.modules.conversations.events import changes, event_stream, read_stamp
from app.modules.identity.models import User
from app.modules.projects.models import Project
from app.workers.agent_runtime import process_run


def request_for(client, app):
    """固定旧连接的 Cookie，退出后不能自动换成新会话。"""

    async def connected():
        return False

    return SimpleNamespace(
        app=app,
        cookies={"yx_web": client.cookies.get("yx_web")},
        is_disconnected=connected,
    )


def decode(frame):
    """读取测试事件名和最小通知信封。"""
    lines = frame.splitlines()
    return lines[0][7:], json.loads(lines[1][6:])


def test_stream_http_auth_headers_and_disable(client, app):
    """未授权不得先发 ready；合法连接无缓存/缓冲，关闭配置仍可读取快照。"""
    path = "/api/v1/web/projects/missing/conversation/events"
    assert client.get(path).status_code == 401
    login(client)
    project = create_project(client)
    path = f"/api/v1/web/projects/{project['id']}/conversation/events"
    with TestClient(app) as other:
        login(other, phone="13900000002")
        assert other.get(path).status_code == 404
    app.state.config["conversation_stream"].update(poll_seconds=0.001, max_connection_seconds=0.002)
    response = client.get(path)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-accel-buffering"] == "no"
    assert decode(response.text.split("\n\n")[0])[0] == "stream.ready"
    app.state.config["conversation_stream"]["enabled"] = False
    assert client.get(path).status_code == 503
    assert snapshot(client, project)["messages"] == []


def test_stream_completion_between_ready_and_snapshot(client, app):
    """订阅基线之后、快照之前完成，仍通知最终提交且不泄漏正文或私有上下文。"""
    login(client)
    project = create_project(client)
    install(app, [proposal()])
    request = request_for(client, app)
    initial = read_stamp(request, project["id"])
    app.state.config["conversation_stream"]["poll_seconds"] = 0.001

    async def scenario():
        stream = event_stream(request, project["id"], initial)
        assert decode(await anext(stream))[0] == "stream.ready"
        assert app.state.engine.pool.checkedout() == 0
        run, _ = send(client, project)
        assert process_run(app, run["id"])
        # 权威读取已包含终态；随后到达的通知只能触发重读，不能追加重复消息。
        view = snapshot(client, project)
        assert view["runs"][0]["status"] == "succeeded"
        committed, updated = await anext(stream), await anext(stream)
        assert decode(committed)[0] == "message.committed"
        assert decode(committed)[1]["resource_revision"] == 2
        assert decode(updated)[0] == "run.updated"
        assert decode(updated)[1]["resource_id"] == run["id"]
        assert "不要头纱" not in committed + updated
        assert "draft_context" not in committed + updated
        assert (
            changes(read_stamp(request, project["id"]), read_stamp(request, project["id"]), project["id"])
            == []
        )
        await stream.aclose()

    asyncio.run(scenario())
    with app.state.sessions() as db:
        assert db.bind.pool.checkedout() == 0


@pytest.mark.parametrize("revocation", ["logout", "blocked", "privacy", "deleted"])
def test_existing_stream_rechecks_authority(client, app, revocation):
    """现有连接的 Cookie 不变，退出/封禁/删除停止通知，隐私变更要求清空重建。"""
    user = login(client)
    project = create_project(client)
    request = request_for(client, app)
    initial = read_stamp(request, project["id"])
    app.state.config["conversation_stream"]["poll_seconds"] = 0.001

    async def scenario():
        stream = event_stream(request, project["id"], initial)
        await anext(stream)
        if revocation == "logout":
            assert client.post("/api/v1/web/auth/logout").status_code == 200
        else:
            with app.state.sessions() as db:
                if revocation == "blocked":
                    db.get(User, user["id"]).status = "blocked"
                elif revocation == "deleted":
                    db.get(Project, project["id"]).lifecycle = "deleted"
                else:
                    db.get(Project, project["id"]).privacy_epoch += 1
                db.commit()
        name, envelope = decode(await anext(stream))
        assert name == ("stream.reset" if revocation == "privacy" else "stream.revoked")
        assert envelope["payload"] == {}
        with pytest.raises(StopAsyncIteration):
            await anext(stream)

    asyncio.run(scenario())


def test_stream_memory_and_project_changes_are_invalidations(client, app):
    """修改项目记忆/草稿版本只触发权威重读，不把内容塞进广播载荷。"""
    login(client)
    project = create_project(client)
    request = request_for(client, app)
    initial = read_stamp(request, project["id"])
    response = client.put(
        f"/api/v1/web/projects/{project['id']}/memory",
        json={
            "expected_revision": 0,
            "expected_privacy_epoch": 0,
            "requirements": ["不出现水印"],
        },
    )
    assert response.status_code == 200
    events = changes(initial, read_stamp(request, project["id"]), project["id"])
    assert [decode(event)[0] for event in events] == ["stream.sync"]
    assert "不出现水印" not in str(events)
