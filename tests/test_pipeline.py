"""Tests for pipeline stage resolution."""

import argparse

from ideaforge.config import IdeaForgeConfig
from ideaforge.pipeline import resolve_stages, should_skip_file


def _args(**kwargs):
    defaults = {
        "no_copy": False,
        "no_transcribe": False,
        "no_llm": False,
        "transcribe_only": False,
        "diarize_only": False,
        "llm_only": False,
    }
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def test_llm_only_stages():
    stages = resolve_stages(_args(llm_only=True), IdeaForgeConfig())
    assert stages.llm and not stages.transcribe and not stages.diarize and not stages.copy


def test_diarize_only_stages():
    stages = resolve_stages(_args(diarize_only=True), IdeaForgeConfig())
    assert stages.diarize and not stages.transcribe and stages.llm


def test_diarize_only_respects_no_llm():
    stages = resolve_stages(_args(diarize_only=True, no_llm=True), IdeaForgeConfig())
    assert stages.diarize and not stages.llm


def test_transcribe_only_stages():
    stages = resolve_stages(_args(transcribe_only=True), IdeaForgeConfig())
    assert stages.transcribe and not stages.llm and not stages.diarize


def test_should_skip_llm_only_when_summary_exists():
    from ideaforge.pipeline import PipelineStages

    skip = should_skip_file(
        stages=PipelineStages(copy=False, transcribe=False, diarize=False, llm=True),
        force=False,
        already_processed=False,
        transcript_exists=True,
        summary_exists=True,
        diarized_exists=False,
    )
    assert skip