"""Request builder for Google Gemini API (AI Studio OpenAI-compatible chat completions)."""

from __future__ import annotations

from typing import Any

from loguru import logger

from core.anthropic import ReasoningReplayMode, build_base_request_body
from core.anthropic.conversion import OpenAIConversionError
from providers.exceptions import InvalidRequestError


def build_request_body(request_data: Any, *, thinking_enabled: bool) -> dict:
    """Build OpenAI-format request body from an Anthropic request for Gemini."""
    logger.debug(
        "GEMINI_REQUEST: conversion start model={} msgs={}",
        getattr(request_data, "model", "?"),
        len(getattr(request_data, "messages", [])),
    )
    try:
        body = build_base_request_body(
            request_data,
            reasoning_replay=ReasoningReplayMode.REASONING_CONTENT
            if thinking_enabled
            else ReasoningReplayMode.DISABLED,
        )
    except OpenAIConversionError as exc:
        raise InvalidRequestError(str(exc)) from exc

    extra_body: dict[str, Any] = {}
    request_extra = getattr(request_data, "extra_body", None)
    if request_extra:
        extra_body.update(request_extra)

    if thinking_enabled:
        body["reasoning_effort"] = "high"
        google_section = extra_body.setdefault("google", {})
        if isinstance(google_section, dict):
            thinking_cfg = google_section.setdefault("thinking_config", {})
            if isinstance(thinking_cfg, dict):
                thinking_cfg.setdefault("include_thoughts", True)
    else:
        body["reasoning_effort"] = "none"

    if extra_body:
        body["extra_body"] = extra_body

    logger.debug(
        "GEMINI_REQUEST: conversion done model={} msgs={} tools={}",
        body.get("model"),
        len(body.get("messages", [])),
        len(body.get("tools", [])),
    )
    return body
