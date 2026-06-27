#!/usr/bin/env python3
"""
IdeaForge - Local-first pipeline for USB voice recorders
Turn meetings into action items and ideas into creations.

Supports:
- USB voice recorders (Z28/Z29 exFAT etc.)
- Transcription + optional speaker diarization
- Structured LLM output (Ollama local or xAI Grok)
"""

import argparse
import hashlib
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

try:
    from faster_whisper import WhisperModel
except ImportError:
    WhisperModel = None

try:
    import ollama
except ImportError:
    ollama = None

try:
    from tqdm import tqdm
except ImportError:
    tqdm = None

import openai  # For xAI Grok

AUDIO_EXTENSIONS = {'.mp3', '.wav', '.m4a', '.aac', '.ogg', '.flac', '.wma', '.opus'}


def compute_file_hash(file_path: Path, block_size: int = 65536) -> str:
    sha256 = hashlib.sha256()
    with open(file_path, 'rb') as f:
        for block in iter(lambda: f.read(block_size), b''):
            sha256.update(block)
    return sha256.hexdigest()


def get_audio_files(source: Path) -> List[Path]:
    files: List[Path] = []
    for ext in AUDIO_EXTENSIONS:
        files.extend(source.rglob(f"*{ext}"))
        files.extend(source.rglob(f"*{ext.upper()}"))
    valid_files = [f for f in files if f.is_file() and f.stat().st_size > 50_000]
    return sorted(valid_files, key=lambda p: p.stat().st_mtime)


def load_processed_log(archive: Path) -> Dict[str, Any]:
    log_path = archive / ".processed_log.json"
    if log_path.exists():
        try:
            return json.loads(log_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"hashes": [], "files": {}}


def save_processed_log(archive: Path, log: Dict[str, Any]) -> None:
    log_path = archive / ".processed_log.json"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(json.dumps(log, indent=2, ensure_ascii=False), encoding="utf-8")


def should_skip_by_hash(file_path: Path, processed_log: Dict[str, Any]) -> bool:
    try:
        h = compute_file_hash(file_path)
        return h in processed_log.get("hashes", [])
    except Exception:
        return False


def copy_file_safely(src: Path, dest_folder: Path) -> Path:
    dest_folder.mkdir(parents=True, exist_ok=True)
    dest = dest_folder / src.name
    if dest.exists():
        h = compute_file_hash(src)[:10]
        dest = dest_folder / f"{src.stem}_{h}{src.suffix}"
    shutil.copy2(src, dest)
    return dest


def transcribe_audio(audio_path: Path, model: WhisperModel, output_dir: Path, force: bool = False) -> Optional[Path]:
    transcript_path = output_dir / f"{audio_path.stem}.txt"
    meta_path = output_dir / f"{audio_path.stem}_whisper.json"

    if transcript_path.exists() and not force:
        print(f"    ↳ Transcript exists → skipping")
        return transcript_path

    print(f"    🎙️  Transcribing {audio_path.name} ...")
    segments, info = model.transcribe(
        str(audio_path),
        beam_size=5,
        vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=500),
    )

    transcript_text = "\n".join(seg.text.strip() for seg in segments if seg.text.strip())

    transcript_path.write_text(transcript_text, encoding="utf-8")

    meta = {
        "audio_file": audio_path.name,
        "duration_seconds": round(info.duration, 1) if info.duration else None,
        "language": info.language,
        "transcribed_at": datetime.now().isoformat(timespec="seconds"),
    }
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    print(f"    ✓ Transcript saved ({len(transcript_text):,} chars)")
    return transcript_path


def llm_process_transcript(transcript_path: Path, args, output_dir: Path, force: bool = False) -> Optional[Path]:
    summary_path = output_dir / f"{transcript_path.stem}_summary.md"
    if summary_path.exists() and not force:
        print(f"    ↳ Summary exists → skipping")
        return summary_path

    transcript = transcript_path.read_text(encoding="utf-8").strip()
    if len(transcript) < 50:
        print("    ⚠️ Transcript too short")
        return None

    if args.llm_backend == "grok":
        client = openai.OpenAI(
            api_key=os.getenv("XAI_API_KEY"),
            base_url="https://api.x.ai/v1"
        )
        model_name = args.grok_model
        print(f"    🤖 Using xAI Grok ({model_name})")
    else:
        if ollama is None:
            print("Ollama not available")
            return None
        client = ollama.Client()
        model_name = args.ollama_model
        print(f"    🤖 Using Ollama ({model_name})")

    prompt = f"""You are an expert meeting and creative analyst.

Analyze this diarized voice transcript and output **only** this Markdown:

## 🎯 Executive Summary
(2-4 sentences)

## 👥 Speakers & Contributions
(SPEAKER labels with context)

## 📋 Key Points

## ✅ Action Items
- Who | What | When (infer where possible)

## 🔑 Decisions & Insights

## 💡 Creative Sparks
(Song ideas, lyrics themes, etc. if relevant)

Transcript:
{transcript[:18000]}"""

    try:
        if args.llm_backend == "grok":
            response = client.chat.completions.create(
                model=model_name,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3
            )
            content = response.choices[0].message.content
        else:
            response = client.chat(
                model=model_name,
                messages=[{"role": "user", "content": prompt}]
            )
            content = response['message']['content']

        summary_path.write_text(content.strip(), encoding="utf-8")
        print(f"    ✓ Summary saved: {summary_path.name}")
        return summary_path
    except Exception as e:
        print(f"    ❌ LLM error: {e}")
        return None


def main():
    parser = argparse.ArgumentParser(description="IdeaForge - Voice to Notes & Creations")
    parser.add_argument("--source", type=Path, required=True, help="Mounted recorder path")
    parser.add_argument("--archive", type=Path, default=Path.home() / "IdeaForge", help="Archive root")
    parser.add_argument("--llm-backend", default="ollama", choices=["ollama", "grok"])
    parser.add_argument("--ollama-model", default="llama3.1")
    parser.add_argument("--grok-model", default="grok-2")
    parser.add_argument("--whisper-model", default="medium", choices=["tiny", "base", "small", "medium", "large-v3"])
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--no-copy", action="store_true")
    parser.add_argument("--no-transcribe", action="store_true")
    parser.add_argument("--no-llm", action="store_true")
    parser.add_argument("--list-only", action="store_true")

    args = parser.parse_args()

    source = args.source.expanduser().resolve()
    archive = args.archive.expanduser().resolve()

    if not source.exists() or not source.is_dir():
        print(f"❌ Source not found: {source}")
        sys.exit(1)

    print(f"🚀 IdeaForge | Source: {source} | Archive: {archive}")

    audio_files = get_audio_files(source)
    print(f"Found {len(audio_files)} audio files.")

    if args.list_only:
        for f in audio_files:
            print(f"  {f.name}")
        return

    processed_log = load_processed_log(archive)

    whisper_model = None
    if not args.no_transcribe and WhisperModel is not None:
        print(f"Loading Whisper {args.whisper_model}...")
        whisper_model = WhisperModel(args.whisper_model, device="cpu", compute_type="int8")

    newly_processed = 0
    iterator = tqdm(audio_files, desc="Processing") if tqdm else audio_files

    for audio_file in iterator:
        if should_skip_by_hash(audio_file, processed_log) and not args.force:
            continue

        mtime = datetime.fromtimestamp(audio_file.stat().st_mtime)
        date_folder = archive / mtime.strftime("%Y-%m-%d")

        print(f"\n📼 Processing {audio_file.name}")

        process_path = audio_file
        if not args.no_copy:
            process_path = copy_file_safely(audio_file, date_folder)
            print(f"   📥 Copied")

        transcript_path = None
        if not args.no_transcribe and whisper_model:
            transcript_path = transcribe_audio(process_path, whisper_model, date_folder, args.force)

        if not args.no_llm and transcript_path:
            llm_process_transcript(transcript_path, args, date_folder, args.force)

        # Update log
        h = compute_file_hash(audio_file)
        if h not in processed_log["hashes"]:
            processed_log["hashes"].append(h)
            newly_processed += 1

    save_processed_log(archive, processed_log)
    print(f"\n✅ IdeaForge complete! Newly processed: {newly_processed}")


if __name__ == "__main__":
    main()
