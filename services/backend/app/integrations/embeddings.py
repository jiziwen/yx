"""固定1536维 embedding 适配器；开发哈希明确标样例，真实插件走服务端凭证。"""

import hashlib
import math
import re

import httpx

from app.integrations.call_logging import response_body, wire_request, wire_response, wire_secret
from app.integrations.contracts import ProviderFailure
from app.integrations.secrets import provider_secret

DIMENSIONS = 1536


def tokens(text):
    """中英文统一分词 v1：英文词、中文双字及单字；不执行输入内容。"""
    result = re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]", text.lower())
    result += [a + b for a, b in zip(text, text[1:]) if all("\u4e00" <= c <= "\u9fff" for c in a + b)]
    return result


def validate_vectors(vectors, count):
    """拒绝错误维度、非数值、零向量和非有限值，不混用索引空间。"""
    if len(vectors) != count:
        raise ProviderFailure("EMBEDDING_INVALID_OUTPUT")
    result = []
    for vector in vectors:
        if len(vector) != DIMENSIONS or any(
            type(v) not in (int, float) or not math.isfinite(v) for v in vector
        ):
            raise ProviderFailure("EMBEDDING_INVALID_OUTPUT")
        length = math.sqrt(sum(v * v for v in vector))
        if not length:
            raise ProviderFailure("EMBEDDING_INVALID_OUTPUT")
        result.append([v / length for v in vector])
    return result


class DevelopmentEmbedding:
    """确定性工程夹具，不宣称语义效果，不允许生产装配。"""

    def __init__(self, options, settings):
        """协议与真实适配器一致，测试不调用外部网络。"""
        if settings.app_env == "production":
            raise ValueError("生产禁止开发 embedding")
        self.spec = {
            "model": "development-hash-v1",
            "dimensions": DIMENSIONS,
            "normalization": "l2",
            "development_sample": True,
        }

    def embed(self, texts, timeout_seconds=30):
        """把词频投影到固定空间，仅用于确定性检索/迁移验收。"""
        vectors = []
        for text in texts:
            vector = [0.0] * DIMENSIONS
            for token in tokens(text):
                index = int.from_bytes(hashlib.sha256(token.encode()).digest()[:4]) % DIMENSIONS
                vector[index] += 1
            vectors.append(vector)
        return validate_vectors(vectors, len(texts)), {}


class CompatibleEmbedding:
    """兼容 embeddings API；无重发、无浏览器自定义端点，错误不返回供应商正文。"""

    def __init__(self, options, settings):
        """模型与固定维度构成空间版本；更换模型必须重建并重新发布。"""
        self.options = options
        self.settings = settings
        self.spec = {
            "model": options.get("model", "Qwen/Qwen3-Embedding-8B"),
            "dimensions": DIMENSIONS,
            "normalization": "l2",
            "development_sample": False,
        }
        self.base_url = options.get("base_url", "https://api.302.ai/v1").rstrip("/")
        if not self.base_url.startswith("https://"):
            raise ValueError("embedding 地址必须 HTTPS")

    def embed(self, texts, timeout_seconds=30):
        """一次有界调用；供应商不可用时停止新索引，保留旧发布版本。"""
        key = provider_secret(self.settings, self.options.get("api_key_env", "AI302_API_KEY"))
        if not key:
            raise ProviderFailure("EMBEDDING_UNAVAILABLE")
        wire_secret(key)
        body = {
            "model": self.spec["model"],
            "input": texts,
            "dimensions": DIMENSIONS,
            "encoding_format": "float",
        }
        wire_request("POST", self.base_url + "/embeddings", json=body)
        try:
            response = httpx.post(
                self.base_url + "/embeddings",
                headers={"Authorization": "Bearer " + key},
                json=body,
                timeout=min(timeout_seconds, 30),
                follow_redirects=False,
            )
            wire_response(response_body(response), response.status_code)
            response.raise_for_status()
            body = response.json()
            rows = sorted(body["data"], key=lambda row: row["index"])
            if [row["index"] for row in rows] != list(range(len(texts))):
                raise ValueError("indexes")
            vectors = validate_vectors([row["embedding"] for row in rows], len(texts))
            usage = {
                k: v
                for k, v in body.get("usage", {}).items()
                if k in {"prompt_tokens", "total_tokens"} and type(v) is int and v >= 0
            }
            return vectors, usage
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            raise ProviderFailure("EMBEDDING_UNAVAILABLE") from exc
