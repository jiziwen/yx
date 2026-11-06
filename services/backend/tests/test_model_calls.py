"""模型日志权限、逐次记录、真实HTTP入出参、流式恢复、分页及隐私屏障。"""

import json
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from sqlalchemy import func, select
from test_agent_streaming import event, transport_provider
from test_creative_flow import create_project, image_bytes, login
from test_model_settings import admin

from app.integrations.ai302_gpt import AI302GPTImage
from app.integrations.call_logging import bounded, call_scope
from app.integrations.contracts import (
    AsyncImageProvider,
    ImageProvider,
    ImageRequest,
    ProviderFailure,
    StreamingLLMProvider,
)
from app.integrations.openai_compatible import CompatibleLLM
from app.modules.identity.models import User
from app.modules.operations.models import Audit, ModelCall
from app.modules.projects.models import Project

PATH = "/api/v1/admin/model-calls"


def rows(app):
    """读取已落库事实，避免只验证页面模拟数据。"""
    with app.state.sessions() as db:
        return list(db.scalars(select(ModelCall).order_by(ModelCall.created_at, ModelCall.id)))


def observed(app, provider, kind="llm", context=None):
    """与网关共用装饰器，HTTP以本地传输替换，不请求真实供应商。"""
    return app.state.model_calls.wrap(provider, "test-provider", {"kind": kind}, context)


def test_gateway_single_record_and_protocol_preserved(app):
    """draft内部调用complete不重复；原有可选协议保持真实能力。"""

    class ScriptedLLM:
        """只验证插件代理，输出固定且不依赖创作图状态。"""

        def draft(self, messages):
            return self.complete(messages)

        def complete(self, messages):
            return {"reply": "整理好了"}

        def stream_complete(self, messages, on_content, timeout_seconds=None):
            return self.complete(messages)

    app.state.gateway.providers[app.state.gateway.routes["llm"]] = ScriptedLLM()
    llm = app.state.gateway.get("llm")
    assert isinstance(llm, StreamingLLMProvider)
    llm.draft([{"role": "user", "content": "只整理需求"}])
    image = app.state.gateway.get("image")
    assert isinstance(image, ImageProvider) and not isinstance(image, AsyncImageProvider)
    assert len(rows(app)) == 1 and rows(app)[0].development_sample
    assert rows(app)[0].request_json["messages"][0]["content"] == "只整理需求"
    assert rows(app)[0].response_json
    app.state.gateway.get("storage").put("test.txt", b"file")
    assert len(rows(app)) == 1


@pytest.mark.parametrize("kind", ["llm", "vision"])
def test_real_http_input_output_and_failed_response(app, monkeypatch, kind):
    """保存真实请求参数和脱敏响应；401不透明重发，失败也留一条。"""
    key = "synthetic-private-key-123"
    monkeypatch.setenv("CALL_TEST_KEY", key)
    requests = []
    original = httpx.Client

    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(
            200 if len(requests) == 1 else 401,
            json={
                "choices": [{"message": {"content": '{"reply":"整理好了"}'}, "finish_reason": "stop"}],
                "usage": {"total_tokens": 7},
                "echo": key,
                "Authorization": "Bearer " + key,
                "reasoning_content": "不应记录的隐藏推理",
            },
        )

    monkeypatch.setattr(httpx, "Client", lambda **kw: original(transport=httpx.MockTransport(handler), **kw))
    provider = observed(
        app,
        CompatibleLLM(
            {
                "model": "test-call-model",
                "base_url": "https://local.test/v1",
                "api_key_env": "CALL_TEST_KEY",
                "max_tokens": 256,
            },
            app.state.settings,
        ),
        kind=kind,
    )
    provider.complete([{"role": "user", "content": "柔光"}])
    with pytest.raises(ProviderFailure, match="PROVIDER_AUTH_FAILED"):
        provider.complete([{"role": "user", "content": "第二次"}])
    success, failed = rows(app)
    assert len(requests) == 2
    assert success.request_json["json"] == requests[0] and success.http_status == 200
    assert success.response_json["usage"]["total_tokens"] == 7
    assert key not in str(success.response_json) and "不应记录的隐藏推理" not in str(success.response_json)
    assert (
        failed.status == "failed"
        and failed.http_status == 401
        and failed.error_code == "PROVIDER_AUTH_FAILED"
    )
    assert key not in str(failed.response_json)


@pytest.mark.parametrize("broken", [False, True])
def test_stream_records_final_or_partial_without_duplicate(app, monkeypatch, broken):
    """断流保留已收片段；完整流合并输出并记录用量，没有第二次模型调用。"""
    wire = event('{"reply":"柔光')
    if not broken:
        wire += (
            event('人像"}')
            + event(finish="stop")
            + 'data: {"choices":[],"usage":{"total_tokens":12}}\n\ndata: [DONE]\n\n'
        )
    provider, requests = transport_provider(monkeypatch, wire, broken=broken)
    wrapped = observed(app, provider)
    chunks = []
    if broken:
        with pytest.raises(ProviderFailure):
            wrapped.stream_complete([], chunks.append)
    else:
        wrapped.stream_complete([], chunks.append)
    row = rows(app)[0]
    assert len(requests) == 1 and len(rows(app)) == 1
    assert row.request_json["json"]["stream"] is True
    assert row.response_json["content"] == "".join(chunks)
    assert row.status == ("failed" if broken else "succeeded")
    assert row.result_unknown == broken


def test_async_image_wire_quality_and_binary_omission(app, monkeypatch):
    """图片提交与查询分别计次，low实际入参可见，不落原图或base64。"""
    monkeypatch.setenv("AI302_API_KEY", "synthetic-key")
    original = httpx.Client
    calls = []

    def handler(request):
        calls.append(request.url.path)
        if request.method == "POST":
            return httpx.Response(200, json={"task_id": "call-task"})
        return httpx.Response(
            200,
            json={
                "status_code": 200,
                "data": {"data": [{"b64_json": __import__("base64").b64encode(image_bytes()).decode()}]},
            },
        )

    monkeypatch.setattr(httpx, "Client", lambda **kw: original(transport=httpx.MockTransport(handler), **kw))
    raw = AI302GPTImage({"models": {"reference": "gpt-image-2"}, "quality": "low"}, app.state.settings)
    wrapped = app.state.model_calls.wrap(
        raw, "image-test", {"kind": "image", "options": {"models": raw.models}}
    )
    assert isinstance(wrapped, AsyncImageProvider) and not isinstance(wrapped, ImageProvider)
    wrapped.submit(ImageRequest("替换人物", "3:4", (image_bytes(),), "job-key"))
    wrapped.lookup("call-task", "job-key")
    submitted, fetched = rows(app)
    assert len(calls) == 2 and submitted.model == "gpt-image-2"
    assert submitted.request_json["data"]["quality"] == "low"
    binary = submitted.request_json["files"][0][1][1]
    assert binary["omitted"] == "binary" and binary["bytes"] == len(image_bytes())
    assert fetched.response_json["data"]["data"][0]["b64_json"]["omitted"] == "base64"


def test_admin_only_fixed_twenty_pagination_and_detail_audit(client, app):
    """匿名、客户及员工不得读正文；每页固定20条，稳定排序不丢最后一页。"""
    assert client.get(PATH).status_code == 401
    login(client)
    assert client.get(PATH).status_code == 401
    for i in range(21):
        with pytest.raises(IndexError):
            # 故意缺少开发图所需上下文，失败的调用同样必须进入分页记录。
            app.state.gateway.get("llm").draft([{"role": "user", "content": f"请求{i}"}])
    admin(client)
    first = client.get(PATH).json()
    second = client.get(PATH, params={"page": 2}).json()
    assert first["total"] == 21 and first["page_size"] == 20 and first["total_pages"] == 2
    assert len(first["items"]) == 20 and len(second["items"]) == 1
    assert not {r["id"] for r in first["items"]} & {r["id"] for r in second["items"]}
    assert "request" not in str(first) and "response_json" not in str(first)
    call_id = first["items"][0]["id"]
    detail = client.get(PATH + "/" + call_id)
    assert detail.status_code == 200 and detail.json()["request"] and detail.json()["response"] is None
    assert client.get(PATH, params={"page": 0}).status_code == 422
    assert client.get(PATH, params={"page": 3}).json()["items"] == []
    assert client.get(PATH + "/unknown").status_code == 404
    with app.state.sessions() as db:
        assert (
            db.scalar(select(func.count()).select_from(Audit).where(Audit.action == "model_call.read")) == 1
        )
        user = db.scalar(select(User).where(User.role == "admin"))
        user.role = "staff"
        db.commit()
    assert client.get(PATH).status_code == 403
    assert client.get(PATH + "/" + call_id).status_code == 403


def test_project_revocation_and_late_return_do_not_restore_content(client, app):
    """调用中撤销授权：最终日志仍有状态，但正文不可复活。"""
    customer = login(client)
    project = create_project(client)
    context = {"project_id": project["id"], "owner_user_id": customer["id"], "privacy_epoch": 0}
    with app.state.sessions() as db:
        context["privacy_epoch"] = db.get(Project, project["id"]).privacy_epoch

    class RevokeDuringCall:
        """模拟上游迟到回包。"""

        def draft(self, messages):
            with app.state.sessions() as db:
                p = db.get(Project, project["id"])
                p.privacy_epoch += 1
                db.commit()
            return {"reply": "私有内容"}

    observed(app, RevokeDuringCall(), context=context).draft([{"content": "私有需求"}])
    row = rows(app)[0]
    assert row.request_json == row.response_json == {"scrubbed": True}
    admin(client)
    data = client.get(PATH + "/" + row.id).json()
    assert data["scrubbed"] and "私有" not in str(data)


def test_concurrent_contexts_and_embedding(app):
    """并发ContextVar隔离；嵌套向量插件保留用户范围并落库。"""
    from app.modules.knowledge.service import embedder

    def run(value):
        with call_scope({"run_id": str(value)}):
            return embedder(app).embed([f"知识{value}"])

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert len(list(pool.map(run, range(2)))) == 2
    result = rows(app)
    assert len(result) == 2 and {r.run_id for r in result} == {"0", "1"}
    assert all(r.kind == "embedding" and r.status == "succeeded" for r in result)


def test_payload_bounds_and_redaction():
    """敏感字段、带签名链接、dataURL及超大响应均可预期地省略。"""
    payload = bounded(
        {
            "api_key": "secret",
            "url": "https://user:pwd@example.com/result?token=secret",
            "image": "data:image/png;base64,AAA",
            "many": ["x" * 64000] * 10,
        }
    )
    raw = json.dumps(payload)
    assert len(raw.encode()) <= 256_000
    assert "token=secret" not in raw and "user:pwd" not in raw and '"secret"' not in raw
    assert "truncated" in raw and "data_url" in raw


def test_actual_agent_run_links_log_to_project(client, app):
    """从真实排队/Worker路径走一轮，调用正文与项目/用户/Run可关联。"""
    from test_agent import install, proposal, send

    from app.workers.agent_runtime import process_run

    customer = login(client)
    project = create_project(client)
    install(app, [proposal()])
    run, _ = send(client, project, "需要柔和的光线")
    assert process_run(app, run["id"])
    row = rows(app)[0]
    assert row.project_id == project["id"] and row.owner_user_id == customer["id"] and row.run_id == run["id"]
    assert row.status == "succeeded" and "需要柔和的光线" in str(row.request_json)
    admin(client)
    assert client.get(PATH + "/" + row.id).json()["scrubbed"] is False
    assert (
        client.request(
            "DELETE", f"/api/v1/web/projects/{project['id']}", json={"confirmed": True}
        ).status_code
        == 200
    )
    with app.state.sessions() as db:
        saved = db.get(ModelCall, row.id)
        assert saved.request_json == saved.response_json == {"scrubbed": True}


def test_model_call_migration_refuses_lossy_downgrade(app):
    """有调用证据禁止无意回退；隔离库显式归档后才能做往返验收。"""
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import delete

    with pytest.raises(IndexError):
        app.state.gateway.get("llm").draft([])
    configuration = Config("alembic.ini")
    with pytest.raises(RuntimeError, match="explicit archival"):
        command.downgrade(configuration, "f36c10421b22")
    assert len(rows(app)) == 1
    with app.state.sessions() as db:
        db.execute(delete(ModelCall))
        db.commit()
    command.downgrade(configuration, "f36c10421b22")
    command.upgrade(configuration, "head")
    command.check(configuration)


def add_call(db, index, *, job_id="image-job", provider_id="image-provider", epoch=None, **values):
    """历史逐次日志夹具；测试合并不依赖新增迁移或付费供应商。"""
    from datetime import datetime, timedelta, timezone

    row = ModelCall(
        id=f"historical-{index:04d}",
        created_at=datetime(2026, 10, 23, tzinfo=timezone.utc) + timedelta(seconds=index),
        provider_id=provider_id,
        kind="image",
        model="gpt-image-2",
        operation="lookup",
        status="succeeded",
        development_sample=False,
        job_id=job_id,
        privacy_epoch=epoch,
        request_json={"method": "GET", "params": {"task_id": "original-task"}},
        response_json={"status_code": 102},
        http_status=200,
        latency_ms=100,
    )
    for name, value in values.items():
        setattr(row, name, value)
    db.add(row)
    return row


def test_image_history_grouped_before_pagination_and_original_prompt(client, app):
    """超过一页的轮询只占一行，任意旧查询详情都可找回原始提示词。"""
    with app.state.sessions() as db:
        first = add_call(
            db,
            0,
            operation="submit",
            request_json={
                "method": "POST",
                "data": {"model": "gpt-image-2", "prompt": "真实图片提示词", "quality": "low"},
            },
            response_json={"task_id": "original-task"},
        )
        for i in range(1, 24):
            add_call(db, i)
        latest = add_call(
            db, 24, response_json={"status_code": 200, "data": {"url": "https://example.test/output.png"}}
        )
        for i in range(25, 45):
            add_call(db, i, job_id=f"different-job-{i}", operation="generate")
        first_id, latest_id = first.id, latest.id
        db.commit()
    admin(client)
    page = client.get(PATH).json()
    assert page["total"] == 21 and page["total_pages"] == 2
    assert len(page["items"]) == 20
    second = client.get(PATH, params={"page": 2}).json()
    assert len(second["items"]) == 1
    merged = second["items"][0]
    assert merged["id"] == first_id and merged["call_count"] == 25 and merged["lookup_count"] == 24
    assert merged["latency_ms"] == 2500 and merged["latest_operation"] == "lookup"
    assert "request" not in merged and "response" not in merged
    # 从历史查询的旧ID进入，也必须先看到提交提示词和最新结果。
    detail = client.get(PATH + "/" + latest_id).json()
    assert detail["request"]["data"]["prompt"] == "真实图片提示词"
    assert detail["response"]["data"]["url"].endswith("output.png")
    assert detail["request_call_id"] == first_id and detail["response_call_id"] == latest_id
    assert len(detail["calls"]) == 20 and detail["calls_total_pages"] == 2
    assert all("request" not in call and "response" not in call for call in detail["calls"])
    older = client.get(PATH + "/" + first_id, params={"calls_page": 2}).json()
    assert len(older["calls"]) == 5 and older["calls"][-1]["id"] == first_id
    raw = client.get(PATH + "/" + latest_id + "/payload").json()
    assert raw["request"]["method"] == "GET" and "prompt" not in str(raw["request"])
    assert raw["response"] == detail["response"]
    assert client.get(PATH + "/" + first_id, params={"calls_page": 0}).status_code == 422
    assert client.get(PATH + "/unknown/payload").status_code == 404


def test_grouping_keeps_tasks_providers_privacy_epochs_and_non_images_separate(client, app):
    """相同模型不能把不同任务、插件或隐私代次合并；无Job记录也逐条保留。"""
    with app.state.sessions() as db:
        add_call(db, 0)
        add_call(db, 1)
        add_call(db, 2, job_id="other-job")
        add_call(db, 3, provider_id="other-provider")
        add_call(db, 4, epoch=1)
        add_call(db, 5, job_id=None)
        add_call(db, 6, job_id=None)
        add_call(db, 7, kind="llm", operation="complete")
        add_call(db, 8, kind="llm", operation="complete")
        db.commit()
    admin(client)
    page = client.get(PATH).json()
    assert page["total"] == 8
    assert sorted(row["call_count"] for row in page["items"]) == [1] * 7 + [2]
    detail = client.get(PATH + "/historical-0000").json()
    assert {row["id"] for row in detail["calls"]} == {"historical-0000", "historical-0001"}


def test_grouped_and_raw_payloads_respect_privacy_and_admin_only(client, app):
    """合并详情和单次详情均检查当前授权，调用汇总不得泄露其他代次。"""
    customer = login(client)
    project = create_project(client)
    with app.state.sessions() as db:
        epoch = db.get(Project, project["id"]).privacy_epoch
        for i in range(2):
            add_call(
                db,
                i,
                epoch=epoch,
                project_id=project["id"],
                owner_user_id=customer["id"],
                request_json={"prompt": "私有提示词"},
            )
        db.commit()
    assert client.get(PATH + "/historical-0000/payload").status_code == 401
    admin(client)
    assert "私有提示词" in client.get(PATH + "/historical-0000").text
    with app.state.sessions() as db:
        db.get(Project, project["id"]).privacy_epoch += 1
        db.commit()
    for suffix in ["", "/payload"]:
        response = client.get(PATH + "/historical-0000" + suffix)
        assert response.status_code == 200 and response.json()["scrubbed"]
        assert "私有提示词" not in response.text
    with app.state.sessions() as db:
        db.scalar(select(User).where(User.role == "admin")).role = "staff"
        db.commit()
    assert client.get(PATH + "/historical-0000/payload").status_code == 403


def test_actual_wire_prompt_persisted_before_send_and_actual_model(app):
    """发出请求前即可查到实际提示词；配置候选模型列表不能覆盖实际模型。"""
    from app.integrations.call_logging import wire_request, wire_response

    class InspectingImage:
        """模拟HTTP边界，读取独立事务以覆盖进程中断前的日志事实。"""

        def submit(self, request):
            wire_request(
                "POST",
                "https://example.test/generate",
                json={"model": "actual-image-model", "prompt": request.prompt},
            )
            row = rows(app)[0]
            assert row.status == "running" and row.request_json["json"]["prompt"] == request.prompt
            assert row.model == "actual-image-model" and row.response_json is None
            wire_response({"task_id": "original-task"}, 200)
            return {"task_id": "original-task"}

    wrapped = app.state.model_calls.wrap(
        InspectingImage(),
        "test-image",
        {"kind": "image", "options": {"models": {"text": "configured-text", "edit": "configured-edit"}}},
    )
    wrapped.submit(ImageRequest("发出前就保存提示词", "3:4", (), "job", operation="text"))
    assert rows(app)[0].model == "actual-image-model"
