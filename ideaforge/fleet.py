"""Fleet-wide status: pipeline, devices, queues across archive roots."""

from __future__ import annotations

import json
import re
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ideaforge import __version__
from ideaforge.config import IdeaForgeConfig
from ideaforge.device_registry import archive_device_root, find_recorder_mounts
from ideaforge.health import check_daemon_health, check_menubar_health
from ideaforge.ingest import failed_session_stems, get_audio_files, is_derived_audio, load_processed_log
from ideaforge.status import PipelineStatus, default_status_path, format_elapsed, load_status

_DATE_FOLDER = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _device_roots(cfg: IdeaForgeConfig) -> List[Tuple[str, Path]]:
    archive = cfg.archive.expanduser().resolve()
    if cfg.devices:
        return [
            (binding.name, archive_device_root(cfg, binding.name))
            for binding in cfg.devices
        ]
    return [("default", archive)]


def _count_pending_audio(archive_root: Path, min_size_bytes: int) -> List[str]:
    if not archive_root.is_dir():
        return []

    extensions = {".wav", ".WAV", ".mp3", ".MP3", ".flac", ".FLAC", ".m4a", ".M4A"}
    pending: List[str] = []

    date_dirs = [
        path
        for path in sorted(archive_root.iterdir())
        if path.is_dir() and _DATE_FOLDER.match(path.name)
    ]
    if not date_dirs and archive_root.is_dir():
        date_dirs = [archive_root]

    for folder in date_dirs:
        for audio in get_audio_files(folder, extensions, min_size_bytes):
            if is_derived_audio(audio):
                continue
            transcript = folder / f"{audio.stem}.txt"
            if not transcript.exists():
                pending.append(audio.stem)
    return sorted(set(pending))


def _device_snapshot(
    name: str,
    archive_root: Path,
    *,
    min_size_bytes: int,
) -> Dict[str, Any]:
    processed_log = load_processed_log(archive_root)
    failures = sorted(failed_session_stems(processed_log))
    pending = _count_pending_audio(archive_root, min_size_bytes)
    return {
        "name": name,
        "archive_root": str(archive_root),
        "failure_count": len(failures),
        "failures": failures,
        "pending_sessions": pending,
        "pending_count": len(pending),
        "processed_files": len(processed_log.get("files", {})),
    }


def collect_fleet_snapshot(cfg: IdeaForgeConfig) -> Dict[str, Any]:
    """Aggregate pipeline status and per-device archive queues."""
    pipeline: PipelineStatus = load_status()
    daemon = check_daemon_health()
    menubar = check_menubar_health()
    mounts = find_recorder_mounts(cfg=cfg)

    devices = [
        _device_snapshot(
            name,
            root,
            min_size_bytes=cfg.min_file_size_bytes,
        )
        for name, root in _device_roots(cfg)
    ]

    total_failures = sum(device["failure_count"] for device in devices)
    total_pending = sum(device["pending_count"] for device in devices)

    return {
        "version": __version__,
        "archive": str(cfg.archive.expanduser().resolve()),
        "pipeline": pipeline.to_dict(),
        "services": {
            "daemon": asdict(daemon),
            "menubar": asdict(menubar),
        },
        "recorders": [
            {
                "name": device.device_name or device.label,
                "label": device.label,
                "mount_path": str(device.mount_path),
                "profile": device.profile_name,
                "recording_count": device.recording_count,
            }
            for device in mounts
        ],
        "devices": devices,
        "queue": {
            "failure_count": total_failures,
            "pending_count": total_pending,
        },
        "paths": {
            "status_json": str(default_status_path()),
        },
    }


def _pipeline_headline(status: PipelineStatus) -> str:
    if status.stage and status.state == "processing":
        return status.stage
    return status.state.replace("_", " ").title()


def format_fleet_report(cfg: IdeaForgeConfig) -> str:
    snapshot = collect_fleet_snapshot(cfg)
    pipeline = load_status()
    lines = [
        f"IdeaForge v{__version__} fleet",
        "─" * 44,
        "",
        "Pipeline",
        f"  State:      {_pipeline_headline(pipeline)}",
    ]
    if pipeline.device:
        lines.append(f"  Device:     {pipeline.device}")
    if pipeline.detail:
        lines.append(f"  Detail:     {pipeline.detail}")
    elapsed = format_elapsed(pipeline)
    if elapsed != "—":
        lines.append(f"  Elapsed:    {elapsed}")
    if pipeline.sessions_total > 1 and pipeline.session:
        lines.append(f"  Session:    {pipeline.session}/{pipeline.sessions_total}")

    daemon = snapshot["services"]["daemon"]
    menubar = snapshot["services"]["menubar"]
    lines.extend([
        "",
        "Services",
        f"  Daemon:     {'running' if daemon['running'] else 'stopped'}"
        + (f" (pid {daemon['pid']})" if daemon.get("pid") else ""),
        f"  Menubar:    {'running' if menubar['running'] else 'stopped'}",
        "",
        "Devices",
    ])

    recorders = snapshot["recorders"]
    if recorders:
        for rec in recorders:
            lines.append(
                f"  Mounted:    {rec['name']} — {rec['recording_count']} file(s) "
                f"at {rec['mount_path']}"
            )
    else:
        lines.append("  Mounted:    none")

    for device in snapshot["devices"]:
        lines.append("")
        lines.append(f"  [{device['name']}] {device['archive_root']}")
        lines.append(f"    Processed:  {device['processed_files']} file(s)")
        if device["failure_count"]:
            preview = ", ".join(device["failures"][:2])
            extra = f" (+{device['failure_count'] - 2})" if device["failure_count"] > 2 else ""
            lines.append(f"    Failures:   {device['failure_count']} — {preview}{extra}")
        else:
            lines.append("    Failures:   none")
        if device["pending_count"]:
            preview = ", ".join(device["pending_sessions"][:2])
            extra = (
                f" (+{device['pending_count'] - 2})"
                if device["pending_count"] > 2
                else ""
            )
            lines.append(f"    Queue:      {device['pending_count']} — {preview}{extra}")
        else:
            lines.append("    Queue:      empty")

    lines.append("")
    lines.append(
        f"Totals: {snapshot['queue']['failure_count']} failure(s), "
        f"{snapshot['queue']['pending_count']} pending session(s)"
    )
    return "\n".join(lines)


def render_fleet_html(snapshot: Dict[str, Any]) -> str:
    """Minimal read-only dashboard page."""
    payload = json.dumps(snapshot, indent=2, ensure_ascii=False)
    devices_rows = ""
    for device in snapshot.get("devices", []):
        devices_rows += (
            f"<tr><td>{device['name']}</td>"
            f"<td>{device['failure_count']}</td>"
            f"<td>{device['pending_count']}</td>"
            f"<td><code>{device['archive_root']}</code></td></tr>"
        )

    pipeline = snapshot.get("pipeline", {})
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta http-equiv="refresh" content="5" />
  <title>IdeaForge Fleet</title>
  <style>
    body {{ font-family: -apple-system, sans-serif; margin: 2rem; color: #111; }}
    h1 {{ font-size: 1.4rem; }}
    table {{ border-collapse: collapse; margin: 1rem 0; }}
    th, td {{ border: 1px solid #ccc; padding: 0.4rem 0.6rem; text-align: left; }}
    pre {{ background: #f6f6f6; padding: 1rem; overflow: auto; }}
    .muted {{ color: #666; }}
  </style>
</head>
<body>
  <h1>IdeaForge Fleet <span class="muted">v{snapshot.get('version', '')}</span></h1>
  <p>Pipeline: <strong>{pipeline.get('stage') or pipeline.get('state', 'unknown')}</strong>
     — {pipeline.get('detail') or 'no detail'}</p>
  <p>Queue: {snapshot.get('queue', {}).get('failure_count', 0)} failure(s),
     {snapshot.get('queue', {}).get('pending_count', 0)} pending session(s)</p>
  <table>
    <thead><tr><th>Device</th><th>Failures</th><th>Pending</th><th>Archive</th></tr></thead>
    <tbody>{devices_rows}</tbody>
  </table>
  <h2>Snapshot JSON</h2>
  <pre>{payload}</pre>
</body>
</html>"""


def serve_fleet_dashboard(
    cfg: IdeaForgeConfig,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
) -> None:
    """Run a read-only HTTP dashboard until interrupted."""

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.path not in ("/", "/index.html", "/fleet.json"):
                self.send_error(404)
                return
            snapshot = collect_fleet_snapshot(cfg)
            if self.path == "/fleet.json":
                body = json.dumps(snapshot, indent=2, ensure_ascii=False).encode("utf-8")
                content_type = "application/json; charset=utf-8"
            else:
                body = render_fleet_html(snapshot).encode("utf-8")
                content_type = "text/html; charset=utf-8"
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:
            return

    server = ThreadingHTTPServer((host, port), _Handler)
    print(f"Fleet dashboard at http://{host}:{port}/  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nFleet dashboard stopped")
    finally:
        server.server_close()