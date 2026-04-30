#!/usr/bin/env python3
"""SSRF-safe HTTP client helpers.

discover_* endpoints and the LLM model client both connect to user-supplied
baseUrls. ``urllib.request.urlopen`` resolves the hostname itself, which leaves
a DNS-rebinding window between the write-time URL validation and the actual
connect: the same hostname can resolve to a public address during validation
and to a loopback/private address by the time the request is issued.

This module pre-resolves the hostname, validates that *every* returned address
is on a public network (or explicit loopback for ``localhost``/``127.0.0.1``),
then connects directly to the resolved IP. The TLS layer still sees the
original hostname via ``server_hostname=`` so SNI and certificate verification
keep working.
"""

from __future__ import annotations

import http.client
import ipaddress
import socket
import ssl
from urllib.parse import urlparse


class UnsafeTargetError(ValueError):
    """Raised when a URL resolves to a non-public network destination."""


_LOOPBACK_HOSTS = {'localhost', '127.0.0.1', '::1'}


def _is_safe_ip(ip: str, *, allow_loopback: bool) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    if addr.is_loopback:
        return allow_loopback
    if (
        addr.is_link_local
        or addr.is_private
        or addr.is_multicast
        or addr.is_reserved
        or addr.is_unspecified
    ):
        return False
    return True


def _resolve_and_validate(host: str, port: int, *, allow_loopback: bool) -> list[tuple[int, str]]:
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as err:
        raise UnsafeTargetError(f'failed to resolve {host}: {err}') from err
    out: list[tuple[int, str]] = []
    for family, _, _, _, sockaddr in infos:
        if family not in (socket.AF_INET, socket.AF_INET6):
            continue
        ip = sockaddr[0]
        if not _is_safe_ip(ip, allow_loopback=allow_loopback):
            raise UnsafeTargetError(f'{host} resolves to non-public address {ip}')
        out.append((family, ip))
    if not out:
        raise UnsafeTargetError(f'{host} has no usable address records')
    return out


class _IPPinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host: str, port: int, *, target_ip: str, target_family: int, timeout: float, context: ssl.SSLContext):
        super().__init__(host, port, timeout=timeout, context=context)
        self._target_ip = target_ip
        self._target_family = target_family

    def connect(self):
        sock = socket.socket(self._target_family, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        sock.connect((self._target_ip, self.port))
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


class _IPPinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, host: str, port: int, *, target_ip: str, target_family: int, timeout: float):
        super().__init__(host, port, timeout=timeout)
        self._target_ip = target_ip
        self._target_family = target_family

    def connect(self):
        sock = socket.socket(self._target_family, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        sock.connect((self._target_ip, self.port))
        self.sock = sock


def open_safe_connection(url: str, *, timeout: float = 20.0) -> tuple[http.client.HTTPConnection, str]:
    """Resolve and validate the URL, return a (connection, path) pair.

    The caller is responsible for ``conn.request(...)``, ``conn.getresponse()``,
    reading or streaming the body, and ``conn.close()``. A pre-resolved IP is
    pinned on the connection so the OS will not re-query DNS when the socket
    opens, defeating DNS-rebinding attacks.
    """
    parsed = urlparse(url)
    if parsed.scheme not in {'http', 'https'}:
        raise UnsafeTargetError('only http/https schemes are allowed')
    host = parsed.hostname or ''
    if not host:
        raise UnsafeTargetError('url has no hostname')
    port = parsed.port or (443 if parsed.scheme == 'https' else 80)
    allow_loopback = host in _LOOPBACK_HOSTS
    family, ip = _resolve_and_validate(host, port, allow_loopback=allow_loopback)[0]
    if parsed.scheme == 'https':
        ctx = ssl.create_default_context()
        conn: http.client.HTTPConnection = _IPPinnedHTTPSConnection(
            host, port, target_ip=ip, target_family=family, timeout=timeout, context=ctx,
        )
    else:
        conn = _IPPinnedHTTPConnection(
            host, port, target_ip=ip, target_family=family, timeout=timeout,
        )
    path = parsed.path or '/'
    if parsed.query:
        path = f'{path}?{parsed.query}'
    return conn, path


def safe_request(
    url: str,
    *,
    method: str = 'GET',
    headers: dict[str, str] | None = None,
    body: bytes | None = None,
    timeout: float = 20.0,
) -> tuple[int, dict[str, str], bytes]:
    """Issue a single SSRF-safe request and read the full body.

    Returns ``(status, headers, body_bytes)``. Use ``open_safe_connection`` for
    streaming responses where the body cannot be buffered in full.
    """
    conn, path = open_safe_connection(url, timeout=timeout)
    try:
        conn.request(method, path, body=body, headers=headers or {})
        resp = conn.getresponse()
        status = resp.status
        resp_headers = {k: v for k, v in resp.getheaders()}
        data = resp.read()
        return status, resp_headers, data
    finally:
        conn.close()
