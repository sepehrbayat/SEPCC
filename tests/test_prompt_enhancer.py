"""Tests for core.prompt_enhancer — unit tests with mocked LLM calls."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import pytest

from core.prompt_enhancer import (
    _build_enhancement_request,
    _compact,
    _read_project_context,
    _should_enhance_prompt,
    enhance_prompt,
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
        req = _build_enhancement_request("fix bug", "some context")
        assert req["model"] == "claude-haiku-4-5-20251001"
        assert req["max_tokens"] == 512
        assert req["stream"] is True
        assert len(req["messages"]) == 1
        assert req["messages"][0]["role"] == "user"
        assert req["messages"][0]["content"] == "fix bug"
        assert "some context" in req["system"]

    def test_no_context(self):
        req = _build_enhancement_request("fix bug", "")
        assert "Project Context" not in req["system"]


class TestShouldEnhancePrompt:
    def test_enhances_normal_text(self):
        assert _should_enhance_prompt("fix the login bug") is True

    def test_skips_slash_commands(self):
        assert _should_enhance_prompt("/compact preserve auth notes") is False
        assert _should_enhance_prompt("   /context all") is False

    def test_skips_empty_prompt(self):
        assert _should_enhance_prompt("   ") is False


class TestEnhancePrompt:
    def test_returns_original_when_context_fails(self, monkeypatch):
        def failing(*args, **kwargs):
            raise OSError("read error")

        monkeypatch.setattr("core.prompt_enhancer._read_project_context", failing)
        result = asyncio.run(enhance_prompt("fix bug", "/nonexistent"))
        assert result == "fix bug"

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

        monkeypatch.setattr("core.prompt_enhancer._call_enhancement_llm", failing_call)
        result = await enhance_prompt("/compact keep provider decisions", "/tmp")

        assert result == "/compact keep provider decisions"
