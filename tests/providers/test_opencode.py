"""Tests for OpenCode Zen provider (OpenAI-compatible Chat Completions)."""
from __future__ import annotations

import pytest

from providers.opencode import OpenCodeProvider
from providers.base import ProviderConfig


class TestOpenCodeProvider:
    """Unit tests for OpenCode Zen provider."""

    def test_init_uses_default_base_url(self):
        """OpenCode defaults to opencode.ai/zen when no base_url is given."""
        config = ProviderConfig(api_key="test-key")
        provider = OpenCodeProvider(config)
        assert "opencode.ai" in str(provider._base_url)

    def test_init_uses_custom_base_url(self):
        """Custom base_url overrides the default."""
        config = ProviderConfig(api_key="test-key", base_url="https://custom.ai/zen/v1")
        provider = OpenCodeProvider(config)
        assert provider._base_url == "https://custom.ai/zen/v1"

    def test_init_strips_trailing_slash(self):
        """Base URL is normalized (trailing slashes stripped)."""
        config = ProviderConfig(api_key="test-key", base_url="https://custom.ai/zen/v1/")
        provider = OpenCodeProvider(config)
        assert not provider._base_url.endswith("/")

    def test_provider_name_defaults_to_opencode(self):
        """Default provider name is OPENCODE."""
        config = ProviderConfig(api_key="test-key")
        provider = OpenCodeProvider(config)
        assert provider._provider_name == "OPENCODE"

    def test_provider_name_custom(self):
        """Provider name can be overridden (e.g. OPENCODE_GO)."""
        config = ProviderConfig(api_key="test-key")
        provider = OpenCodeProvider(config, provider_name="OPENCODE_GO")
        assert provider._provider_name == "OPENCODE_GO"

    def test_provider_has_api_key(self):
        """API key is forwarded to the provider config."""
        config = ProviderConfig(api_key="sk-test-123")
        provider = OpenCodeProvider(config)
        assert provider._config.api_key == "sk-test-123"
