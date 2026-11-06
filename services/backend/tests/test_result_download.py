"""混合DNS、可信代理及TLS服务名回归；绝不连接私网成图地址或关闭证书验证。"""

import ssl

import httpx
import pytest

from app.integrations import result_download
from app.integrations.contracts import ProviderFailure
from app.integrations.result_download import HostnameStream, global_addresses, result_addresses


def resolver(monkeypatch, local, answers):
    """本机DNS和HTTPS解析均用独立夹具替代，不访问外部网络。"""
    monkeypatch.setattr(
        result_download.socket,
        "getaddrinfo",
        lambda *a, **kw: [(2, 1, 6, "", (value, 443)) for value in local],
    )
    original = httpx.Client
    seen = []

    def handler(request):
        """只允许固定公共解析器，不下载任何响应中的地址或URL。"""
        assert request.url.host in {"dns.google", "cloudflare-dns.com"}
        assert request.url.params["name"] == "file.302.ai"
        seen.append(request)
        return httpx.Response(200, json={"Answer": [{"type": 1, "data": value} for value in answers]})

    monkeypatch.setattr(
        result_download.httpx, "Client", lambda **kw: original(transport=httpx.MockTransport(handler), **kw)
    )
    return seen


def test_mixed_ipv4_and_transition_ipv6_uses_verified_public_dns(monkeypatch):
    """真实故障形状：本机公网A与Teredo地址混合，不再把已完成结果永远拦在待核对。"""
    seen = resolver(monkeypatch, ["179.60.193.9", "2001::6ca0:a5ad"], ["104.21.6.36", "127.0.0.1"])
    assert result_addresses("file.302.ai", 5, None) == ["104.21.6.36"]
    assert len(seen) == 1


def test_proxy_does_not_trust_synthetic_local_public_addresses(monkeypatch):
    """代理网络使用HTTPS解析后的真实CDN地址，不把本地合成IP拿去CONNECT。"""
    resolver(monkeypatch, ["179.60.193.9"], ["104.21.6.36"])
    assert result_addresses("file.302.ai", 5, "http://127.0.0.1:8888") == ["104.21.6.36"]


def test_private_answers_never_become_download_targets(monkeypatch):
    """即便两个解析器都返回内网，仍拒绝交付，不把安全错误当作成功。"""
    seen = resolver(monkeypatch, ["127.0.0.1"], ["127.0.0.1", "10.0.0.5", "169.254.169.254"])
    with pytest.raises(ProviderFailure, match="PROVIDER_UNSAFE_RESULT"):
        result_addresses("file.302.ai", 5, None)
    assert len(seen) == 2
    assert global_addresses(["::1", "198.18.0.1", "2001::6ca0:a5ad"]) == []


def test_direct_global_dns_needs_no_external_resolver(monkeypatch):
    """正常公网直连不增加解析请求。"""
    seen = resolver(monkeypatch, ["104.21.6.36"], [])
    assert result_addresses("file.302.ai", 5, None) == ["104.21.6.36"]
    assert not seen


def test_proxy_tunnel_keeps_original_sni_and_certificate_validation():
    """HTTP CONNECT目标固定为公网IP，第二层TLS仍校验file.302.ai，代理自身域名不被替换。"""
    calls = []

    class Stream:
        """不进行网络连接的TLS协议夹具。"""

        def start_tls(self, **kwargs):
            """记录原验证上下文和服务名。"""
            calls.append(kwargs)
            return self

    context = ssl.create_default_context()
    stream = HostnameStream(Stream(), "104.21.6.36", "file.302.ai")
    stream = stream.start_tls(context, server_hostname="trusted-proxy.example", timeout=3)
    stream.start_tls(context, server_hostname="104.21.6.36", timeout=3)
    assert [call["server_hostname"] for call in calls] == ["trusted-proxy.example", "file.302.ai"]
    assert all(call["ssl_context"] is context for call in calls)
    assert context.check_hostname and context.verify_mode == ssl.CERT_REQUIRED
