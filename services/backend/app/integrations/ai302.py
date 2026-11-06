"""302.AI 统一异步图片适配器；凭据只在服务端，提交与查询无透明重试。"""

import base64
import re
from urllib.parse import quote, urlsplit

import httpx

from app.integrations.call_logging import response_body, wire_request, wire_response
from app.integrations.contracts import (
    ImageLookup,
    ImageRequest,
    ImageResult,
    ImageSubmission,
    ProviderFailure,
)
from app.integrations.http_policy import retry_after_seconds
from app.integrations.result_download import configured_proxy, result_addresses, result_transport
from app.integrations.secrets import provider_secret

TASK_ID = re.compile(r"[A-Za-z0-9_-]{1,200}\Z")
USAGE_KEYS = {"input_tokens", "output_tokens", "total_tokens", "image_count"}


class AI302Image:
    """使用 /302/v2/image；统一接口模型参数由部署配置决定。"""

    def __init__(self, options: dict, settings):
        """仅允许部署指定的 HTTPS API 和结果主机，开发环境也不接受私有地址。"""
        self.base_url = options.get("base_url", "https://api.302.ai").rstrip("/")
        api = urlsplit(self.base_url)
        if (
            api.scheme != "https"
            or api.hostname not in {"api.302.ai", "api.302ai.cn"}
            or api.username
            or api.password
            or api.query
            or api.fragment
            or api.path
            or api.port not in (None, 443)
        ):
            raise ValueError("302.AI API 地址必须使用官方 HTTPS 根地址")
        self.key = provider_secret(settings, options.get("api_key_env", "AI302_API_KEY"))
        if not self.key:
            raise ValueError("缺少 302.AI 服务端凭证")
        self.models = options["models"]
        if (
            not self.models
            or not set(self.models).issubset({"text", "reference", "edit"})
            or any(not isinstance(model, str) or not model for model in self.models.values())
        ):
            raise ValueError("302.AI 必须配置各操作的实际模型标识")
        self.timeout = min(max(float(options.get("timeout_seconds", 30)), 1), 120)
        self.result_hosts = set(options.get("result_hosts", ["file.302.ai", "file.302ai.cn"]))
        self.resolution = options.get("resolution")

    def _request(self, method: str, path: str, **kwargs) -> dict:
        """提交不确定与查询失败统一保守处理；不公开上游错误正文。"""
        wire_request(method, self.base_url + path, **kwargs)
        try:
            with httpx.Client(timeout=self.timeout, follow_redirects=False) as client:
                response = client.request(
                    method, self.base_url + path, headers={"Authorization": f"Bearer {self.key}"}, **kwargs
                )
                wire_response(response_body(response), response.status_code)
                # 查询失败不代表任务失败；提交 5xx/重定向可能已经被接单。
                if response.status_code >= 500 or response.is_redirect:
                    raise ProviderFailure("PROVIDER_RESULT_UNKNOWN", unknown=True)
                if response.status_code == 429:
                    raise ProviderFailure(
                        "PROVIDER_RATE_LIMITED",
                        unknown=method != "POST",
                        retry_after_seconds=retry_after_seconds(response.headers.get("Retry-After")),
                    )
                if response.is_error:
                    raise ProviderFailure("PROVIDER_REJECTED", unknown=method != "POST")
                data = response.json()
                if not isinstance(data, dict):
                    raise ValueError("shape")
                return data
        except (httpx.RequestError, ValueError) as exc:
            raise ProviderFailure("PROVIDER_RESULT_UNKNOWN", unknown=True) from exc

    def submit(self, request: ImageRequest) -> ImageSubmission:
        """以 data URL 直接发送冻结的私有输入，不创建公开素材链接。"""
        if request.operation not in self.models or (request.operation == "text" and request.references):
            raise ProviderFailure("PROVIDER_OPERATION_UNAVAILABLE")
        body = {
            "model": self.models[request.operation],
            "prompt": request.prompt,
            "aspect_ratio": request.aspect_ratio,
            "output_format": "png",
        }
        if self.resolution:
            body["resolution"] = self.resolution
        if request.references:
            body["image"] = [
                "data:image/png;base64," + base64.b64encode(value).decode("ascii")
                for value in request.references
            ]
        data = self._request("POST", "/302/v2/image/generate", params={"run_async": "true"}, json=body)
        task_id = data.get("task_id")
        if not isinstance(task_id, str) or not TASK_ID.fullmatch(task_id):
            raise ProviderFailure("PROVIDER_INVALID_RECEIPT", unknown=True)
        return ImageSubmission(task_id)

    def _download(self, url: str) -> bytes:
        """只读取已登记的公共 HTTPS 结果主机，限制字节且禁止跟随重定向。"""
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or parsed.hostname not in self.result_hosts
            or parsed.port not in (None, 443)
            or parsed.username
            or parsed.password
            or parsed.fragment
        ):
            raise ProviderFailure("PROVIDER_UNSAFE_RESULT", unknown=True)
        try:
            proxy = configured_proxy(parsed.hostname)
            address = result_addresses(parsed.hostname, self.timeout, proxy)[0]
            authority = f"[{address}]" if ":" in address else address
            target = parsed._replace(netloc=authority).geturl()
            # 公网IP固定到真实连接；Host与TLS仍使用已登记域名，且不转发供应商令牌。
            transport = result_transport(address, parsed.hostname, proxy)
            with httpx.Client(
                timeout=self.timeout, follow_redirects=False, transport=transport, trust_env=False
            ) as client:
                with client.stream(
                    "GET",
                    target,
                    headers={"Host": parsed.hostname},
                    extensions={"sni_hostname": parsed.hostname},
                ) as response:
                    if response.status_code != 200:
                        raise ProviderFailure("PROVIDER_RESULT_UNAVAILABLE", unknown=True)
                    content = bytearray()
                    for chunk in response.iter_bytes():
                        content.extend(chunk)
                        if len(content) > 30 * 1024 * 1024:
                            raise ProviderFailure("PROVIDER_RESULT_TOO_LARGE", unknown=True)
                    return bytes(content)
        except (httpx.RequestError, OSError, ValueError) as exc:
            raise ProviderFailure("PROVIDER_RESULT_UNAVAILABLE", unknown=True) from exc

    def lookup(self, task_id: str, request_key: str) -> ImageLookup:
        """仅查询已持久化 ID；未知状态、404、缺少结果均保留预占。"""
        if not TASK_ID.fullmatch(task_id):
            raise ProviderFailure("PROVIDER_INVALID_RECEIPT", unknown=True)
        data = self._request("GET", "/302/v2/image/fetch/" + quote(task_id, safe=""))
        if data.get("task_id") != task_id:
            return ImageLookup("unknown", error_code="PROVIDER_RECEIPT_MISMATCH")
        status = data.get("status")
        if status in {"pending", "processing", "running", "queued"}:
            return ImageLookup("pending")
        if status == "failed":
            return ImageLookup("failed", error_code="PROVIDER_TASK_FAILED")
        if status != "completed":
            return ImageLookup("unknown", error_code="PROVIDER_STATUS_UNKNOWN")
        url = data.get("image_url")
        if not isinstance(url, str) or not url:
            return ImageLookup("unknown", error_code="PROVIDER_INVALID_OUTPUT")
        raw = data.get("raw_response")
        usage = raw.get("usage", {}) if isinstance(raw, dict) else {}
        usage = (
            {
                key: value
                for key, value in usage.items()
                if key in USAGE_KEYS and type(value) is int and 0 <= value <= 10**12
            }
            if isinstance(usage, dict)
            else {}
        )
        # 统一接口文档不保证返回实付金额，不能用公开价格填充实际成本。
        return ImageLookup("succeeded", ImageResult(self._download(url), usage=usage))
