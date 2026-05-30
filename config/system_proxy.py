"""Best-effort system proxy discovery for provider egress."""

from __future__ import annotations

import sys
from urllib.parse import urlparse

LOCAL_SOCKS_PORTS = frozenset({1080, 10808, 10809, 1086, 7890, 7891})


def detect_system_proxy() -> str:
    """Return a provider-compatible proxy URL from OS settings, if obvious."""
    if sys.platform != "win32":
        return ""
    return _detect_windows_proxy()


def normalize_proxy_server(raw: str) -> str:
    """Normalize a Windows ``ProxyServer`` value to an httpx proxy URL."""
    value = raw.strip()
    if not value:
        return ""

    parts = _split_proxy_entries(value)
    for key in ("socks", "https", "http"):
        if key in parts:
            scheme = "socks5" if key == "socks" else "http"
            return _proxy_url(parts[key], scheme=scheme)

    return _proxy_url(value, scheme=_default_scheme_for_hostport(value))


def _detect_windows_proxy() -> str:
    try:
        import winreg
    except ImportError:
        return ""

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
        ) as key:
            enabled, _ = winreg.QueryValueEx(key, "ProxyEnable")
            if not enabled:
                return ""
            proxy_server, _ = winreg.QueryValueEx(key, "ProxyServer")
    except OSError:
        return ""

    return normalize_proxy_server(str(proxy_server))


def _split_proxy_entries(value: str) -> dict[str, str]:
    entries: dict[str, str] = {}
    for part in value.split(";"):
        key, sep, item = part.partition("=")
        if sep and item.strip():
            entries[key.strip().lower()] = item.strip()
    return entries


def _proxy_url(value: str, *, scheme: str) -> str:
    candidate = value.strip()
    if not candidate:
        return ""
    parsed = urlparse(candidate)
    if parsed.scheme and "://" in candidate:
        return candidate
    return f"{scheme}://{candidate}"


def _default_scheme_for_hostport(value: str) -> str:
    host_port = value.rsplit("@", 1)[-1]
    host, sep, port_text = host_port.rpartition(":")
    if not sep:
        return "http"
    try:
        port = int(port_text)
    except ValueError:
        return "http"
    host = host.strip("[]").lower()
    if host in {"127.0.0.1", "localhost", "::1"} and port in LOCAL_SOCKS_PORTS:
        return "socks5"
    return "http"
