"""Pipeline stage resolution."""

from __future__ import annotations

import argparse
from dataclasses import dataclass

from ideaforge.config import IdeaForgeConfig


@dataclass
class PipelineStages:
    copy: bool
    transcribe: bool
    diarize: bool
    llm: bool

    @property
    def label(self) -> str:
        parts = []
        if self.copy:
            parts.append("copy")
        if self.transcribe:
            parts.append("transcribe")
        if self.diarize:
            parts.append("diarize")
        if self.llm:
            parts.append("llm")
        return " → ".join(parts) if parts else "none"


def resolve_stages(args: argparse.Namespace, cfg: IdeaForgeConfig) -> PipelineStages:
    """Resolve which pipeline stages to run."""
    if getattr(args, "llm_only", False):
        return PipelineStages(copy=False, transcribe=False, diarize=False, llm=True)

    if getattr(args, "diarize_only", False):
        return PipelineStages(
            copy=False,
            transcribe=False,
            diarize=True,
            llm=not args.no_llm,
        )

    if getattr(args, "transcribe_only", False):
        return PipelineStages(
            copy=not args.no_copy,
            transcribe=True,
            diarize=False,
            llm=False,
        )

    return PipelineStages(
        copy=not args.no_copy,
        transcribe=not args.no_transcribe,
        diarize=cfg.diarize,
        llm=not args.no_llm,
    )


def should_skip_file(
    *,
    stages: PipelineStages,
    force: bool,
    already_processed: bool,
    transcript_exists: bool,
    summary_exists: bool,
    diarized_exists: bool,
) -> bool:
    """Decide whether to skip a file based on stage mode and existing outputs."""
    if force:
        return False

    if stages.llm and not stages.transcribe and not stages.diarize:
        return summary_exists

    if stages.diarize and not stages.transcribe:
        return diarized_exists and transcript_exists

    if already_processed and stages.transcribe:
        if stages.diarize:
            return transcript_exists and diarized_exists
        return transcript_exists

    return False