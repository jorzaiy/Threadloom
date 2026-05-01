#!/usr/bin/env python3
import socket
import sys
import unittest
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1] / 'backend'
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from backend import safe_http


def _fake_resolver(addresses):
    """Return a getaddrinfo replacement that always returns the given (family, ip) pairs."""
    def resolver(host, port, *args, **kwargs):
        return [
            (family, socket.SOCK_STREAM, 0, '', (ip, port))
            for family, ip in addresses
        ]
    return resolver


class SafeHttpResolutionTests(unittest.TestCase):
    def setUp(self):
        self._original_getaddrinfo = socket.getaddrinfo

    def tearDown(self):
        socket.getaddrinfo = self._original_getaddrinfo

    def test_open_safe_connection_rejects_private_resolved_address(self):
        # H1 regression: if a public-looking hostname resolves to a private IP
        # (DNS-rebinding), open_safe_connection must refuse to even build a
        # connection.
        socket.getaddrinfo = _fake_resolver([(socket.AF_INET, '192.168.1.5')])
        with self.assertRaises(safe_http.UnsafeTargetError):
            safe_http.open_safe_connection('https://attacker.example.com/v1/models')

    def test_open_safe_connection_rejects_loopback_for_non_local_host(self):
        socket.getaddrinfo = _fake_resolver([(socket.AF_INET, '127.0.0.1')])
        with self.assertRaises(safe_http.UnsafeTargetError):
            safe_http.open_safe_connection('https://attacker.example.com/v1/models')

    def test_open_safe_connection_rejects_link_local(self):
        socket.getaddrinfo = _fake_resolver([(socket.AF_INET, '169.254.169.254')])
        with self.assertRaises(safe_http.UnsafeTargetError):
            safe_http.open_safe_connection('https://metadata-leak.example.com/latest/meta-data')

    def test_open_safe_connection_rejects_any_private_in_multi_record_response(self):
        # If the resolver returns mixed public + private records, refuse — we
        # cannot guarantee which record the kernel would pick at connect time.
        socket.getaddrinfo = _fake_resolver([
            (socket.AF_INET, '8.8.8.8'),
            (socket.AF_INET, '10.0.0.1'),
        ])
        with self.assertRaises(safe_http.UnsafeTargetError):
            safe_http.open_safe_connection('https://mixed.example.com/v1/models')

    def test_open_safe_connection_allows_loopback_for_explicit_localhost(self):
        socket.getaddrinfo = _fake_resolver([(socket.AF_INET, '127.0.0.1')])
        conn, path = safe_http.open_safe_connection('http://127.0.0.1:8080/v1/models')
        self.assertEqual(path, '/v1/models')
        # Don't actually connect; close the unconnected handle.
        conn.close()

    def test_open_safe_connection_pins_resolved_ip(self):
        # The resolved IP must drive the actual socket, not a re-query at
        # connect time. We assert by inspecting the pinned attribute.
        socket.getaddrinfo = _fake_resolver([(socket.AF_INET, '8.8.8.8')])
        conn, _path = safe_http.open_safe_connection('https://public.example.com/v1/models')
        self.assertEqual(getattr(conn, '_target_ip'), '8.8.8.8')
        # Original hostname is still set on the connection so SNI / cert
        # validation use the user-facing name.
        self.assertEqual(conn.host, 'public.example.com')
        conn.close()

    def test_open_safe_connection_rejects_unknown_scheme(self):
        with self.assertRaises(safe_http.UnsafeTargetError):
            safe_http.open_safe_connection('file:///etc/passwd')


if __name__ == '__main__':
    unittest.main()
