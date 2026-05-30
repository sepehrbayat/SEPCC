"""Tests for system proxy normalization."""

from config.system_proxy import normalize_proxy_server


def test_normalize_proxy_server_prefers_explicit_socks_entry() -> None:
    raw = "http=127.0.0.1:8080;https=127.0.0.1:8080;socks=127.0.0.1:10808"

    assert normalize_proxy_server(raw) == "socks5://127.0.0.1:10808"


def test_normalize_proxy_server_uses_socks_for_common_loopback_socks_port() -> None:
    assert normalize_proxy_server("127.0.0.1:10808") == "socks5://127.0.0.1:10808"


def test_normalize_proxy_server_defaults_plain_hostport_to_http() -> None:
    assert normalize_proxy_server("proxy.example.com:8080") == (
        "http://proxy.example.com:8080"
    )
