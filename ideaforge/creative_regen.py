"""Regenerate creative/song outputs from an existing transcript (no re-transcribe)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ideaforge.config import IdeaForgeConfig
from ideaforge.llm import process_transcript
from ideaforge.session_layout import session_artifact_paths
from ideaforge.summary_names import resolve_summary_md_path


def find_session_dir(root: Path, session_stem: str) -> Optional[Path]:
    """Find ``…/R…/`` session package or flat location containing the stem."""
    direct = root / session_stem
    if direct.is_dir():
        return direct
    if root.is_dir():
        for path in root.rglob(session_stem):
            if path.is_dir() and path.name == session_stem:
                return path
    return None


def find_session_artifacts(
    archive_or_folder: Path,
    session_stem: str,
) -> Optional[Dict[str, Path]]:
    """Locate transcript + dirs for a session stem under an archive tree."""
    root = archive_or_folder.expanduser().resolve()
    session_dir = find_session_dir(root, session_stem)
    if session_dir is not None:
        paths = session_artifact_paths(session_dir, session_stem)
        if paths["transcript"].is_file():
            return paths
    if root.is_dir():
        for path in root.rglob(f"{session_stem}.txt"):
            return session_artifact_paths(path.parent, session_stem)
    return None


def creative_sidecar_paths(session_dir: Path, session_stem: str) -> Dict[str, Path]:
    return {
        "suno": session_dir / f"{session_stem}_suno.txt",
        "udio": session_dir / f"{session_stem}_udio.txt",
    }


def prior_creative_seed(summary_json: Path) -> Optional[Dict[str, Any]]:
    if not summary_json.is_file():
        return None
    try:
        data = json.loads(summary_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    intent = data.get("intent") or (data.get("metadata") or {}).get("output_intent")
    if intent != "song_idea" and "suno_style_prompt" not in data and "chorus_hook" not in data:
        return None
    return data


def regenerate_creative(
    source: Path,
    session_stem: str,
    cfg: IdeaForgeConfig,
    *,
    seed_from_prior: bool = True,
) -> Tuple[int, Optional[Path], str]:
    """Force re-run creative LLM for one session. Returns (exit_code, md_path, message)."""
    paths = find_session_artifacts(source, session_stem)
    if paths is None:
        return 1, None, f"No transcript found for session {session_stem!r} under {source}"

    transcript = paths["transcript"]
    output_dir = paths["session_dir"]
    seed = prior_creative_seed(paths["summary_json"]) if seed_from_prior else None
    if seed:
        print(f"   ↻ Seeding regenerate from prior {paths['summary_json'].name}")

    # Optional: prepend prior hooks into creative settings via print only;
    # process_transcript already rebuilds from transcript. Seed is informational
    # for the operator and stored back via new metadata.
    result = process_transcript(
        transcript,
        output_dir,
        mode="creative",
        backend=cfg.resolve_llm_backend(),
        ollama_model=cfg.ollama_model,
        grok_model=cfg.grok_model,
        claude_model=cfg.claude_model,
        output_format=cfg.output_format,
        force=True,
        archive=cfg.archive.expanduser(),
        creative_settings=cfg.creative_settings(),
        suno_style=cfg.creative_suno_style(),
        udio_style=cfg.creative_udio_style(),
    )
    if result is None:
        return 1, None, "Creative regenerate failed (no output)"

    # Prefer friendly markdown path
    md = resolve_summary_md_path(output_dir, session_stem) or result
    if seed and paths["summary_json"].is_file():
        try:
            data = json.loads(paths["summary_json"].read_text(encoding="utf-8"))
            meta = dict(data.get("metadata") or {})
            meta["regenerated_from"] = seed.get("title") or session_stem
            data["metadata"] = meta
            paths["summary_json"].write_text(
                json.dumps(data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except (OSError, json.JSONDecodeError, TypeError):
            pass

    sidecars = creative_sidecar_paths(output_dir, session_stem)
    extra = []
    for name, path in sidecars.items():
        if path.is_file():
            extra.append(path.name)
    msg = f"Regenerated {md.name}"
    if extra:
        msg += f" (+ {', '.join(extra)})"
    return 0, Path(md) if not isinstance(md, Path) else md, msg


def list_sidecars_for_note_path(
    note_path: str,
    *,
    stem: Optional[str] = None,
) -> List[Tuple[str, Path]]:
    """Return (label, path) for existing suno/udio sidecars near a notes file."""
    md = Path(note_path)
    candidates: List[Path] = [md.parent]
    if stem:
        candidates.append(md.parent / stem)
        candidates.append(md.parent.parent / stem)
    # session package parent of date-folder notes
    if md.parent.name and len(md.parent.name) == 10:
        for child in md.parent.iterdir() if md.parent.is_dir() else []:
            if child.is_dir() and child.name.startswith("R20"):
                if stem is None or child.name == stem:
                    candidates.append(child)

    found: List[Tuple[str, Path]] = []
    seen: set[str] = set()
    stems: List[str] = []
    if stem:
        stems.append(stem)
    # Infer stem from sibling json
    for base in candidates:
        for json_path in base.glob("*_summary.json") if base.is_dir() else []:
            s = json_path.name[: -len("_summary.json")]
            if s not in stems:
                stems.append(s)

    for base in candidates:
        if not base.is_dir():
            continue
        for s in stems or [""]:
            if not s:
                continue
            for label, name in (
                ("Suno", f"{s}_suno.txt"),
                ("Udio", f"{s}_udio.txt"),
            ):
                path = base / name
                key = str(path.resolve()) if path.exists() else ""
                if path.is_file() and key not in seen:
                    seen.add(key)
                    found.append((label, path))
    return found
