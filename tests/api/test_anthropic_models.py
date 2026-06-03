"""Tests for Anthropic content block types and edge cases.

Supplements the validator-focused tests in test_models_validators.py
with content-block round-trips, extra-field pass-through, and
union-type edge cases.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from api.models.anthropic import (
    ContentBlockDocument,
    ContentBlockImage,
    ContentBlockRedactedThinking,
    ContentBlockServerToolUse,
    ContentBlockText,
    ContentBlockThinking,
    ContentBlockToolResult,
    ContentBlockToolUse,
    ContentBlockWebFetchToolResult,
    ContentBlockWebSearchToolResult,
    Message,
    MessagesRequest,
    SystemContent,
    ThinkingConfig,
    TokenCountRequest,
    Tool,
    _extract_system_message_text,
)


# ── Content block serialisation / round-trip ─────────────────────────────

@pytest.mark.parametrize(
    "cls,data,expected_type",
    [
        (ContentBlockText, {"type": "text", "text": "hello"}, "text"),
        (
            ContentBlockImage,
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "abc"}},
            "image",
        ),
        (
            ContentBlockDocument,
            {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": "abc"}},
            "document",
        ),
        (
            ContentBlockToolUse,
            {"type": "tool_use", "id": "tu_1", "name": "read_file", "input": {"path": "/x"}},
            "tool_use",
        ),
        (
            ContentBlockToolResult,
            {"type": "tool_result", "tool_use_id": "tu_1", "content": "done"},
            "tool_result",
        ),
        (
            ContentBlockThinking,
            {"type": "thinking", "thinking": "hmm", "signature": "sig_1"},
            "thinking",
        ),
        (
            ContentBlockRedactedThinking,
            {"type": "redacted_thinking", "data": "opaque"},
            "redacted_thinking",
        ),
        (
            ContentBlockServerToolUse,
            {"type": "server_tool_use", "id": "stu_1", "name": "web_search", "input": {"query": "x"}},
            "server_tool_use",
        ),
        (
            ContentBlockWebSearchToolResult,
            {"type": "web_search_tool_result", "tool_use_id": "tu_1", "content": [{"title": "x"}]},
            "web_search_tool_result",
        ),
        (
            ContentBlockWebFetchToolResult,
            {"type": "web_fetch_tool_result", "tool_use_id": "tu_1", "content": "<html>...</html>"},
            "web_fetch_tool_result",
        ),
    ],
)
def test_content_block_round_trip(cls, data, expected_type):
    """Every content block can be created, dumped, and re-parsed."""
    block = cls.model_validate(data)
    assert block.type == expected_type
    dumped = block.model_dump(exclude_none=True)
    reparsed = cls.model_validate(dumped)
    assert reparsed.type == expected_type


# ── Extra-field pass-through (AnthropicBlockBase) ────────────────────────

def test_content_block_preserves_provider_fields():
    """cache_control and other provider fields survive dump/parse."""
    block = ContentBlockText.model_validate({
        "type": "text",
        "text": "cached prompt",
        "cache_control": {"type": "ephemeral"},
    })
    dumped = block.model_dump(exclude_none=True)
    assert dumped["cache_control"] == {"type": "ephemeral"}


def test_tool_block_preserves_provider_fields():
    """Extra fields on Tool survive round-trip."""
    tool = Tool.model_validate({
        "name": "web_search",
        "type": "web_search_20250305",
        "description": "Search the web",
        "display_name": "Search",  # provider extra
    })
    dumped = tool.model_dump(exclude_none=True)
    assert dumped["display_name"] == "Search"


# ── ToolResult content union ─────────────────────────────────────────────

def test_tool_result_accepts_string_content():
    result = ContentBlockToolResult.model_validate({
        "type": "tool_result",
        "tool_use_id": "tu_1",
        "content": "simple result",
    })
    assert result.content == "simple result"


def test_tool_result_accepts_list_content():
    result = ContentBlockToolResult.model_validate({
        "type": "tool_result",
        "tool_use_id": "tu_1",
        "content": [{"type": "text", "text": "part 1"}],
    })
    assert isinstance(result.content, list)
    assert result.content[0]["text"] == "part 1"


def test_tool_result_accepts_dict_content():
    result = ContentBlockToolResult.model_validate({
        "type": "tool_result",
        "tool_use_id": "tu_1",
        "content": {"status": "ok"},
    })
    assert isinstance(result.content, dict)
    assert result.content["status"] == "ok"


# ── Thinking edge cases ──────────────────────────────────────────────────

def test_thinking_block_without_signature():
    block = ContentBlockThinking.model_validate({
        "type": "thinking",
        "thinking": "bare thought",
    })
    dumped = block.model_dump(exclude_none=True)
    assert dumped["thinking"] == "bare thought"
    assert "signature" not in dumped


def test_thinking_config_disabled():
    config = ThinkingConfig.model_validate({"enabled": False})
    assert config.enabled is False
    dumped = config.model_dump(exclude_none=True)
    assert dumped == {"enabled": False}


# ── Message with mixed content blocks ────────────────────────────────────

def test_message_with_mixed_content_blocks():
    msg = Message.model_validate({
        "role": "assistant",
        "content": [
            {"type": "thinking", "thinking": "let me check", "signature": "s1"},
            {"type": "text", "text": "Here is the answer:"},
            {
                "type": "tool_use",
                "id": "tu_1",
                "name": "read",
                "input": {"file": "f.txt"},
            },
        ],
    })
    dumped = msg.model_dump(exclude_none=True)
    types = [b["type"] for b in dumped["content"]]
    assert types == ["thinking", "text", "tool_use"]


# ── MessagesRequest with all optional fields ─────────────────────────────

def test_messages_request_full_construct():
    """All optional fields survive round-trip."""
    request = MessagesRequest.model_validate({
        "model": "claude-opus-4-7",
        "max_tokens": 4096,
        "messages": [{"role": "user", "content": "hello"}],
        "system": "You are helpful.",
        "stop_sequences": ["\n\n\n"],
        "stream": False,
        "temperature": 0.7,
        "top_p": 0.95,
        "top_k": 40,
        "metadata": {"user_id": "u1"},
        "tools": [{"name": "read", "description": "Read a file", "input_schema": {"type": "object"}}],
        "tool_choice": {"type": "auto"},
        "thinking": {"type": "enabled", "budget_tokens": 2048},
        "betas": ["web-search-2025-01"],
    })
    dumped = request.model_dump(exclude_none=True)
    assert dumped["model"] == "claude-opus-4-7"
    assert dumped["stream"] is False
    assert dumped["temperature"] == 0.7
    assert "betas" not in dumped  # excluded
    assert "original_model" not in dumped  # excluded
    assert "resolved_provider_model" not in dumped


# ── TokenCountRequest ────────────────────────────────────────────────────

def test_token_count_request_basic():
    request = TokenCountRequest.model_validate({
        "model": "claude-sonnet-4-6",
        "messages": [{"role": "user", "content": "count me"}],
    })
    assert request.model == "claude-sonnet-4-6"
    assert len(request.messages) == 1


def test_token_count_request_with_tools():
    request = TokenCountRequest.model_validate({
        "model": "claude-sonnet-4-6",
        "messages": [{"role": "user", "content": "hi"}],
        "tools": [{"name": "search"}],
        "system": "Be brief.",
    })
    dumped = request.model_dump(exclude_none=True)
    assert dumped["tools"] == [{"name": "search"}]
    assert dumped["system"] == "Be brief."


# ── System text extraction helpers ───────────────────────────────────────

def test_extract_system_message_text_from_string():
    result = _extract_system_message_text("hello world")
    assert result == "hello world"


def test_extract_system_message_text_from_none():
    result = _extract_system_message_text(None)
    assert result == ""


def test_extract_system_message_text_from_non_text_block():
    result = _extract_system_message_text({"type": "image", "data": "x"})
    assert result == ""


def test_extract_system_message_text_from_text_block():
    result = _extract_system_message_text(
        {"type": "text", "text": "system prompt", "cache_control": {}}
    )
    assert result == "system prompt"


def test_extract_system_message_text_from_mixed_blocks():
    result = _extract_system_message_text([
        {"type": "text", "text": "rule 1", "cache_control": {"type": "ephemeral"}},
        {"type": "image", "source": {"data": "x"}},
        {"type": "text", "text": "rule 2"},
    ])
    assert result == "rule 1\n\nrule 2"


def test_extract_system_message_text_empty_list():
    assert _extract_system_message_text([]) == ""


def test_extract_system_message_text_all_non_text():
    result = _extract_system_message_text([
        {"type": "image", "source": {"data": "x"}},
    ])
    assert result == ""


# ── System content block ─────────────────────────────────────────────────

def test_system_content_block_basic():
    block = SystemContent.model_validate({
        "type": "text",
        "text": "system prompt",
    })
    assert block.type == "text"
    assert block.text == "system prompt"


# ── Tool edge cases ──────────────────────────────────────────────────────

def test_tool_with_type_and_input_schema():
    tool = Tool.model_validate({
        "name": "custom_tool",
        "type": "custom",
        "description": "A custom tool",
        "input_schema": {"type": "object", "properties": {"x": {"type": "string"}}},
    })
    dumped = tool.model_dump(exclude_none=True)
    assert dumped["name"] == "custom_tool"
    assert dumped["type"] == "custom"
    assert "input_schema" in dumped


def test_tool_without_input_schema():
    """Server tools (e.g. web_search) may omit input_schema."""
    tool = Tool.model_validate({
        "name": "web_search",
        "type": "web_search_20250305",
    })
    dumped = tool.model_dump(exclude_none=True)
    assert dumped["name"] == "web_search"
    assert "input_schema" not in dumped


# ── Validation: missing required fields ──────────────────────────────────

def test_content_block_text_requires_text_field():
    with pytest.raises(ValidationError):
        ContentBlockText.model_validate({"type": "text"})


def test_content_block_tool_use_requires_id():
    with pytest.raises(ValidationError):
        ContentBlockToolUse.model_validate({
            "type": "tool_use",
            "name": "read",
            "input": {},
        })


def test_message_requires_valid_role():
    with pytest.raises(ValidationError):
        Message.model_validate({"role": "invalid_role", "content": "hi"})


def test_messages_request_requires_messages():
    with pytest.raises(ValidationError):
        MessagesRequest.model_validate({"model": "x", "max_tokens": 100})
