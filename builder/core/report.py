"""Build-status aggregation and reporting.

Each matrix job writes a small JSON *result* file (see ``write_result``). The
summary job collects all of them from a directory and renders both a Markdown
table for ``$GITHUB_STEP_SUMMARY`` and a plain-text body for the daily email.
"""
from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import List


@dataclass
class Result:
    tool: str
    channel: str
    arch: str
    status: str                     # "built" | "skipped" | "failed"
    os: str = "linux"
    version: str = ""
    duration_seconds: float = 0.0
    size_bytes: int = 0
    note: str = ""


def write_result(out_dir: Path, result: Result) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    name = f"{result.tool}-{result.channel}-{result.os}-{result.arch}.json"
    path = out_dir / name
    path.write_text(json.dumps(asdict(result), indent=2) + "\n")
    return path


def load_results(in_dir: Path) -> List[Result]:
    results: List[Result] = []
    for path in sorted(in_dir.rglob("*.json")):
        try:
            results.append(Result(**json.loads(path.read_text())))
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
    return results


def _human_size(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f}{unit}" if unit == "B" else f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}GB"


def _human_duration(seconds: float) -> str:
    if seconds <= 0:
        return "-"
    total = int(round(seconds))
    if total < 60:
        return f"{total}s"
    minutes, secs = divmod(total, 60)
    if minutes < 60:
        return f"{minutes}m {secs}s" if secs else f"{minutes}m"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m" if minutes else f"{hours}h"


def _project_compile_times(results: List[Result]) -> dict[str, float]:
    totals: dict[str, float] = defaultdict(float)
    for r in results:
        if r.status in ("built", "failed") and r.duration_seconds > 0:
            totals[r.tool] += r.duration_seconds
    return dict(sorted(totals.items()))


_ICON = {"built": "✅", "skipped": "⏭️", "failed": "❌"}


def render_markdown(results: List[Result]) -> str:
    lines = [
        "# Build Report",
        "",
        "## Project Compile Time",
        "",
        "| Tool | Actual Compile Time |",
        "|------|---------------------|",
    ]
    totals = _project_compile_times(results)
    if totals:
        for tool, seconds in totals.items():
            lines.append(f"| {tool} | {_human_duration(seconds)} |")
    else:
        lines.append("| - | - |")

    lines.extend([
        "",
        "## Matrix Results",
        "",
        "| Tool | Channel | OS | Arch | Status | Version | Time | Size | Note |",
        "|------|---------|----|------|--------|---------|------|------|------|",
    ])
    for r in results:
        dur = _human_duration(r.duration_seconds)
        size = _human_size(r.size_bytes) if r.size_bytes else "-"
        lines.append(
            f"| {r.tool} | {r.channel} | {r.os} | {r.arch} | {_ICON.get(r.status, r.status)} "
            f"{r.status} | {r.version or '-'} | {dur} | {size} | {r.note or ''} |"
        )
    return "\n".join(lines) + "\n"


def any_failed(results: List[Result]) -> bool:
    return any(r.status == "failed" for r in results)


def should_notify(results: List[Result]) -> bool:
    """Whether the run warrants an Issue comment (which emails watchers).

    True only when something actually built or failed — a day where every job
    was skipped (nothing new upstream) stays silent to avoid daily noise.
    """
    return any(r.status in ("built", "failed") for r in results)


def render_issue_body(results: List[Result]) -> str:
    """Markdown body for the tracking issue: the table + an updated-at stamp."""
    from datetime import datetime, timezone
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return f"{render_markdown(results)}\n_Updated {stamp}_\n"
