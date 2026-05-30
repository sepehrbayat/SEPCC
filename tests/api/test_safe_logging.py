"""Tests that API and SSE logging avoid raw sensitive payloads by default."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.responses import StreamingResponse

from api import services as services_mod
from api.models.anthropic import Message, MessagesRequest
from api.services import ClaudeProxyService
from config.settings import Settings
from core.anthropic.sse import SSEBuilder


def test_create_message_skips_full_payload_debug_log_by_default():
    settings = Settings()
    assert settings.log_raw_api_payloads is False
    mock_provider = MagicMock()

    async def fake_stream(*_a, **_kw):
        yield "event: ping\ndata: {}\n\n"

    mock_provider.stream_response = fake_stream
    service = ClaudeProxyService(settings, provider_getter=lambda _: mock_provider)

    request = MessagesRequest(
        model="claude-3-haiku-20240307",
        max_tokens=10,
        messages=[Message(role="user", content="secret-user-text")],
    )

    with patch.object(services_mod.logger, "debug") as mock_debug:
        service.create_message(request)

    full_payload_calls = [
        c
        for c in mock_debug.call_args_list
        if c.args and str(c.args[0]) == "FULL_PAYLOAD [{}]: {}"
    ]
    assert not full_payload_calls


def test_create_message_logs_full_payload_when_opt_in():
    settings = Settings()
    settings.log_raw_api_payloads = True
    mock_provider = MagicMock()

    async def fake_stream(*_a, **_kw):
        yield "event: ping\ndata: {}\n\n"

    mock_provider.stream_response = fake_stream
    service = ClaudeProxyService(settings, provider_getter=lambda _: mock_provider)
    request = MessagesRequest(
        model="claude-3-haiku-20240307",
        max_tokens=10,
        messages=[Message(role="user", content="visible")],
    )

    with patch.object(services_mod.logger, "debug") as mock_debug:
        service.create_message(request)

    keys = [c.args[0] for c in mock_debug.call_args_list if c.args]
    assert any(k == "FULL_PAYLOAD [{}]: {}" for k in keys)


def test_create_message_uses_fallback_when_primary_provider_unavailable():
    settings = Settings()
    settings.model = "deepseek/deepseek-v4-pro"
    settings.model_fallbacks = "open_router/fallback-model"
    providers = {"open_router": MagicMock()}
    requested: list[str] = []

    def provider_getter(provider_id: str):
        requested.append(provider_id)
        return providers[provider_id]

    service = ClaudeProxyService(
        settings,
        provider_getter=provider_getter,
        provider_available=lambda provider_id: provider_id != "deepseek",
    )
    request = MessagesRequest(
        model="claude-3-haiku-20240307",
        max_tokens=10,
        messages=[Message(role="user", content="hi")],
    )

    service.create_message(request)

    assert requested == ["open_router"]
    providers["open_router"].preflight_stream.assert_called_once()
    routed_request = providers["open_router"].preflight_stream.call_args.args[0]
    assert routed_request.model == "fallback-model"


@pytest.mark.asyncio
async def test_create_message_reports_stream_error_sse_as_provider_failure():
    settings = Settings()
    settings.model = "deepseek/deepseek-v4-pro"
    settings.model_haiku = None
    reports: list[tuple[str, bool, str | None]] = []
    mock_provider = MagicMock()

    async def fake_stream(*_a, **_kw):
        yield 'event: error\ndata: {"type":"error"}\n\n'

    mock_provider.stream_response = fake_stream
    service = ClaudeProxyService(
        settings,
        provider_getter=lambda _: mock_provider,
        report_provider_health=lambda provider_id, ok, exc: reports.append(
            (provider_id, ok, type(exc).__name__ if exc else None)
        ),
    )
    request = MessagesRequest(
        model="claude-3-haiku-20240307",
        max_tokens=10,
        messages=[Message(role="user", content="hi")],
    )

    response = service.create_message(request)
    assert isinstance(response, StreamingResponse)
    _ = [chunk async for chunk in response.body_iterator]

    assert reports == [("deepseek", False, "RuntimeError")]


def test_sse_builder_default_debug_has_no_serialized_json_content():
    with patch("core.anthropic.sse.logger.debug") as mock_debug:
        sse = SSEBuilder("msg_x", "m", 1, log_raw_events=False)
        sse.message_start()

    assert mock_debug.call_count == 0


def test_sse_builder_raw_logging_includes_event_body_when_enabled():
    with patch("core.anthropic.sse.logger.debug") as mock_debug:
        sse = SSEBuilder("msg_x", "m", 1, log_raw_events=True)
        sse.message_start()

    assert mock_debug.call_count == 1
    message = str(mock_debug.call_args)
    assert "message_start" in message
    assert "role" in message


def _flatten_log_calls(mock_log) -> str:
    parts: list[str] = []
    for call in mock_log.call_args_list:
        parts.extend(str(arg) for arg in call.args)
        parts.append(repr(call.kwargs))
    return " ".join(parts)


def test_create_message_unexpected_error_default_logs_exclude_exception_text():
    settings = Settings()
    assert settings.log_api_error_tracebacks is False
    secret = "upstream-secret-token-abc"

    mock_provider = MagicMock()

    def stream_boom(*_a, **_kw):
        raise RuntimeError(secret)

    mock_provider.stream_response = stream_boom
    service = ClaudeProxyService(settings, provider_getter=lambda _: mock_provider)
    request = MessagesRequest(
        model="claude-3-haiku-20240307",
        max_tokens=10,
        messages=[Message(role="user", content="hi")],
    )

    with (
        patch.object(services_mod.logger, "error") as log_err,
        pytest.raises(HTTPException),
    ):
        service.create_message(request)

    blob = _flatten_log_calls(log_err)
    assert secret not in blob
    assert "RuntimeError" in blob


def test_create_message_unexpected_error_always_returns_500():
    """Non-provider failures must not leak arbitrary status_code attributes."""

    class WeirdError(Exception):
        status_code = 418

    settings = Settings()
    mock_provider = MagicMock()

    def stream_boom(*_a, **_kw):
        raise WeirdError("no")

    mock_provider.stream_response = stream_boom
    service = ClaudeProxyService(settings, provider_getter=lambda _: mock_provider)
    request = MessagesRequest(
        model="claude-3-haiku-20240307",
        max_tokens=10,
        messages=[Message(role="user", content="hi")],
    )

    with pytest.raises(HTTPException) as excinfo:
        service.create_message(request)

    assert excinfo.value.status_code == 500


def test_parse_cli_event_error_logs_metadata_by_default():
    """CLI parser must not log raw error text unless LOG_RAW_CLI_DIAGNOSTICS is on."""
    from messaging.event_parser import parse_cli_event

    secret = "user-secret-parser-leak-xyz"
    with patch("messaging.event_parser.logger.info") as log_info:
        parse_cli_event(
            {"type": "error", "error": {"message": secret}}, log_raw_cli=False
        )
    flat = " ".join(str(c) for c in log_info.call_args_list)
    assert secret not in flat
    assert "message_chars" in flat


def test_parse_cli_event_error_logs_text_when_log_raw_cli_enabled():
    from messaging.event_parser import parse_cli_event

    secret = "visible-cli-parser-msg"
    with patch("messaging.event_parser.logger.info") as log_info:
        parse_cli_event(
            {"type": "error", "error": {"message": secret}}, log_raw_cli=True
        )
    flat = " ".join(str(c) for c in log_info.call_args_list)
    assert secret in flat


def test_count_tokens_unexpected_error_default_logs_exclude_exception_text():
    settings = Settings()
    assert settings.log_api_error_tracebacks is False
    secret = "count-tokens-leak-xyz"

    def boom(*_a, **_kw):
        raise ValueError(secret)

    service = ClaudeProxyService(
        settings,
        provider_getter=lambda _: MagicMock(),
        token_counter=boom,
    )
    from api.models.anthropic import TokenCountRequest

    req = TokenCountRequest(
        model="claude-3-haiku-20240307",
        messages=[Message(role="user", content="x")],
    )

    with (
        patch.object(services_mod.logger, "error") as log_err,
        pytest.raises(HTTPException),
    ):
        service.count_tokens(req)

    blob = _flatten_log_calls(log_err)
    assert secret not in blob
    assert "ValueError" in blob
