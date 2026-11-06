"""302.AI GPT Image 原生异步接口，显式指定质量和尺寸，复用安全结果下载。"""

import base64
import json

from app.integrations.ai302 import TASK_ID, USAGE_KEYS, AI302Image
from app.integrations.contracts import (
    ImageLookup,
    ImageRequest,
    ImageResult,
    ImageSubmission,
    ProviderFailure,
)
from app.integrations.image_sizes import IMAGE_SIZES, output_size


class AI302GPTImage(AI302Image):
    """GPT 系列使用原生 generations/edits，避免统一接口丢失 quality 参数。"""

    def __init__(self, options: dict, settings):
        """质量档位来自服务端配置；尺寸映射仅提供默认值。"""
        super().__init__(options, settings)
        self.quality = options.get("quality", "low")
        if self.quality not in {"low", "medium", "high", "auto"}:
            raise ValueError("无效的图片质量档位")
        self.sizes = options.get("size_by_aspect_ratio", IMAGE_SIZES)

    def submit(self, request: ImageRequest) -> ImageSubmission:
        """一次提交一张；JSON 文生图与有序多文件编辑都显式发送 low 等档位。"""
        if (
            request.operation not in self.models
            or (request.operation == "text" and request.references)
            or (request.operation != "text" and not request.references)
        ):
            raise ProviderFailure("PROVIDER_OPERATION_UNAVAILABLE")
        body = {
            "model": self.models[request.operation],
            "prompt": request.prompt,
            "size": request.size or output_size(request.aspect_ratio, self.sizes),
            "quality": self.quality,
            "n": 1,
            "output_format": "png",
        }
        if request.operation == "text":
            data = self._request(
                "POST",
                "/v1/images/generations",
                params={"async": "true", "response_format": "url"},
                json=body,
            )
        else:
            data = self._request(
                "POST",
                "/v1/images/edits",
                params={"async": "true", "response_format": "url"},
                data={key: str(value) for key, value in body.items()},
                files=[
                    ("image[]", (f"input-{i}.png", content, "image/png"))
                    for i, content in enumerate(request.references)
                ],
            )
        task_id = data.get("task_id")
        if not isinstance(task_id, str) or not TASK_ID.fullmatch(task_id):
            raise ProviderFailure("PROVIDER_INVALID_RECEIPT", unknown=True)
        return ImageSubmission(task_id)

    def lookup(self, task_id: str, request_key: str) -> ImageLookup:
        """查询既有凭据；只将明确成功且可解码的结果交给发布事务。"""
        if not TASK_ID.fullmatch(task_id):
            raise ProviderFailure("PROVIDER_INVALID_RECEIPT", unknown=True)
        response = self._request("GET", "/async_result", params={"task_id": task_id})
        if response.get("status_code") in {102, 202}:
            return ImageLookup("pending")
        if response.get("status_code") != 200 or response.get("err"):
            return ImageLookup("unknown", error_code="PROVIDER_STATUS_UNKNOWN")
        payload = response.get("data")
        if isinstance(payload, str) and payload.lstrip().startswith("{"):
            try:
                payload = json.loads(payload)
            except ValueError:
                return ImageLookup("unknown", error_code="PROVIDER_INVALID_OUTPUT")
        usage = {}
        if isinstance(payload, dict):
            raw_usage = payload.get("usage", {})
            usage = (
                {
                    key: value
                    for key, value in raw_usage.items()
                    if key in USAGE_KEYS and type(value) is int and 0 <= value <= 10**12
                }
                if isinstance(raw_usage, dict)
                else {}
            )
            items = payload.get("data")
            if not isinstance(items, list) or not items or not isinstance(items[0], dict):
                return ImageLookup("unknown", error_code="PROVIDER_INVALID_OUTPUT")
            item = items[0]
            if isinstance(item.get("b64_json"), str):
                try:
                    content = base64.b64decode(item["b64_json"], validate=True)
                    if len(content) > 30 * 1024 * 1024:
                        raise ValueError("size")
                    return ImageLookup("succeeded", ImageResult(content, usage=usage))
                except ValueError as exc:
                    raise ProviderFailure("PROVIDER_INVALID_OUTPUT", unknown=True) from exc
            payload = item.get("url")
        if isinstance(payload, str) and payload.startswith("https://"):
            return ImageLookup("succeeded", ImageResult(self._download(payload), usage=usage))
        return ImageLookup("unknown", error_code="PROVIDER_INVALID_OUTPUT")
