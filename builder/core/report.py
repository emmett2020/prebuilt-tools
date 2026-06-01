"""Build-status aggregation and reporting.

Each matrix job writes a small JSON *result* file (see ``write_result``). The
summary job collects all of them from a directory and renders both a Markdown
table for ``$GITHUB_STEP_SUMMARY`` and a plain-text body for the daily email.
"""
from __future__ import annotations

import json
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


_ICON = {"built": "✅", "skipped": "⏭️", "failed": "❌"}


def render_markdown(results: List[Result]) -> str:
    lines = [
        "# Build Report",
        "",
        "| Tool | Channel | OS | Arch | Status | Version | Time | Size | Note |",
        "|------|---------|----|------|--------|---------|------|------|------|",
    ]
    for r in results:
        dur = f"{r.duration_seconds/60:.0f}m" if r.duration_seconds else "-"
        size = _human_size(r.size_bytes) if r.size_bytes else "-"
        lines.append(
            f"| {r.tool} | {r.channel} | {r.os} | {r.arch} | {_ICON.get(r.status, r.status)} "
            f"{r.status} | {r.version or '-'} | {dur} | {size} | {r.note or ''} |"
        )
    return "\n".join(lines) + "\n"


def render_text(results: List[Result]) -> str:
    lines = ["Build Report", "=" * 40]
    for r in results:
        lines.append(
            f"[{r.status.upper():7}] {r.tool}/{r.channel}/{r.os}/{r.arch} "
            f"{r.version}".rstrip()
            + (f" — {r.note}" if r.note else "")
        )
    n_fail = sum(1 for r in results if r.status == "failed")
    lines += ["", f"{len(results)} jobs, {n_fail} failed."]
    return "\n".join(lines) + "\n"


def any_failed(results: List[Result]) -> bool:
    return any(r.status == "failed" for r in results)


def email_subject(results: List[Result]) -> str:
    n_fail = sum(1 for r in results if r.status == "failed")
    state = "FAILED" if n_fail else "OK"
    return f"[prebuilt] daily build {state} — {len(results)} jobs, {n_fail} failed"
