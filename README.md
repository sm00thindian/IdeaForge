# IdeaForge

**Local-first pipeline for USB voice recorders. Turn meetings into action items and ideas into creations.**

Process recordings from devices like the Z28/Z29 (exFAT USB) → diarized transcription → structured LLM notes (Ollama or xAI Grok).

## Features
- **USB Recorder Ingestion**: Safe copy from mounted exFAT drives into dated archive.
- **Transcription & Diarization**: Faster-Whisper / WhisperX + pyannote for speaker labels.
- **LLM Processing**: High-quality structured output via Ollama (local) or Grok (xAI API) for:
  - Meeting mode: Executive summary, key points, **action items**, decisions.
  - Creative mode (upcoming): Lyrics, song structure, Suno v5.5 prompts.
- Fully local by default. Private. No GUI required (CLI-first).
- Extensible for song writing, journal entries, compliance notes, etc.

## Quick Start
(See detailed setup in the README or docs.)

```bash
# After plugging in recorder
python ideaforge.py --source /Volumes/Z29 --llm-backend grok   # or ollama
