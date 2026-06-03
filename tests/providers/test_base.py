"""Tests for providers/base.py: ProviderConfig and BaseProvider behavior.

ProviderConfig is the most depended-on configuration object in SEPCC
(71 inbound relations).  These tests cover construction defaults,
thinking toggle logic, and edge cases.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from providers.base import BaseProvider, ProviderConfig


# ── ProviderConfig construction ──────────────────────────────────────────

def test_provider_config_minimal():
    """Minimal config requires only an API key."""
    cfg = ProviderConfig(api_key="sk-test")
    assert cfg.api_key == "sk-test"
    assert cfg.base_url is None
    assert cfg.rate_limit is None
    assert cfg.rate_window == 60
    assert cfg.max_concurrency == 5
    assert cfg.http_read_timeout == 300.0
    assert cfg.http_write_timeout == 60.0
    assert cfg.http_connect_timeout == 60.0  # from config.constants
    assert cfg.enable_thinking is True
    assert cfg.proxy == ""
    assert cfg.log_raw_sse_events is False
    assert cfg.log_api_error_tracebacks is False


def test_provider_config_full():
    """All fields accept custom values."""
    cfg = ProviderConfig(
        api_key="sk-full",
        base_url="https://api.example.com/v1",
        rate_limit=20,
        rate_window=30,
        max_concurrency=10,
        http_read_timeout=600.0,
        http_write_timeout=120.0,
        http_connect_timeout=15.0,
        enable_thinking=False,
        proxy="socks5://127.0.0.1:10808",
        log_raw_sse_events=True,
        log_api_error_tracebacks=True,
    )
    assert cfg.api_key == "sk-full"
    assert cfg.base_url == "https://api.example.com/v1"
    assert cfg.rate_limit == 20
    assert cfg.rate_window == 30
    assert cfg.max_concurrency == 10
    assert cfg.http_read_timeout == 600.0
    assert cfg.http_write_timeout == 120.0
    assert cfg.http_connect_timeout == 15.0
    assert cfg.enable_thinking is False
    assert cfg.proxy == "socks5://127.0.0.1:10808"
    assert cfg.log_raw_sse_events is True
    assert cfg.log_api_error_tracebacks is True


def test_provider_config_serializes_to_dict():
    cfg = ProviderConfig(api_key="sk-test", base_url="https://x.com")
    d = cfg.model_dump()
    assert d["api_key"] == "sk-test"
    assert d["base_url"] == "https://x.com"
    assert "rate_window" in d
    assert d["rate_window"] == 60


def test_provider_config_rejects_missing_api_key():
    with pytest.raises(Exception):  # pydantic ValidationError
        ProviderConfig()


# ── _ConcreteProvider for testing BaseProvider ───────────────────────────


class _ConcreteProvider(BaseProvider):
    """Minimal concrete provider for testing BaseProvider logic."""

    async def cleanup(self) -> None:
        pass

    async def list_model_ids(self) -> frozenset[str]:
        return frozenset(["model-a"])

    async def stream_response(self, request, input_tokens=0, *, request_id=None, thinking_enabled=None):
        if False:
            yield ""


# ── _is_thinking_enabled ─────────────────────────────────────────────────


def _make_request(thinking=None):
    """Create a mock request with an optional ``thinking`` attribute."""
    req = MagicMock()
    if thinking is not None:
        req.thinking = thinking
    else:
        del req.thinking
    return req


def test_thinking_enabled_default():
    """Default config (enable_thinking=True), no request thinking → enabled."""
    cfg = ProviderConfig(api_key="k")
    provider = _ConcreteProvider(cfg)
    req = MagicMock()
    del req.thinking
    assert provider._is_thinking_enabled(req) is True


def test_thinking_disabled_by_config():
    """Config sets enable_thinking=False → disabled."""
    cfg = ProviderConfig(api_key="k", enable_thinking=False)
    provider = _ConcreteProvider(cfg)
    req = _make_request()
    assert provider._is_thinking_enabled(req) is False


def test_thinking_disabled_by_request_type():
    """Request thinking type='disabled' overrides config."""
    cfg = ProviderConfig(api_key="k", enable_thinking=True)
    provider = _ConcreteProvider(cfg)
    req = _make_request({"type": "disabled"})
    assert provider._is_thinking_enabled(req) is False


def test_thinking_disabled_by_request_enabled_false():
    """Request thinking enabled=False."""
    cfg = ProviderConfig(api_key="k", enable_thinking=True)
    provider = _ConcreteProvider(cfg)
    req = _make_request({"type": "enabled", "enabled": False})
    assert provider._is_thinking_enabled(req) is False


def test_thinking_config_disabled_but_request_enabled():
    """Config disabled + request enabled → still disabled."""
    cfg = ProviderConfig(api_key="k", enable_thinking=False)
    provider = _ConcreteProvider(cfg)
    req = _make_request({"type": "enabled", "enabled": True})
    assert provider._is_thinking_enabled(req) is False


def test_thinking_explicit_override_param():
    """The ``thinking_enabled`` parameter overrides config."""
    cfg = ProviderConfig(api_key="k", enable_thinking=True)
    provider = _ConcreteProvider(cfg)
    req = _make_request()
    assert provider._is_thinking_enabled(req, thinking_enabled=False) is False


def test_thinking_override_param_with_request_disabled():
    """override=False + request disabled=type → disabled."""
    cfg = ProviderConfig(api_key="k", enable_thinking=True)
    provider = _ConcreteProvider(cfg)
    req = _make_request({"type": "disabled"})
    assert provider._is_thinking_enabled(req, thinking_enabled=False) is False


def test_thinking_request_has_thinking_obj_attr():
    """Request object with thinking as object attribute (not dict)."""
    cfg = ProviderConfig(api_key="k", enable_thinking=True)
    provider = _ConcreteProvider(cfg)
    req = _make_request()
    req.thinking = MagicMock()
    req.thinking.type = "enabled"
    req.thinking.enabled = True
    assert provider._is_thinking_enabled(req) is True


def test_thinking_request_obj_attr_disabled():
    """Request object thinking.type = 'disabled'."""
    cfg = ProviderConfig(api_key="k", enable_thinking=True)
    provider = _ConcreteProvider(cfg)
    req = _make_request()
    req.thinking = MagicMock()
    req.thinking.type = "disabled"
    del req.thinking.enabled
    assert provider._is_thinking_enabled(req) is False


def test_thinking_request_obj_attr_enabled_false():
    """Request object thinking.enabled = False."""
    cfg = ProviderConfig(api_key="k", enable_thinking=True)
    provider = _ConcreteProvider(cfg)
    req = _make_request()
    req.thinking = MagicMock()
    del req.thinking.type
    req.thinking.enabled = False
    assert provider._is_thinking_enabled(req) is False
