from api.models.anthropic import Message, MessagesRequest, TokenCountRequest


def test_messages_request_parses_without_model_mapping_side_effects():
    request = MessagesRequest(
        model="claude-3-opus",
        max_tokens=100,
        messages=[Message(role="user", content="hello")],
    )

    assert request.model == "claude-3-opus"


def test_messages_request_ignores_internal_routing_fields_when_supplied():
    request = MessagesRequest.model_validate(
        {
            "model": "target-model",
            "original_model": "claude-3-opus",
            "resolved_provider_model": "nvidia_nim/target-model",
            "max_tokens": 100,
            "messages": [{"role": "user", "content": "hello"}],
        }
    )

    assert request.model == "target-model"
    assert "original_model" not in request.model_dump()
    assert "resolved_provider_model" not in request.model_dump()


def test_messages_request_moves_system_role_messages_to_top_level_system():
    request = MessagesRequest.model_validate(
        {
            "model": "claude-3-opus",
            "max_tokens": 100,
            "system": "Existing rules.",
            "messages": [
                {"role": "user", "content": "hello"},
                {"role": "system", "content": "Inline rules."},
                {"role": "assistant", "content": "hi"},
                {
                    "role": "system",
                    "content": [{"type": "text", "text": "More inline rules."}],
                },
            ],
        }
    )

    assert [message.role for message in request.messages] == ["user", "assistant"]
    assert request.system == ("Existing rules.\n\nInline rules.\n\nMore inline rules.")


def test_messages_request_preserves_system_blocks_when_appending_system_role_message():
    request = MessagesRequest.model_validate(
        {
            "model": "claude-3-opus",
            "max_tokens": 100,
            "system": [
                {
                    "type": "text",
                    "text": "Cached rules.",
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            "messages": [
                {"role": "system", "content": "Inline rules."},
                {"role": "user", "content": "hello"},
            ],
        }
    )

    dumped = request.model_dump(exclude_none=True)

    assert dumped["system"] == [
        {
            "type": "text",
            "text": "Cached rules.",
            "cache_control": {"type": "ephemeral"},
        },
        {"type": "text", "text": "Inline rules."},
    ]
    assert dumped["messages"] == [{"role": "user", "content": "hello"}]


def test_messages_request_ignores_non_text_dict_system_role_content():
    request = MessagesRequest.model_validate(
        {
            "model": "claude-3-opus",
            "max_tokens": 100,
            "messages": [
                {
                    "role": "system",
                    "content": {"type": "image", "text": "not system text"},
                },
                {"role": "user", "content": "hello"},
            ],
        }
    )

    assert request.system is None
    assert [message.role for message in request.messages] == ["user"]


def test_messages_request_keeps_extracted_system_text_when_existing_system_invalid():
    request = MessagesRequest.model_validate(
        {
            "model": "claude-3-opus",
            "max_tokens": 100,
            "system": {"unexpected": "shape"},
            "messages": [
                {"role": "system", "content": "Inline rules."},
                {"role": "user", "content": "hello"},
            ],
        }
    )

    assert request.system == "Inline rules."


def test_token_count_request_parses_without_model_mapping_side_effects():
    request = TokenCountRequest(
        model="claude-3-sonnet", messages=[Message(role="user", content="hello")]
    )

    assert request.model == "claude-3-sonnet"


def test_token_count_request_moves_system_role_messages_to_top_level_system():
    request = TokenCountRequest.model_validate(
        {
            "model": "claude-3-sonnet",
            "messages": [
                {"role": "system", "content": "Inline rules."},
                {"role": "user", "content": "hello"},
            ],
        }
    )

    assert [message.role for message in request.messages] == ["user"]
    assert request.system == "Inline rules."


def test_messages_request_preserves_thinking_signature():
    request = MessagesRequest.model_validate(
        {
            "model": "claude-3-opus",
            "max_tokens": 100,
            "messages": [
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "thinking",
                            "thinking": "signed thought",
                            "signature": "sig_123",
                        }
                    ],
                }
            ],
        }
    )

    dumped = request.model_dump(exclude_none=True)

    assert dumped["messages"][0]["content"][0]["signature"] == "sig_123"


def test_messages_request_preserves_native_thinking_budget():
    request = MessagesRequest.model_validate(
        {
            "model": "claude-3-opus",
            "max_tokens": 100,
            "messages": [{"role": "user", "content": "think hard"}],
            "thinking": {"type": "enabled", "budget_tokens": 4096},
        }
    )

    dumped = request.model_dump(exclude_none=True)

    assert dumped["thinking"]["type"] == "enabled"
    assert dumped["thinking"]["budget_tokens"] == 4096


def test_messages_request_accepts_adaptive_thinking_type():
    request = MessagesRequest.model_validate(
        {
            "model": "claude-3-opus",
            "max_tokens": 100,
            "messages": [{"role": "user", "content": "hello"}],
            "thinking": {"type": "adaptive"},
        }
    )

    dumped = request.model_dump(exclude_none=True)

    assert dumped["thinking"]["type"] == "adaptive"


def test_messages_request_accepts_anthropic_server_tool_without_input_schema():
    request = MessagesRequest.model_validate(
        {
            "model": "claude-opus-4-7",
            "max_tokens": 100,
            "messages": [{"role": "user", "content": "search"}],
            "tools": [{"type": "web_search_20250305", "name": "web_search"}],
        }
    )

    dumped = request.model_dump(exclude_none=True)

    assert dumped["tools"] == [{"name": "web_search", "type": "web_search_20250305"}]


def test_messages_request_accepts_redacted_thinking_blocks():
    request = MessagesRequest.model_validate(
        {
            "model": "claude-3-opus",
            "max_tokens": 100,
            "messages": [
                {
                    "role": "assistant",
                    "content": [{"type": "redacted_thinking", "data": "opaque"}],
                }
            ],
        }
    )

    dumped = request.model_dump(exclude_none=True)

    assert dumped["messages"][0]["content"][0] == {
        "type": "redacted_thinking",
        "data": "opaque",
    }
