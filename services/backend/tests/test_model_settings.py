"""模型发布的权限、不可变历史、并发和跨进程恢复，不发送真实模型请求。"""

import json
from concurrent.futures import ThreadPoolExecutor

import httpx
from sqlalchemy import func, select
from test_creative_flow import accept, login, prepare, save_plan

from app.integrations.contracts import ImageSubmission
from app.main import create_app
from app.modules.media_jobs.models import Job
from app.modules.operations.models import ModelRelease
from app.workers.runtime import process_job

PATH = "/api/v1/admin/model-settings/ai302"


def admin(client):
    """开发模式受控管理员，不把用户 Cookie 当成管理权限。"""
    result = client.post(
        "/api/v1/admin/auth/login", json={"username": "admin", "password": "yingxu-dev-admin"}
    )
    assert result.status_code == 200


def body(client, **changes):
    """读取真实表单版本，只允许修改已公开的配置字段。"""
    current = client.get(PATH).json()
    return {
        "expected_revision": current["revision"],
        "image": {**current["image"], **changes},
        "llm": current["llm"],
    }


def approved_publish(client, value):
    """隔离测试提供合成审核证据，正式API仍必须走候选和人工审核链路。"""
    response = client.post("/api/v1/admin/model-candidates", json=value)
    if response.status_code != 201:
        return response
    row = response.json()
    cases = {key: "synthetic-test-evidence" for key in row["required_cases"]}
    return client.post(
        f"/api/v1/admin/model-candidates/{row['id']}/activate",
        json={
            "expected_revision": value["expected_revision"],
            "candidate_digest": row["digest"],
            "confirmed": True,
            "cases": cases,
            "actual_cost_cny": 0,
            "bill_reference": "synthetic-zero-network",
            "review_note": "synthetic-isolated-unit-review",
        },
    )


def test_model_settings_permission_secret_and_stale_write(client, app, monkeypatch):
    """未授权不能读写，发布只保存白名单；密钥值不进入配置/审计/公开目录。"""
    monkeypatch.setenv("AI302_API_KEY", "synthetic-private-test-key")
    login(client)
    assert client.get(PATH).status_code == 401
    assert client.put(PATH, json={}).status_code == 401
    admin(client)
    value = body(client, enabled=True)
    value["llm"]["enabled"] = True
    assert value["image"]["quality"] == "low" and value["llm"]["model"] == "claude-sonnet-5-5"
    saved = approved_publish(client, value)
    assert saved.status_code == 200, saved.text
    assert saved.json()["revision"] == 1 and saved.json()["credentials_present"]
    assert approved_publish(client, value).json()["error"]["code"] == "REVISION_CONFLICT"
    invalid = body(client)
    invalid["image"]["api_key"] = "must-not-be-accepted"
    assert approved_publish(client, invalid).status_code == 422
    published = client.get(PATH).json()
    inventory = client.get("/api/v1/admin/catalog").json()
    audit = client.get("/api/v1/admin/audit").json()
    assert "synthetic-private-test-key" not in json.dumps([published, inventory, audit])
    with app.state.sessions() as db:
        assert "synthetic-private-test-key" not in json.dumps(db.scalar(select(ModelRelease)).providers_json)


def test_model_settings_missing_credentials_rejects_enable(client, monkeypatch):
    """显式空环境值优先于用户 dotenv；缺密钥不允许发布真实模型。"""
    monkeypatch.setenv("AI302_API_KEY", "")
    admin(client)
    value = body(client, enabled=True)
    assert approved_publish(client, value).json()["error"]["code"] == "PROVIDER_CREDENTIALS_MISSING"
    assert client.get(PATH).json()["revision"] == 0


def test_image_switch_preserves_accepted_provider_and_blocks_stale_plan(client, app, monkeypatch):
    """换质量后未确认计划失效，已确认计划的插件与配置哈希持续可用。"""
    monkeypatch.setenv("AI302_API_KEY", "synthetic")
    admin(client)
    assert approved_publish(client, body(client, enabled=True)).status_code == 200
    login(client)
    project, _, first = prepare(client)
    jobs = accept(client, first).json()["job_ids"]
    old_policy = app.state.gateway.image_policy("reference")
    second = save_plan(client, project)
    assert approved_publish(client, body(client, quality="medium")).status_code == 200
    new_policy = app.state.gateway.image_policy("reference")
    assert old_policy != new_policy
    assert app.state.gateway.snapshot("image", old_policy["provider_id"]) == old_policy
    assert accept(client, second).json()["error"]["code"] == "PROVIDER_CONFIG_CHANGED"
    called = []

    def submit(request):
        """只记录旧任务实际进入的插件，不调用网络。"""
        called.append(request.request_key)
        return ImageSubmission("existing-task")

    app.state.gateway.get("image", old_policy["provider_id"]).submit = submit
    assert process_job(app, jobs[0]) and called == [jobs[0]]
    with app.state.sessions() as db:
        assert db.get(Job, jobs[0]).provider_id == old_policy["provider_id"]


def test_llm_only_change_does_not_invalidate_image_or_repeat_identical_release(client, app, monkeypatch):
    """改语言模型不改变图片插件 ID；相同表单保存不会制造新发布。"""
    monkeypatch.setenv("AI302_API_KEY", "synthetic")
    admin(client)
    value = body(client, enabled=True)
    value["llm"]["enabled"] = True
    assert approved_publish(client, value).status_code == 200
    old_policy = app.state.gateway.image_policy("text")
    value = body(client)
    value["llm"]["max_tokens"] = 256
    saved = approved_publish(client, value)
    assert saved.status_code == 200 and saved.json()["revision"] == 2
    assert app.state.gateway.image_policy("text") == old_policy
    same = approved_publish(client, body(client))
    assert same.json()["revision"] == 2
    with app.state.sessions() as db:
        assert db.scalar(select(func.count()).select_from(ModelRelease)) == 2


def test_two_instances_refresh_and_keep_old_versions(client, app, monkeypatch):
    """独立 API/Worker 实例从共享数据库发现新指针，历史定义仍可读取。"""
    monkeypatch.setenv("AI302_API_KEY", "synthetic")
    other = create_app(app.state.settings, engine=app.state.engine)
    admin(client)
    assert approved_publish(client, body(client, enabled=True)).status_code == 200
    first = other.state.gateway.image_policy("text")
    assert first == app.state.gateway.image_policy("text")
    assert approved_publish(client, body(client, text_model="future-gpt-image")).status_code == 200
    assert other.state.gateway.image_policy("text") != first
    assert other.state.gateway.snapshot("image", first["provider_id"]) == first


def test_concurrent_model_publication_one_wins(client, app):
    """相同 expected_revision 只能有一个发布提交，另一方不能覆盖。"""
    admin(client)
    value = body(client)
    with ThreadPoolExecutor(2) as executor:
        results = list(executor.map(lambda _: approved_publish(client, value), range(2)))
    assert sorted(result.status_code for result in results) == [200, 409]
    with app.state.sessions() as db:
        assert db.scalar(select(func.count()).select_from(ModelRelease)) == 1


def test_model_inventory_redacts_and_rejects_bad_ids(client, monkeypatch):
    """只返回账号可见模型 ID，不把任意上游字段当成浏览器配置。"""
    monkeypatch.setenv("AI302_API_KEY", "synthetic")
    admin(client)
    real = httpx.Client

    def handle(request):
        """只允许官方模型列表端点，不接受浏览器指定 URL。"""
        assert str(request.url) == "https://api.302.ai/v1/models"
        return httpx.Response(
            200,
            json={
                "data": [
                    {"id": "gpt-image-2", "secret": "private"},
                    {"id": "claude-sonnet-5-5"},
                    {"id": "<script>"},
                ]
            },
        )

    monkeypatch.setattr(
        "app.modules.operations.model_settings.httpx.Client",
        lambda **kwargs: real(transport=httpx.MockTransport(handle), **kwargs),
    )
    result = client.get(PATH + "/models")
    assert result.json() == {"models": ["claude-sonnet-5-5", "gpt-image-2"]}
