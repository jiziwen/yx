"""300秒模型等待、外层预算与租约契约；使用MockTransport，不实际等待或调用供应商。"""

import json
from copy import deepcopy

import httpx
import pytest
from test_agent import install, send
from test_agent_streaming import event
from test_creative_flow import create_project, login

from app.core.db import now
from app.integrations.contracts import LLMResult
from app.integrations.openai_compatible import CompatibleImage, CompatibleLLM
from app.integrations.registry import Gateway
from app.modules.agents.models import AgentRun
from app.modules.media_jobs.governance import aware
from app.workers.agent_runtime import process_run


@pytest.mark.parametrize("streaming", [False, True])
def test_complete_and_stream_keep_300_second_http_timeout(app, monkeypatch, streaming):
    """同步与流式网络层不再被120秒硬上限截断。"""
    monkeypatch.setenv("TIMEOUT_TEST_KEY", "synthetic")
    original = httpx.Client
    timeouts = []
    output = {"outcome": "answer", "reply": "已完成"}

    def handler(request):
        """返回本地契约响应，禁止外部请求。"""
        if json.loads(request.content).get("stream"):
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                text=event(json.dumps(output)) + event(finish="stop") + "data: [DONE]\n\n",
            )
        return httpx.Response(
            200, json={"choices": [{"message": {"content": json.dumps(output)}, "finish_reason": "stop"}]}
        )

    def client(**kwargs):
        """记录传入HTTP客户端的实际等待值。"""
        timeouts.append(kwargs.get("timeout"))
        return original(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(httpx, "Client", client)
    provider = CompatibleLLM(
        {
            "model": "test",
            "base_url": "https://example.invalid/v1",
            "api_key_env": "TIMEOUT_TEST_KEY",
            "timeout_seconds": 300,
        },
        app.state.settings,
    )
    result = (
        provider.stream_complete([], lambda value: None, timeout_seconds=300)
        if streaming
        else provider.complete([], timeout_seconds=300)
    )
    assert result.data == output and timeouts == [300]


def test_old_release_sixty_seconds_does_not_override_agent_runtime_budget(app, monkeypatch):
    """历史发布保持原始定义，运行超时独立使用部署的300秒预算。"""
    monkeypatch.setenv("TIMEOUT_TEST_KEY", "synthetic")
    config = deepcopy(app.state.config)
    definition = config["providers"]["compatible-llm"]
    definition["enabled"] = True
    definition["options"].update(api_key_env="TIMEOUT_TEST_KEY", timeout_seconds=60)
    config["routes"]["llm"] = "compatible-llm"
    gateway = Gateway(config, app.state.settings)
    assert gateway.providers["compatible-llm"].timeout == 300
    assert gateway.definitions["compatible-llm"]["options"]["timeout_seconds"] == 60


def test_worker_reserves_full_call_wait_with_room_for_final_validation(client, app):
    """外层330秒，实际调用300秒，调用租约覆盖完整等待，测试不消耗真实时间。"""
    login(client)
    project = create_project(client)
    provider = install(app, [])
    observed = []

    def complete(messages, timeout_seconds=None):
        """在模型请求开始时观察冻结预算与实际租约。"""
        observed.append(timeout_seconds)
        with app.state.sessions() as db:
            active = db.get(AgentRun, run["id"])
            assert 300 < (aware(active.call_until) - now()).total_seconds() <= 305
            assert active.budget_json["request_timeout_seconds"] == 300
            assert (aware(active.deadline_at) - now()).total_seconds() > 300
        return LLMResult({"outcome": "answer", "reply": "已完成"})

    provider.complete = complete
    run, _ = send(client, project)
    assert process_run(app, run["id"])
    assert observed == [300]
    with app.state.sessions() as db:
        assert db.get(AgentRun, run["id"]).status == "succeeded"


def test_image_transport_timeout_remains_independent(app, monkeypatch):
    """增大语言模型等待不顺带改变图片网络限制。"""
    monkeypatch.setenv("TIMEOUT_TEST_KEY", "synthetic")
    provider = CompatibleImage(
        {
            "model": "test",
            "base_url": "https://example.invalid/v1",
            "api_key_env": "TIMEOUT_TEST_KEY",
            "timeout_seconds": 90,
        },
        app.state.settings,
    )
    assert provider.timeout == 90
