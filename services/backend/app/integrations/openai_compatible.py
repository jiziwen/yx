"""可配置 HTTP 兼容网关；部署者指定端点与模型，浏览器不能覆盖。"""

import base64
import json
import re
from time import monotonic

import httpx

from app.integrations.call_logging import response_body, wire_request, wire_response
from app.integrations.contracts import ImageRequest, ImageResult, LLMResult, ProviderFailure
from app.integrations.http_policy import retry_after_seconds
from app.integrations.image_sizes import IMAGE_SIZES, output_size
from app.integrations.secrets import provider_secret


def json_object(content):
    """只兼容包住完整JSON的代码围栏，不从任意文字提取对象或放宽字段契约。"""
    if not isinstance(content, str) or len(content) > 65536:
        raise ValueError("bounded JSON string required")
    fenced = re.fullmatch(
        r"\s*```(?:json)?[ \t]*\r?\n(.*?)\r?\n```\s*", content, flags=re.DOTALL | re.IGNORECASE
    )
    result = json.loads(fenced[1] if fenced else content)
    if not isinstance(result, dict):
        raise ValueError("object required")
    return result


def check_response(response):
    """仅按 HTTP 状态分类；不解析或传播可能含凭证的上游错误正文。"""
    status = response.status_code
    if status >= 500:
        raise ProviderFailure("PROVIDER_RESULT_UNKNOWN", unknown=True)
    if status == 429:
        raise ProviderFailure(
            "PROVIDER_RATE_LIMITED",
            retry_after_seconds=retry_after_seconds(response.headers.get("Retry-After")),
        )
    if response.is_error:
        code = {
            400: "PROVIDER_INVALID_REQUEST",
            401: "PROVIDER_AUTH_FAILED",
            402: "PROVIDER_BALANCE_INSUFFICIENT",
            403: "PROVIDER_PERMISSION_DENIED",
            404: "PROVIDER_MODEL_UNAVAILABLE",
            422: "PROVIDER_INVALID_REQUEST",
        }.get(status, "PROVIDER_REJECTED")
        raise ProviderFailure(code)


class CompatibleBase:
    """连接参数有界；上游错误映射为稳定分类，不透传响应正文。"""

    DEFAULT_TIMEOUT = 60
    MAX_TIMEOUT = 120

    def __init__(self, options: dict, settings):
        """初始化当前适配器或错误，不从浏览器接受凭证与权限。"""
        self.model = options["model"]
        self.base_url = options["base_url"].rstrip("/")
        self.key = provider_secret(settings, options["api_key_env"])
        self.timeout = min(float(options.get("timeout_seconds", self.DEFAULT_TIMEOUT)), self.MAX_TIMEOUT)
        if not self.key:
            raise ValueError(f"缺少供应商凭证环境变量：{options['api_key_env']}")
        if settings.app_env == "production" and not self.base_url.startswith("https://"):
            raise ValueError("production 上游必须使用 HTTPS")

    def post(self, path: str, **kwargs) -> dict:
        """超时/5xx 视为提交结果未知，不进行透明重试。"""
        wire_request("POST", self.base_url + path, **{k: v for k, v in kwargs.items() if k != "timeout"})
        try:
            with httpx.Client(timeout=kwargs.pop("timeout", self.timeout), follow_redirects=False) as client:
                response = client.post(
                    self.base_url + path, headers={"Authorization": f"Bearer {self.key}"}, **kwargs
                )
                wire_response(response_body(response), response.status_code)
                check_response(response)
                return response.json()
        except (httpx.RequestError, ValueError) as exc:
            raise ProviderFailure("PROVIDER_RESULT_UNKNOWN", unknown=True) from exc


class CompatibleLLM(CompatibleBase):
    """兼容 chat/completions 的 JSON 输出；工具权限仍由 Agent 层校验。"""

    DEFAULT_TIMEOUT = 300
    MAX_TIMEOUT = 300

    def __init__(self, options: dict, settings):
        """输出预算可由部署配置控制，浏览器不能直接覆盖单次模型请求。"""
        super().__init__(options, settings)
        self.max_tokens = min(max(int(options.get("max_tokens", 2000)), 16), 4096)
        self.streaming_enabled = options.get("streaming_enabled", True)

    def draft(self, messages: list[dict]) -> dict:
        """只返回模型草稿；超出预算与结构校验由调用方负责。"""
        return self.complete(messages).data

    def complete(self, messages: list[dict], timeout_seconds: float | None = None) -> LLMResult:
        """Agent 可读取数值用量并缩短网络期限，不泄露完整供应商响应。"""
        data = self.post(
            "/chat/completions",
            timeout=min(self.timeout, timeout_seconds) if timeout_seconds else self.timeout,
            json={
                "model": self.model,
                "messages": messages,
                "response_format": {"type": "json_object"},
                "max_tokens": self.max_tokens,
            },
        )
        try:
            choice = data["choices"][0]
            result = json_object(choice["message"]["content"])
            if not isinstance(result, dict) or choice.get("finish_reason") == "length":
                raise ValueError("incomplete output")
            usage = data.get("usage", {})
            return LLMResult(
                result,
                {
                    key: usage[key]
                    for key in ("prompt_tokens", "completion_tokens", "total_tokens")
                    if isinstance(usage, dict) and type(usage.get(key)) is int and usage[key] >= 0
                },
            )
        except (KeyError, IndexError, ValueError, TypeError) as exc:
            raise ProviderFailure("PROVIDER_INVALID_OUTPUT") from exc

    def stream_complete(self, messages, on_content, timeout_seconds=None) -> LLMResult:
        """消费兼容 SSE；仅 content 进入回调，推理/原生工具参数永不转发。"""
        timeout = min(self.timeout, timeout_seconds) if timeout_seconds else self.timeout
        deadline = monotonic() + (timeout_seconds or self.timeout)
        chunks, usage, finish, size = [], {}, None, 0
        stream_body = {
            "model": self.model,
            "messages": messages,
            "response_format": {"type": "json_object"},
            "max_tokens": self.max_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        wire_request("POST", self.base_url + "/chat/completions", json=stream_body)
        http_status = None
        try:
            with httpx.Client(timeout=timeout, follow_redirects=False) as client:
                with client.stream(
                    "POST",
                    self.base_url + "/chat/completions",
                    headers={"Authorization": f"Bearer {self.key}", "Accept": "text/event-stream"},
                    json=stream_body,
                ) as response:
                    http_status = response.status_code
                    if response.is_error:
                        response.read()
                        wire_response(response_body(response), http_status)
                    check_response(response)
                    data_lines = []
                    for line in response.iter_lines():
                        if monotonic() >= deadline:
                            raise ProviderFailure("AGENT_TIMEOUT")
                        if line.startswith("data:"):
                            data_lines.append(line[5:].lstrip(" "))
                            if sum(map(len, data_lines)) > 65536:
                                raise ProviderFailure("PROVIDER_INVALID_OUTPUT")
                            continue
                        if line or not data_lines:
                            continue
                        data = "\n".join(data_lines)
                        data_lines = []
                        if data == "[DONE]":
                            break
                        try:
                            item = json.loads(data)
                        except ValueError as exc:
                            raise ProviderFailure("PROVIDER_RESULT_UNKNOWN", unknown=True) from exc
                        if not isinstance(item, dict) or item.get("error"):
                            raise ProviderFailure("PROVIDER_RESULT_UNKNOWN", unknown=True)
                        if isinstance(item.get("usage"), dict):
                            usage.update(
                                {
                                    key: value
                                    for key, value in item["usage"].items()
                                    if key in {"prompt_tokens", "completion_tokens", "total_tokens"}
                                    and type(value) is int
                                    and value >= 0
                                }
                            )
                        choices = item.get("choices", [])
                        if not isinstance(choices, list):
                            raise ProviderFailure("PROVIDER_RESULT_UNKNOWN", unknown=True)
                        for choice in choices:
                            if not isinstance(choice, dict) or not isinstance(choice.get("delta", {}), dict):
                                raise ProviderFailure("PROVIDER_RESULT_UNKNOWN", unknown=True)
                            if choice.get("index", 0) != 0:
                                continue
                            content = choice.get("delta", {}).get("content")
                            if content is not None:
                                if not isinstance(content, str) or finish is not None:
                                    raise ProviderFailure("PROVIDER_INVALID_OUTPUT")
                                size += len(content)
                                if size > 65536:
                                    raise ProviderFailure("PROVIDER_INVALID_OUTPUT")
                                chunks.append(content)
                                on_content(content)
                            if choice.get("finish_reason") is not None:
                                finish = choice["finish_reason"]
            if finish is None:
                raise ProviderFailure("PROVIDER_RESULT_UNKNOWN", unknown=True)
            if finish != "stop":
                raise ProviderFailure("PROVIDER_INVALID_OUTPUT")
            result = json_object("".join(chunks))
            if not isinstance(result, dict):
                raise ValueError("object required")
            return LLMResult(result, usage)
        except httpx.RequestError as exc:
            raise ProviderFailure("PROVIDER_RESULT_UNKNOWN", unknown=True) from exc
        except (ValueError, KeyError, IndexError, TypeError, AttributeError) as exc:
            raise ProviderFailure("PROVIDER_INVALID_OUTPUT") from exc
        finally:
            if http_status is not None and http_status < 400:
                wire_response(
                    {"stream": True, "content": "".join(chunks), "finish_reason": finish, "usage": usage},
                    http_status,
                )


class CompatibleImage(CompatibleBase):
    """兼容 multipart images/edits 的参考图插件；供应商必须支持返回 b64_json。"""

    def __init__(self, options: dict, settings):
        """尺寸随适配器配置，不能把某一家模型的尺寸规则写入业务流程。"""
        super().__init__(options, settings)
        self.sizes = options.get("size_by_aspect_ratio", IMAGE_SIZES)

    def generate(self, request: ImageRequest) -> ImageResult:
        """不下载供应商任意 URL；使用冻结参考图并要求直接图片数据。"""
        size = request.size or output_size(request.aspect_ratio, self.sizes)
        if request.operation == "text":
            data = self.post(
                "/images/generations",
                json={
                    "model": self.model,
                    "prompt": request.prompt,
                    "n": 1,
                    "size": size,
                    "response_format": "b64_json",
                },
            )
        else:
            data = self.post(
                "/images/edits",
                data={
                    "model": self.model,
                    "prompt": request.prompt,
                    "n": "1",
                    "size": size,
                    "response_format": "b64_json",
                },
                files=[
                    ("image[]", (f"reference-{i}.png", content, "image/png"))
                    for i, content in enumerate(request.references)
                ],
            )
        try:
            content = base64.b64decode(data["data"][0]["b64_json"], validate=True)
            if len(content) > 30 * 1024 * 1024:
                raise ValueError("oversized")
            return ImageResult(content)
        except (KeyError, IndexError, ValueError) as exc:
            raise ProviderFailure("PROVIDER_INVALID_OUTPUT", unknown=True) from exc
