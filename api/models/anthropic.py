"""Pydantic models for Anthropic-compatible requests."""

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.anthropic.content import get_block_attr, get_block_type


# =============================================================================
# Content Block Types
# =============================================================================
class Role(StrEnum):
    user = "user"
    assistant = "assistant"
    system = "system"


class _AnthropicBlockBase(BaseModel):
    """Pass through provider fields (e.g. ``cache_control``) for native transports."""

    model_config = ConfigDict(extra="allow")


class ContentBlockText(_AnthropicBlockBase):
    type: Literal["text"]
    text: str


class ContentBlockImage(_AnthropicBlockBase):
    type: Literal["image"]
    source: dict[str, Any]


class ContentBlockDocument(_AnthropicBlockBase):
    """Anthropic document block (e.g. PDF files via the Files API)."""

    type: Literal["document"]
    source: dict[str, Any]


class ContentBlockToolUse(_AnthropicBlockBase):
    type: Literal["tool_use"]
    id: str
    name: str
    input: dict[str, Any]


class ContentBlockToolResult(_AnthropicBlockBase):
    type: Literal["tool_result"]
    tool_use_id: str
    content: str | list[Any] | dict[str, Any]


class ContentBlockThinking(_AnthropicBlockBase):
    type: Literal["thinking"]
    thinking: str
    signature: str | None = None


class ContentBlockRedactedThinking(_AnthropicBlockBase):
    type: Literal["redacted_thinking"]
    data: str


class ContentBlockServerToolUse(_AnthropicBlockBase):
    """Anthropic server-side tool invocation (e.g. ``web_search``, ``web_fetch``)."""

    type: Literal["server_tool_use"]
    id: str
    name: str
    input: dict[str, Any]


class ContentBlockWebSearchToolResult(_AnthropicBlockBase):
    type: Literal["web_search_tool_result"]
    tool_use_id: str
    content: Any


class ContentBlockWebFetchToolResult(_AnthropicBlockBase):
    type: Literal["web_fetch_tool_result"]
    tool_use_id: str
    content: Any


class SystemContent(_AnthropicBlockBase):
    type: Literal["text"]
    text: str


def _extract_system_message_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text_parts: list[str] = []
        for block in content:
            if get_block_type(block) != "text":
                continue
            text = get_block_attr(block, "text", "")
            if isinstance(text, str) and text:
                text_parts.append(text)
        return "\n\n".join(text_parts)
    if isinstance(content, dict):
        if content.get("type") != "text":
            return ""
        text = content.get("text")
        if isinstance(text, str):
            return text
    return "" if content is None else str(content)


def _append_system_text(system: Any, system_texts: list[str]) -> Any:
    text_parts = [text for text in system_texts if text]
    if not text_parts:
        return system

    if isinstance(system, list):
        return [
            *system,
            *({"type": "text", "text": text} for text in text_parts),
        ]

    appended = "\n\n".join(text_parts)
    if isinstance(system, str):
        return f"{system}\n\n{appended}" if system else appended
    if system is None:
        return appended
    return appended


def _normalize_system_role_messages(data: Any) -> Any:
    """Move OpenAI-style system-role messages into Anthropic's top-level system."""
    if not isinstance(data, dict):
        return data

    messages = data.get("messages")
    if not isinstance(messages, list):
        return data

    normalized_messages: list[Any] = []
    system_texts: list[str] = []
    for message in messages:
        if isinstance(message, dict) and message.get("role") == Role.system:
            system_texts.append(_extract_system_message_text(message.get("content")))
            continue
        normalized_messages.append(message)

    if not system_texts:
        return data

    normalized = dict(data)
    normalized["messages"] = normalized_messages
    normalized["system"] = _append_system_text(normalized.get("system"), system_texts)
    return normalized


# =============================================================================
# Message Types
# =============================================================================
class Message(BaseModel):
    """One turn in an Anthropic Messages conversation — user or assistant.

    Content is a polymorphic union of text, image, document, tool-use,
    tool-result, thinking, and server-tool blocks.
    """

    role: Literal["user", "assistant"]
    content: (
        str
        | list[
            ContentBlockText
            | ContentBlockImage
            | ContentBlockDocument
            | ContentBlockToolUse
            | ContentBlockToolResult
            | ContentBlockThinking
            | ContentBlockRedactedThinking
            | ContentBlockServerToolUse
            | ContentBlockWebSearchToolResult
            | ContentBlockWebFetchToolResult
        ]
    )
    reasoning_content: str | None = None


class Tool(_AnthropicBlockBase):
    name: str
    # Anthropic server tools (e.g. web_search beta tools) include a ``type`` and
    # may omit ``input_schema`` because the provider owns the schema.
    type: str | None = None
    description: str | None = None
    input_schema: dict[str, Any] | None = None


class ThinkingConfig(BaseModel):
    enabled: bool | None = True
    type: str | None = None
    budget_tokens: int | None = None


# =============================================================================
# Request Models
# =============================================================================
class MessagesRequest(BaseModel):
    """Inbound Anthropic Messages POST body — the core API contract.

    Accepts model, messages, system prompt, tools, thinking config, and
    metadata.  Internal routing fields are parsed but stripped before
    forwarding to downstream providers.
    """

    model_config = ConfigDict(extra="allow")

    model: str
    # Internal routing / debug: accepted on parse but not serialized to providers.
    original_model: str | None = Field(default=None, exclude=True)
    resolved_provider_model: str | None = Field(default=None, exclude=True)
    max_tokens: int | None = None
    messages: list[Message]
    system: str | list[SystemContent] | None = None
    stop_sequences: list[str] | None = None
    stream: bool | None = True
    temperature: float | None = None
    top_p: float | None = None
    top_k: int | None = None
    metadata: dict[str, Any] | None = None
    tools: list[Tool] | None = None
    tool_choice: dict[str, Any] | None = None
    thinking: ThinkingConfig | None = None
    # Native Anthropic / SDK client hints: ignored (not forwarded) for OpenAI Chat conversion.
    context_management: dict[str, Any] | None = None
    output_config: dict[str, Any] | None = None
    mcp_servers: list[dict[str, Any]] | None = None
    extra_body: dict[str, Any] | None = None
    # Beta feature flags sent by Claude Code as a body field; accepted but never forwarded.
    betas: list[str] | None = Field(default=None, exclude=True)

    @model_validator(mode="before")
    @classmethod
    def normalize_system_role_messages(cls, data: Any) -> Any:
        return _normalize_system_role_messages(data)


class TokenCountRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    model: str
    original_model: str | None = Field(default=None, exclude=True)
    resolved_provider_model: str | None = Field(default=None, exclude=True)
    messages: list[Message]
    system: str | list[SystemContent] | None = None
    tools: list[Tool] | None = None
    thinking: ThinkingConfig | None = None
    tool_choice: dict[str, Any] | None = None
    context_management: dict[str, Any] | None = None
    output_config: dict[str, Any] | None = None
    mcp_servers: list[dict[str, Any]] | None = None
    betas: list[str] | None = Field(default=None, exclude=True)

    @model_validator(mode="before")
    @classmethod
    def normalize_system_role_messages(cls, data: Any) -> Any:
        return _normalize_system_role_messages(data)
