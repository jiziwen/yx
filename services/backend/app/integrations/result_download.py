"""受控成图下载：验证公网目的地址并固定连接，代理模式仍校验原域名TLS证书。"""

import ipaddress
import socket
from urllib.request import getproxies, proxy_bypass

import httpx

from app.integrations.contracts import ProviderFailure


def configured_proxy(host):
    """只读取部署环境的出站代理，绝不接受模型或浏览器传入代理地址。"""
    proxies = getproxies()
    return None if proxy_bypass(host) else proxies.get("https") or proxies.get("all")


def global_addresses(values):
    """只选择全球可路由IP，不把私网、环回或过渡地址用于成图连接。"""
    result = []
    for value in values:
        try:
            address = ipaddress.ip_address(value)
        except ValueError:
            continue
        if address.is_global and str(address) not in result:
            result.append(str(address))
    return sorted(result, key=lambda value: ipaddress.ip_address(value).version)


def result_addresses(host, timeout, proxy):
    """代理/混合DNS可能返回合成地址，使用固定HTTPS解析器核对，不下载解析结果中的URL。"""
    try:
        local = [entry[4][0] for entry in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)]
    except OSError:
        local = []
    public = global_addresses(local)
    if not proxy and public and len(public) == len(set(local)):
        return public
    for endpoint in ("https://dns.google/resolve", "https://cloudflare-dns.com/dns-query"):
        try:
            with httpx.Client(timeout=min(timeout, 8), follow_redirects=False) as client:
                response = client.get(
                    endpoint, params={"name": host, "type": "A"}, headers={"Accept": "application/dns-json"}
                )
                response.raise_for_status()
                addresses = global_addresses(
                    [
                        entry.get("data", "")
                        for entry in response.json().get("Answer", [])
                        if entry.get("type") == 1
                    ]
                )
                if addresses:
                    return addresses
        except (httpx.HTTPError, ValueError, TypeError, AttributeError):
            continue
    if public:
        return public
    raise ProviderFailure("PROVIDER_UNSAFE_RESULT", unknown=True)


class HostnameStream:
    """CONNECT使用已验证IP时，把TLS服务名恢复为原域名，保持证书校验开启。"""

    def __init__(self, stream, address, hostname):
        """冻结已验证地址及对应的登记域名。"""
        self.stream, self.address, self.hostname = stream, address, hostname

    def __getattr__(self, name):
        """读写与关闭仍交由原网络流处理。"""
        return getattr(self.stream, name)

    def start_tls(self, ssl_context, server_hostname=None, timeout=None):
        """同时兼容直连、HTTP代理及HTTPS代理的第二层TLS，不影响代理自身证书。"""
        name = self.hostname if server_hostname == self.address else server_hostname
        stream = self.stream.start_tls(ssl_context=ssl_context, server_hostname=name, timeout=timeout)
        return HostnameStream(stream, self.address, self.hostname)


class HostnameBackend:
    """包装锁定版本httpcore的同步网络后端；不改变连接目的IP或TLS验证上下文。"""

    def __init__(self, backend, address, hostname):
        """保留原后端的代理、超时和连接选项。"""
        self.backend, self.address, self.hostname = backend, address, hostname

    def __getattr__(self, name):
        """委托未修改的网络后端协议方法。"""
        return getattr(self.backend, name)

    def connect_tcp(self, *args, **kwargs):
        """HTTPX目标已固定为公网IP；返回保留原域名的TLS流。"""
        return HostnameStream(self.backend.connect_tcp(*args, **kwargs), self.address, self.hostname)


def result_transport(address, hostname, proxy):
    """HTTPX无公开后端注入入口，适配锁定的httpcore池并由TLS契约测试覆盖。"""
    transport = httpx.HTTPTransport(proxy=proxy, verify=True, retries=0)
    transport._pool._network_backend = HostnameBackend(transport._pool._network_backend, address, hostname)
    return transport
