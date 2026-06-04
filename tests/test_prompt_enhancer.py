"""Tests for core.prompt_enhancer — unit tests with mocked LLM calls."""

from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path
from typing import Any, cast

import pytest

from core.prompt_enhancer import (
    PromptEnhancementResult,
    _build_enhancement_request,
    _call_enhancement_llm,
    _compact,
    _extract_message_text,
    _extract_non_stream_error,
    _extract_non_stream_text,
    _read_project_context,
    _should_enhance_prompt,
    enhance_prompt,
    enhance_prompt_sync,
    enhance_prompt_with_metadata,
)


class TestCompact:
    def test_empty_text(self):
        assert _compact("") == ""

    def test_single_line(self):
        assert _compact("hello world") == "hello world"

    def test_skips_fences_and_blanks(self):
        text = "line one\n```\nfenced content\n```\n\nline two"
        result = _compact(text)
        assert "line one" in result
        assert "line two" in result
        assert "fenced content" not in result

    def test_respects_max_lines(self):
        text = "\n".join(f"line {i}" for i in range(20))
        result = _compact(text, max_lines=5)
        assert len(result.splitlines()) == 5

    def test_respects_max_chars(self):
        text = "a" * 50 + "\n" + "b" * 50 + "\n" + "c" * 2000
        result = _compact(text, max_chars=100)
        assert len(result) <= 100

    def test_unmatched_fence_does_not_skip_remaining_context(self):
        text = "before\n```\nimportant after"
        result = _compact(text)
        assert "before" in result
        assert "important after" in result


class TestReadProjectContext:
    def test_empty_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = _read_project_context(tmp)
            assert result == ""

    def test_reads_existing_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "CLAUDE.md").write_text("# Project rules\n- Rule 1\n- Rule 2")
            result = _read_project_context(tmp)
            assert "Rule 1" in result

    def test_missing_files_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = _read_project_context(tmp)
            assert isinstance(result, str)


class TestBuildEnhancementRequest:
    def test_includes_context(self):
        req = _build_enhancement_request(
            "fix bug", "some context", model="custom-enhancer-model"
        )
        assert req["model"] == "custom-enhancer-model"
        assert req["max_tokens"] == 512
        assert req["stream"] is True
        assert len(req["messages"]) == 1
        assert req["messages"][0]["role"] == "user"
        assert req["messages"][0]["content"] == "fix bug"
        assert "some context" in req["system"]

    def test_no_context(self):
        req = _build_enhancement_request("fix bug", "")
        assert "Project Context" not in req["system"]

    def test_custom_token_and_stream_options_are_preserved(self):
        req = _build_enhancement_request(
            "fix bug",
            "ctx",
            model="model-y",
            max_tokens=77,
            stream=False,
        )

        assert req["model"] == "model-y"
        assert req["max_tokens"] == 77
        assert req["stream"] is False


class TestShouldEnhancePrompt:
    def test_enhances_normal_text(self):
        assert _should_enhance_prompt("fix the login bug") is True

    def test_skips_slash_commands(self):
        assert _should_enhance_prompt("/compact preserve auth notes") is False
        assert _should_enhance_prompt("   /context all") is False

    def test_skips_empty_prompt(self):
        assert _should_enhance_prompt("   ") is False

    @pytest.mark.parametrize(
        "prompt",
        [
            "\n\t/status",
            " /enhance fix this",
            "\r\n/verify-context",
            "   /doctor",
        ],
    )
    def test_skips_control_inputs_with_leading_whitespace(self, prompt):
        assert _should_enhance_prompt(prompt) is False

    def test_enhances_unicode_product_prompt(self):
        assert _should_enhance_prompt("لطفا جریان پرداخت را تست کن") is True


class TestExtractionContracts:
    def test_extract_message_text_concatenates_mixed_content_blocks(self):
        data = {
            "content": [
                {"type": "text", "text": "first "},
                {"type": "tool_use", "name": "ignored"},
                "second ",
                {"text": "third"},
            ]
        }

        assert _extract_message_text(data) == "first second third"

    @pytest.mark.parametrize(
        ("payload", "expected"),
        [
            ({"content": "direct text"}, "direct text"),
            ({"text": "fallback text"}, "fallback text"),
            ({"completion": "legacy completion"}, "legacy completion"),
        ],
    )
    def test_extract_message_text_supports_proxy_response_shapes(
        self, payload, expected
    ):
        assert _extract_message_text(payload) == expected

    def test_extract_message_text_rejects_non_string_payloads(self):
        assert _extract_message_text({"content": [{"text": 123}, None]}) == ""
        assert _extract_message_text(["not", "a", "dict"]) == ""

    def test_extract_non_stream_error_prefers_nested_error_message(self):
        body = json.dumps({"error": {"message": "bad upstream"}, "message": "outer"})

        assert _extract_non_stream_error(body) == "bad upstream"

    def test_extract_non_stream_text_accepts_pretty_json_body(self):
        body = json.dumps(
            {"content": [{"type": "text", "text": "pretty json enhancement"}]},
            indent=2,
        )

        assert _extract_non_stream_text(body) == "pretty json enhancement"


class TestEnhancePrompt:
    @pytest.mark.asyncio
    async def test_call_llm_reads_non_streaming_json_response(self, monkeypatch):
        class FakeResponse:
            status_code = 200

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            async def aiter_lines(self):
                yield '{"content":[{"type":"text","text":"enhanced from json"}]}'

        class FakeClient:
            def __init__(self, *_args, **_kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            def stream(self, *_args, **_kwargs):
                return FakeResponse()

        monkeypatch.setattr("core.prompt_enhancer.httpx.AsyncClient", FakeClient)

        result = await _call_enhancement_llm(
            {"stream": False},
            1.0,
            api_url="http://proxy/v1/messages",
            api_key="",
        )

        assert result == "enhanced from json"

    @pytest.mark.asyncio
    async def test_call_llm_sends_api_key_and_request_body(self, monkeypatch):
        seen: dict[str, Any] = {}

        class FakeResponse:
            status_code = 200

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            async def aiter_lines(self):
                yield 'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"ok"}}'
                yield "data: [DONE]"

        class FakeClient:
            def __init__(self, *args, **kwargs):
                seen["client_kwargs"] = kwargs

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            def stream(self, method, url, **kwargs):
                seen["method"] = method
                seen["url"] = url
                seen["json"] = kwargs["json"]
                seen["headers"] = kwargs["headers"]
                return FakeResponse()

        monkeypatch.setattr("core.prompt_enhancer.httpx.AsyncClient", FakeClient)

        result = await _call_enhancement_llm(
            {"model": "enhancer", "stream": True},
            3.0,
            api_url="http://proxy/v1/messages",
            api_key="secret-key",
        )

        assert result == "ok"
        assert seen["method"] == "POST"
        assert seen["url"] == "http://proxy/v1/messages"
        assert seen["json"] == {"model": "enhancer", "stream": True}
        assert seen["headers"] == {
            "Content-Type": "application/json",
            "x-api-key": "secret-key",
        }

    @pytest.mark.asyncio
    async def test_call_llm_ignores_invalid_sse_and_joins_text_deltas(
        self, monkeypatch
    ):
        class FakeResponse:
            status_code = 200

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            async def aiter_lines(self):
                yield "event: content_block_delta"
                yield "data: {not json"
                yield 'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"part one "}}'
                yield 'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"part two"}}'
                yield "data: [DONE]"

        class FakeClient:
            def __init__(self, *_args, **_kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            def stream(self, *_args, **_kwargs):
                return FakeResponse()

        monkeypatch.setattr("core.prompt_enhancer.httpx.AsyncClient", FakeClient)

        result = await _call_enhancement_llm(
            {"stream": True},
            1.0,
            api_url="http://proxy/v1/messages",
            api_key="",
        )

        assert result == "part one part two"

    @pytest.mark.asyncio
    async def test_call_llm_non_200_json_error_returns_empty(self, monkeypatch):
        class FakeResponse:
            status_code = 429

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            async def aread(self):
                return b'{"error":{"message":"quota exceeded"}}'

            async def aiter_lines(self):
                raise AssertionError("non-200 responses should be read as a body")

        class FakeClient:
            def __init__(self, *_args, **_kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            def stream(self, *_args, **_kwargs):
                return FakeResponse()

        monkeypatch.setattr("core.prompt_enhancer.httpx.AsyncClient", FakeClient)

        result = await _call_enhancement_llm(
            {"stream": True},
            1.0,
            api_url="http://proxy/v1/messages",
            api_key="",
        )

        assert result == ""

    @pytest.mark.asyncio
    async def test_call_llm_omits_api_key_header_when_empty(self, monkeypatch):
        seen: dict[str, object] = {}

        class FakeResponse:
            status_code = 200

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            async def aiter_lines(self):
                yield '{"text":"ok"}'

        class FakeClient:
            def __init__(self, *_args, **_kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            def stream(self, *_args, **kwargs):
                seen["headers"] = kwargs["headers"]
                return FakeResponse()

        monkeypatch.setattr("core.prompt_enhancer.httpx.AsyncClient", FakeClient)

        result = await _call_enhancement_llm(
            {"stream": False},
            1.0,
            api_url="http://proxy/v1/messages",
            api_key="",
        )

        headers = seen["headers"]
        assert isinstance(headers, dict)
        assert headers == {"Content-Type": "application/json"}
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_call_llm_non_sse_error_object_returns_empty(self, monkeypatch):
        class FakeResponse:
            status_code = 200

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            async def aiter_lines(self):
                yield '{"error":{"message":"provider rejected request"}}'

        class FakeClient:
            def __init__(self, *_args, **_kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            def stream(self, *_args, **_kwargs):
                return FakeResponse()

        monkeypatch.setattr("core.prompt_enhancer.httpx.AsyncClient", FakeClient)

        result = await _call_enhancement_llm(
            {"stream": False},
            1.0,
            api_url="http://proxy/v1/messages",
            api_key="",
        )

        assert result == ""

    def test_returns_original_when_context_fails(self, monkeypatch):
        def failing(*args, **kwargs):
            raise OSError("read error")

        monkeypatch.setattr("core.prompt_enhancer._read_project_context", failing)
        result = asyncio.run(enhance_prompt("fix bug", "/nonexistent"))
        assert result == "fix bug"

    @pytest.mark.asyncio
    async def test_metadata_passes_context_request_and_api_options(self, monkeypatch):
        seen: dict[str, object] = {}
        monkeypatch.setattr(
            "core.prompt_enhancer._read_project_context",
            lambda workspace: f"context from {workspace}",
        )

        async def fake_call(request_body, timeout, *, api_url, api_key):
            seen["request_body"] = request_body
            seen["timeout"] = timeout
            seen["api_url"] = api_url
            seen["api_key"] = api_key
            return "enhanced"

        monkeypatch.setattr("core.prompt_enhancer._call_enhancement_llm", fake_call)

        result = await enhance_prompt_with_metadata(
            "fix bug",
            "/workspace",
            api_url="http://proxy/v1/messages",
            api_key="key",
            model="model-x",
            timeout=7,
        )

        request_body = seen["request_body"]
        assert isinstance(request_body, dict)
        typed_request_body = cast("dict[str, Any]", request_body)
        assert typed_request_body.get("model") == "model-x"
        system = typed_request_body.get("system")
        assert isinstance(system, str)
        assert "context from /workspace" in system
        assert seen["timeout"] == 7
        assert seen["api_url"] == "http://proxy/v1/messages"
        assert seen["api_key"] == "key"
        assert result.status == "enhanced"

    def test_read_project_context_compacts_multiple_files_and_skips_fenced_secret(
        self, tmp_path
    ):
        (tmp_path / "CLAUDE.md").write_text(
            "# Rules\n- Use uv run\n```\nSECRET_TOKEN=abc\n```\n- Keep tests green",
            encoding="utf-8",
        )
        context_dir = tmp_path / ".fcc" / "context"
        context_dir.mkdir(parents=True)
        (context_dir / "decisions.md").write_text(
            "- Prompt enhancer model is configurable.\n",
            encoding="utf-8",
        )

        result = _read_project_context(str(tmp_path))

        assert "Use uv run" in result
        assert "Prompt enhancer model" in result
        assert "SECRET_TOKEN" not in result

    @pytest.mark.asyncio
    async def test_metadata_treats_whitespace_response_as_empty(self, monkeypatch):
        monkeypatch.setattr(
            "core.prompt_enhancer._read_project_context",
            lambda p: "context",
        )

        async def whitespace(*args, **kwargs):
            return " \n\t "

        monkeypatch.setattr("core.prompt_enhancer._call_enhancement_llm", whitespace)

        result = await enhance_prompt_with_metadata("fix bug", "/tmp")

        assert result.status == "empty"
        assert result.enhanced_prompt == "fix bug"

    @pytest.mark.asyncio
    async def test_metadata_truncates_before_reporting_enhanced(self, monkeypatch):
        monkeypatch.setattr(
            "core.prompt_enhancer._read_project_context",
            lambda p: "context",
        )

        async def long_response(*args, **kwargs):
            return "enhanced prompt with a long tail"

        monkeypatch.setattr("core.prompt_enhancer._call_enhancement_llm", long_response)

        result = await enhance_prompt_with_metadata(
            "fix bug",
            "/tmp",
            max_output_chars=15,
        )

        assert result.status == "enhanced"
        assert result.enhanced_prompt == "enhanced prompt"

    @pytest.mark.asyncio
    async def test_returns_original_on_timeout(self, monkeypatch):
        monkeypatch.setattr(
            "core.prompt_enhancer._read_project_context",
            lambda p: "context",
        )

        async def slow(*args, **kwargs):
            await asyncio.sleep(10)
            return "enhanced"

        monkeypatch.setattr("core.prompt_enhancer._call_enhancement_llm", slow)
        result = await enhance_prompt("fix bug", "/tmp", timeout=0.01)
        assert result == "fix bug"

    @pytest.mark.asyncio
    async def test_returns_enhanced_on_success(self, monkeypatch):
        monkeypatch.setattr(
            "core.prompt_enhancer._read_project_context",
            lambda p: "context",
        )

        async def fast(*args, **kwargs):
            return "enhanced prompt"

        monkeypatch.setattr("core.prompt_enhancer._call_enhancement_llm", fast)
        result = await enhance_prompt("fix bug", "/tmp")
        assert result == "enhanced prompt"

    @pytest.mark.asyncio
    async def test_metadata_reports_changed_prompt(self, monkeypatch):
        monkeypatch.setattr(
            "core.prompt_enhancer._read_project_context",
            lambda p: "context",
        )

        async def fast(*args, **kwargs):
            return "enhanced prompt"

        monkeypatch.setattr("core.prompt_enhancer._call_enhancement_llm", fast)
        result = await enhance_prompt_with_metadata("fix bug", "/tmp")

        assert result == PromptEnhancementResult(
            original_prompt="fix bug",
            enhanced_prompt="enhanced prompt",
            status="enhanced",
        )
        assert result.changed is True

    @pytest.mark.asyncio
    async def test_metadata_reports_unchanged_prompt(self, monkeypatch):
        monkeypatch.setattr(
            "core.prompt_enhancer._read_project_context",
            lambda p: "context",
        )

        async def same(*args, **kwargs):
            return "fix bug"

        monkeypatch.setattr("core.prompt_enhancer._call_enhancement_llm", same)
        result = await enhance_prompt_with_metadata("fix bug", "/tmp")

        assert result.status == "unchanged"
        assert result.changed is False

    def test_sync_helper_returns_metadata(self, monkeypatch):
        monkeypatch.setattr(
            "core.prompt_enhancer._read_project_context",
            lambda p: "context",
        )

        async def fast(*args, **kwargs):
            return "enhanced prompt"

        monkeypatch.setattr("core.prompt_enhancer._call_enhancement_llm", fast)
        result = enhance_prompt_sync("fix bug", "/tmp")

        assert result.status == "enhanced"
        assert result.enhanced_prompt == "enhanced prompt"

    @pytest.mark.asyncio
    async def test_truncates_to_max_output(self, monkeypatch):
        monkeypatch.setattr(
            "core.prompt_enhancer._read_project_context",
            lambda p: "context",
        )

        async def long_response(*args, **kwargs):
            return "x" * 3000

        monkeypatch.setattr("core.prompt_enhancer._call_enhancement_llm", long_response)
        result = await enhance_prompt("fix bug", "/tmp", max_output_chars=100)
        assert len(result) <= 100

    @pytest.mark.asyncio
    async def test_returns_original_on_empty_response(self, monkeypatch):
        monkeypatch.setattr(
            "core.prompt_enhancer._read_project_context",
            lambda p: "context",
        )

        async def empty_response(*args, **kwargs):
            return ""

        monkeypatch.setattr(
            "core.prompt_enhancer._call_enhancement_llm", empty_response
        )
        result = await enhance_prompt("fix bug", "/tmp")
        assert result == "fix bug"

    @pytest.mark.asyncio
    async def test_returns_original_on_call_failure(self, monkeypatch):
        monkeypatch.setattr(
            "core.prompt_enhancer._read_project_context",
            lambda p: "context",
        )

        async def failing(*args, **kwargs):
            raise RuntimeError("LLM call failed")

        monkeypatch.setattr("core.prompt_enhancer._call_enhancement_llm", failing)
        result = await enhance_prompt("fix bug", "/tmp")
        assert result == "fix bug"

    @pytest.mark.asyncio
    async def test_slash_command_bypasses_llm_call(self, monkeypatch):
        async def failing_call(*args, **kwargs):
            raise AssertionError("slash commands must not be enhanced")

        result = await enhance_prompt("/compact keep provider decisions", "/tmp")

        assert result == "/compact keep provider decisions"

    # ── Error handling + retry tests ──────────────────────────────────

    @pytest.mark.asyncio
    async def test_connect_error_retries_once_then_fails_with_reason(self, monkeypatch):
        """ConnectError must retry once, then store the error type in reason."""
        from httpx import ConnectError

        monkeypatch.setattr(
            "core.prompt_enhancer._read_project_context",
            lambda p: "context",
        )

        call_count = 0

        async def connect_fail(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            raise ConnectError("Connection refused")

        monkeypatch.setattr("core.prompt_enhancer._call_enhancement_llm", connect_fail)

        result = await enhance_prompt_with_metadata("fix bug", "/tmp")
        assert result.status == "error"
        assert call_count == 2  # Original + 1 retry
        assert "ConnectError" in result.reason
        assert "Connection refused" in result.reason

    @pytest.mark.asyncio
    async def test_non_connect_error_does_not_retry(self, monkeypatch):
        """RuntimeError (not ConnectError) must fail immediately, no retry."""
        monkeypatch.setattr(
            "core.prompt_enhancer._read_project_context",
            lambda p: "context",
        )

        call_count = 0

        async def runtime_fail(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            raise RuntimeError("something broke")

        monkeypatch.setattr("core.prompt_enhancer._call_enhancement_llm", runtime_fail)

        result = await enhance_prompt_with_metadata("fix bug", "/tmp")
        assert result.status == "error"
        assert call_count == 1  # No retry for non-connection errors
        assert "RuntimeError" in result.reason
        assert "something broke" in result.reason

    @pytest.mark.asyncio
    async def test_connect_error_single_retry_succeeds(self, monkeypatch):
        """First call fails with ConnectError, retry succeeds."""
        from httpx import ConnectError

        monkeypatch.setattr(
            "core.prompt_enhancer._read_project_context",
            lambda p: "context",
        )

        call_count = 0

        async def retry_then_ok(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectError("Connection refused")
            return "enhanced after retry"

        monkeypatch.setattr("core.prompt_enhancer._call_enhancement_llm", retry_then_ok)

        result = await enhance_prompt_with_metadata("fix bug", "/tmp")
        assert result.status == "enhanced"
        assert call_count == 2
        assert result.enhanced_prompt == "enhanced after retry"
