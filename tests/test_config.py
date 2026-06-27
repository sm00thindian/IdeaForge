"""Tests for config and LLM backend resolution."""

import os

from ideaforge.config import IdeaForgeConfig, has_anthropic_api_key, has_xai_api_key


def test_has_xai_api_key_false(monkeypatch):
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    assert not has_xai_api_key()


def test_has_xai_api_key_true(monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", "xai-test-key")
    assert has_xai_api_key()


def test_resolve_llm_backend_auto_prefers_grok(monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", "xai-test-key")
    cfg = IdeaForgeConfig(llm_backend="auto")
    assert cfg.resolve_llm_backend() == "grok"


def test_resolve_llm_backend_auto_falls_back_to_ollama(monkeypatch):
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    cfg = IdeaForgeConfig(llm_backend="auto")
    assert cfg.resolve_llm_backend() == "ollama"


def test_resolve_llm_backend_cli_override(monkeypatch):
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    cfg = IdeaForgeConfig(llm_backend="auto")
    assert cfg.resolve_llm_backend(cli_override="ollama") == "ollama"


def test_resolve_llm_backend_grok_without_key_falls_back(monkeypatch):
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    cfg = IdeaForgeConfig(llm_backend="grok")
    assert cfg.resolve_llm_backend() == "ollama"


def test_has_anthropic_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert not has_anthropic_api_key()
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    assert has_anthropic_api_key()


def test_resolve_llm_backend_auto_still_prefers_grok_over_claude(monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", "xai-test-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    cfg = IdeaForgeConfig(llm_backend="auto")
    assert cfg.resolve_llm_backend() == "grok"


def test_resolve_llm_backend_claude_explicit(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    cfg = IdeaForgeConfig(llm_backend="claude")
    assert cfg.resolve_llm_backend() == "claude"


def test_resolve_llm_backend_claude_without_key_falls_back(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    cfg = IdeaForgeConfig(llm_backend="claude")
    assert cfg.resolve_llm_backend() == "ollama"