"""原生 GPT 图片适配器契约：low 必须实际进入请求，查询不重复生成。"""

import base64
import json

import pytest
from test_creative_flow import image_bytes

from app.integrations.ai302_gpt import AI302GPTImage
from app.integrations.contracts import ImageRequest


@pytest.mark.parametrize("operation", ["text", "reference", "edit"])
def test_native_quality_and_role_order(app, monkeypatch, operation):
    """文生图与 multipart 编辑均固定 n=1、质量 low，并保持输入顺序。"""
    monkeypatch.setenv("AI302_API_KEY", "synthetic")
    provider = AI302GPTImage(
        {
            "models": {"text": "gpt-image-2", "reference": "gpt-image-2", "edit": "gpt-image-2"},
            "quality": "low",
        },
        app.state.settings,
    )
    captured = []

    def request(method, path, **kwargs):
        """记录适配器边界，不发付费调用。"""
        captured.append((method, path, kwargs))
        return {"task_id": "native-test"}

    provider._request = request
    references = () if operation == "text" else (b"base", b"person")
    provider.submit(ImageRequest("test", "3:4", references, "request-key", operation=operation))
    _, path, kwargs = captured[0]
    body = kwargs.get("json", kwargs.get("data"))
    assert body["quality"] == "low" and body["size"] == "768x1024" and str(body["n"]) == "1"
    assert kwargs["params"]["async"] == "true" and "input_fidelity" not in body
    if operation != "text":
        assert path == "/v1/images/edits" and [item[1][1] for item in kwargs["files"]] == list(references)


@pytest.mark.parametrize("serialized", [False, True])
def test_native_result_wrapper_and_usage(app, monkeypatch, serialized):
    """302 返回字典或序列化 JSON 都读取同一结果，用量不包含原始提示词。"""
    monkeypatch.setenv("AI302_API_KEY", "synthetic")
    provider = AI302GPTImage({"models": {"text": "gpt-image-2"}}, app.state.settings)
    payload = {
        "data": [{"b64_json": base64.b64encode(image_bytes()).decode()}],
        "usage": {"total_tokens": 123, "private": "hidden"},
    }
    provider._request = lambda *a, **k: {
        "status_code": 200,
        "err": "",
        "data": json.dumps(payload) if serialized else payload,
    }
    result = provider.lookup("native-test", "key")
    assert result.status == "succeeded" and result.result.content == image_bytes()
    assert result.result.usage == {"total_tokens": 123}


def test_native_unknown_never_means_failure(app, monkeypatch):
    """未知/错误状态保留核对，不推测远端明确失败来释放次数。"""
    monkeypatch.setenv("AI302_API_KEY", "synthetic")
    provider = AI302GPTImage({"models": {"text": "gpt-image-2"}}, app.state.settings)
    provider._request = lambda *a, **k: {"status_code": 500, "err": "not ready"}
    assert provider.lookup("native-test", "key").status == "unknown"


@pytest.mark.parametrize("operation", ["text", "edit"])
def test_native_sends_arbitrary_pixels_without_local_size_limits(app, monkeypatch, operation):
    """明确尺寸超过旧边长上限且不是16倍数，JSON/multipart仍原样发送。"""
    monkeypatch.setenv("AI302_API_KEY", "synthetic")
    provider = AI302GPTImage(
        {
            "models": {"text": "gpt-image-2", "edit": "gpt-image-2"},
            "size_by_aspect_ratio": {"3:4": "768x1024"},
        },
        app.state.settings,
    )
    captured = []

    def request(method, path, **kwargs):
        """记录供应商请求边界，不触发付费调用。"""
        captured.append(kwargs)
        return {"task_id": "arbitrary-size-test"}

    provider._request = request
    provider.submit(
        ImageRequest(
            "场景",
            "4097:513",
            () if operation == "text" else (b"base",),
            "key",
            operation=operation,
            size="4097x513",
        )
    )
    assert captured[0].get("json", captured[0].get("data"))["size"] == "4097x513"


def test_native_unlisted_ratio_and_nonstandard_mapping_are_not_rejected(app, monkeypatch):
    """不声明画幅映射也能使用任意比例，自定义尺寸配置不套供应商限制。"""
    monkeypatch.setenv("AI302_API_KEY", "synthetic")
    provider = AI302GPTImage(
        {"models": {"text": "gpt-image-2"}, "size_by_aspect_ratio": {"101:150": "202x300"}},
        app.state.settings,
    )
    requests = []

    def request(method, path, **kwargs):
        """仅收集待发送JSON。"""
        requests.append(kwargs["json"])
        return {"task_id": "unlisted-ratio-test"}

    provider._request = request
    for ratio in ["7:5", "101:150", "9:16"]:
        provider.submit(ImageRequest("场景", ratio, (), "key", operation="text"))
    assert [request["size"] for request in requests] == ["1022x730", "202x300", "864x1536"]
