"""Tests for .env loading."""

import os

from ideaforge.config import load_dotenv


def test_load_dotenv_sets_unset_vars(tmp_path, monkeypatch):
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("IDEAFORGE_TEST_KEY", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text('HF_TOKEN="hf_test_123"\n# comment\nIDEAFORGE_TEST_KEY=loaded\n')
    loaded = load_dotenv(env_file)
    assert loaded == env_file
    assert os.environ["HF_TOKEN"] == "hf_test_123"
    assert os.environ["IDEAFORGE_TEST_KEY"] == "loaded"


def test_load_dotenv_does_not_override_existing(tmp_path, monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "existing")
    env_file = tmp_path / ".env"
    env_file.write_text("HF_TOKEN=from_file\n")
    load_dotenv(env_file)
    assert os.environ["HF_TOKEN"] == "existing"