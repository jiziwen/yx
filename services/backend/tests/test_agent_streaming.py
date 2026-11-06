"""真实传输协议替身与业务屏障：前缀不是正式消息，断流不重发、不触发图片。"""

import json

import httpx
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select
from test_agent import install, proposal, send, snapshot
from test_conversation_events import decode, request_for
from test_creative_flow import create_project, login

from app.core.config import Settings
from app.integrations.contracts import LLMResult, ProviderFailure
from app.integrations.openai_compatible import CompatibleLLM
from app.modules.agents.models import AgentRun
from app.modules.agents.streaming import reply_prefix
from app.modules.conversations.events import changes, read_stamp
from app.modules.executions.models import Approval, Plan
from app.modules.media_jobs.models import Job
from app.modules.projects.models import Project
from app.workers.agent_runtime import maintain_runs, process_run


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('{"outcome":"answer","reply":"你好，', "你好，"),
        ('{"outcome":"answer","reply":"\\u4f60\\u597', "你"),
        ('{"outcome":"answer","reply":"你好\\', "你好"),
        ('{"outcome":"answer","reply":"你好\\uD83D', "你好"),
        ('{"outcome":"answer","reply":"你好\\uD83D\\uDE0A', "你好😊"),
        ('{"outcome":"answer","reply":"换行\\n引号\\"', '换行\n引号"'),
        ('{"outcome":"answer","reply":"\\uDC00', None),
        ('{"outcome":"answer","reply":"\\uD83D\\u0041', None),
        ('{"tool_calls":[{"arguments":{"reply":"秘密"}}]}', None),
        ('{"reply":"无outcome不得显示', None),
        ('{"thought":{"reply":"秘密"},"outcome":"answer","reply":"可见', "可见"),
        ('{"outcome":"answer","tool_calls":[],"reply":"混合请求', None),
        ('```json\n{"outcome":"answer","reply":"代码围栏', None),
        ('{"outcome":"answer","reply":"坏\\q', None),
    ],
)
def test_partial_json_extracts_only_visible_reply(raw, expected):
    """任意边界的 Unicode/转义完整性、顶层字段与工具/嵌套内容隔离。"""
    assert reply_prefix(raw) == expected


class SplitBytes(httpx.SyncByteStream):
    """模拟网络任意字节分片，包括多字节中文被拆开。"""

    def __init__(self, data, broken=False):
        """仅持有合成响应，不读取网络或环境凭证。"""
        self.data, self.broken = data, broken

    def __iter__(self):
        """以非行边界推送字节，最后可模拟断流。"""
        for index in range(0, len(self.data), 7):
            yield self.data[index : index + 7]
        if self.broken:
            raise httpx.ReadError("synthetic disconnection")


def event(content=None, finish=None, **extra):
    """供应商 SSE 测试帧，可插入隐藏字段但业务不可展示。"""
    delta = {"content": content} if content is not None else {}
    delta.update(extra)
    return (
        "data: "
        + json.dumps({"choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}, ensure_ascii=False)
        + "\n\n"
    )


def transport_provider(monkeypatch, data, *, broken=False, status=200):
    """用 MockTransport 隔离真实 HTTP；保留 Client.stream/iter_lines 的实际解析。"""
    monkeypatch.setenv("STREAM_TEST_KEY", "synthetic-key")
    original, requests = httpx.Client, []

    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(
            status, headers={"content-type": "text/event-stream"}, stream=SplitBytes(data.encode(), broken)
        )

    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs)
    )
    provider = CompatibleLLM(
        {
            "model": "synthetic-stream-model",
            "base_url": "https://local.test/v1",
            "api_key_env": "STREAM_TEST_KEY",
        },
        Settings(app_env="test"),
    )
    return provider, requests


def test_compatible_stream_content_usage_and_utf8(monkeypatch):
    """真正逐帧消费，不透传 reasoning/tool_calls；终态用量正确且只发一次请求。"""
    raw = json.dumps(proposal(), ensure_ascii=False)
    wire = ": heartbeat\n\n" + event(reasoning_content="隐藏内容", tool_calls=[{"arguments": "秘密参数"}])
    wire += "".join(event(raw[i : i + 9]) for i in range(0, len(raw), 9))
    wire += (
        event(finish="stop")
        + 'data: {"choices":[],"usage":{"prompt_tokens":12,"completion_tokens":30,"total_tokens":42,"private":"secret"}}\n\ndata: [DONE]\n\n'
    )
    provider, requests = transport_provider(monkeypatch, wire)
    chunks = []
    result = provider.stream_complete([], chunks.append, timeout_seconds=10)
    assert "".join(chunks) == raw and result.data == proposal()
    assert result.usage == {"prompt_tokens": 12, "completion_tokens": 30, "total_tokens": 42}
    assert len(chunks) > 5 and "隐藏内容" not in str(chunks) and "秘密参数" not in str(chunks)
    assert len(requests) == 1 and requests[0]["stream"] is True
    assert requests[0]["stream_options"] == {"include_usage": True}


@pytest.mark.parametrize(
    ("wire", "broken", "status", "code"),
    [
        (event('{"outcome":"answer","reply":"片段'), True, 200, "PROVIDER_RESULT_UNKNOWN"),
        (event('{"outcome":"answer","reply":"完整但未结束"}'), False, 200, "PROVIDER_RESULT_UNKNOWN"),
        (event("{}") + event(finish="length"), False, 200, "PROVIDER_INVALID_OUTPUT"),
        ('data: {"error":{"message":"secret"}}\n\n', False, 200, "PROVIDER_RESULT_UNKNOWN"),
        ("data: {invalid-json}\n\n", False, 200, "PROVIDER_RESULT_UNKNOWN"),
        ("", False, 429, "PROVIDER_RATE_LIMITED"),
        ("secret credential", False, 401, "PROVIDER_AUTH_FAILED"),
        ("", False, 500, "PROVIDER_RESULT_UNKNOWN"),
    ],
)
def test_compatible_stream_failure_does_not_fallback(monkeypatch, wire, broken, status, code):
    """不完整/限流/未知结果只报稳定分类，不补发非流式调用。"""
    provider, requests = transport_provider(monkeypatch, wire, broken=broken, status=status)
    with pytest.raises(ProviderFailure) as failure:
        provider.stream_complete([], lambda _: None)
    assert failure.value.code == code and len(requests) == 1


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize(
    "status,code",
    [
        (400, "PROVIDER_INVALID_REQUEST"),
        (401, "PROVIDER_AUTH_FAILED"),
        (402, "PROVIDER_BALANCE_INSUFFICIENT"),
        (403, "PROVIDER_PERMISSION_DENIED"),
        (404, "PROVIDER_MODEL_UNAVAILABLE"),
        (422, "PROVIDER_INVALID_REQUEST"),
        (409, "PROVIDER_REJECTED"),
    ],
)
def test_http_rejections_are_classified_without_body_or_retry(monkeypatch, streaming, status, code):
    """流式与完整响应使用同一安全错误分类，保留输入而不盲目重发。"""
    provider, requests = transport_provider(monkeypatch, "secret: synthetic-key", status=status)
    with pytest.raises(ProviderFailure) as failure:
        if streaming:
            provider.stream_complete([], lambda _: pytest.fail("error must not stream"))
        else:
            provider.complete([])
    assert failure.value.code == code and not failure.value.unknown and len(requests) == 1
    assert "synthetic-key" not in str(failure.value)


class StreamingScript:
    """有控制点的可插拔流式模型，供业务取消和跨进程事实验收。"""

    def __init__(self, action):
        """一次调用由场景提供前缀、最终响应和中途变化。"""
        self.action, self.calls = action, 0

    def draft(self, messages):
        """意外降级应直接失败，防止测试掩盖重复请求。"""
        raise AssertionError("unexpected non-stream fallback")

    def stream_complete(self, messages, on_content, timeout_seconds=None):
        """调用真正的 Worker 回调，不直接篡改临时回复表。"""
        self.calls += 1
        return LLMResult(self.action(self.calls, on_content))


def test_worker_preview_commits_atomically_and_sse_restores(client, app):
    """运行中可读前缀与 SSE，完成后临时字被单条正式回复替换，零图片副作用。"""
    login(client)
    project = create_project(client)
    request = request_for(client, app)

    def action(_attempt, output):
        output('{"outcome":"plan_ready","reply":"正在一起整理')
        current = snapshot(client, project)
        preview = current["runs"][0]["reply_preview"]
        assert preview["text"] == "正在一起整理" and preview["attempt_no"] == 1
        assert len(current["messages"]) == 1
        stamp = read_stamp(request, project["id"])
        assert stamp.previews[run["id"]] == preview
        deltas = [
            decode(item)[1]
            for item in changes(initial, stamp, project["id"])
            if decode(item)[0] == "message.delta"
        ]
        assert deltas[0]["payload"]["preview"]["text"] == "正在一起整理"
        assert app.state.engine.pool.checkedout() == 0
        return proposal()

    provider = StreamingScript(action)
    app.state.gateway.providers["local-llm"] = provider
    run, _ = send(client, project)
    initial = read_stamp(request, project["id"])
    assert process_run(app, run["id"])
    view = snapshot(client, project)
    assert len(view["messages"]) == 2 and view["runs"][0]["reply_preview"] is None
    assert view["messages"][-1]["text"] == proposal()["reply"]
    assert provider.calls == 1
    with app.state.sessions() as db:
        assert db.get(AgentRun, run["id"]).stream_json is None
        assert all(db.scalar(select(func.count()).select_from(model)) == 0 for model in (Plan, Approval, Job))


@pytest.mark.parametrize("barrier", ["cancel", "privacy", "memory"])
def test_worker_stream_cannot_publish_after_barrier(client, app, barrier):
    """已显示片段不能变成取消/撤销/记忆变更后的最终消息，也不恢复临时内容。"""
    login(client)
    project = create_project(client)

    def action(_attempt, output):
        output('{"outcome":"plan_ready","reply":"正在整理')
        assert snapshot(client, project)["runs"][0]["reply_preview"]
        if barrier == "cancel":
            assert client.post(f"/api/v1/web/agent-runs/{run['id']}/cancel").status_code == 200
        elif barrier == "privacy":
            with app.state.sessions() as db:
                db.get(Project, project["id"]).privacy_epoch += 1
                db.commit()
        else:
            assert (
                client.put(
                    f"/api/v1/web/projects/{project['id']}/memory",
                    json={"expected_revision": 0, "expected_privacy_epoch": 0, "requirements": ["不要水印"]},
                ).status_code
                == 200
            )
        output("新的要求")
        return proposal()

    app.state.gateway.providers["local-llm"] = StreamingScript(action)
    run, _ = send(client, project)
    assert not process_run(app, run["id"])
    maintain_runs(app)
    view = snapshot(client, project)
    assert not [m for m in view["messages"] if m["role"] == "assistant"]
    with app.state.sessions() as db:
        current = db.get(AgentRun, run["id"])
        assert current.stream_json is None
        assert current.calls == 1


def test_stream_repair_is_new_attempt_and_unknown_is_not_replayed(client, app, monkeypatch):
    """格式修正更换尝试，不承接旧文字；网络断流没有修正或非流式补发。"""
    login(client)
    project = create_project(client)
    seen = []

    def action(attempt, output):
        assert snapshot(client, project)["runs"][-1]["reply_preview"] is None
        output('{"outcome":"plan_ready","reply":"' + ("旧草稿" if attempt == 1 else "新草稿"))
        seen.append(snapshot(client, project)["runs"][-1]["reply_preview"])
        return proposal(count=9) if attempt == 1 else proposal()

    app.state.gateway.providers["local-llm"] = StreamingScript(action)
    run, _ = send(client, project)
    assert process_run(app, run["id"])
    assert [value["attempt_no"] for value in seen] == [1, 2]
    assert [value["text"] for value in seen] == ["旧草稿", "新草稿"]
    provider, requests = transport_provider(
        monkeypatch, event('{"outcome":"answer","reply":"中断'), broken=True
    )
    app.state.gateway.providers["local-llm"] = provider
    run, _ = send(client, project)
    assert not process_run(app, run["id"])
    state = snapshot(client, project)["runs"][-1]
    assert state["error_code"] == "PROVIDER_RESULT_UNKNOWN" and state["calls"] == 1
    assert state["reply_preview"] is None and len(requests) == 1


def test_stream_migration_preserves_final_messages(client, app):
    """回退仅移除临时回复；恢复后旧 Run 预览为 null，正式消息保留。"""
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
    command.downgrade(Config("alembic.ini"), "ffba47dfea56")
    command.upgrade(Config("alembic.ini"), "head")
    command.check(Config("alembic.ini"))
    state = snapshot(client, project)
    assert len(state["messages"]) == 2 and state["runs"][0]["reply_preview"] is None
