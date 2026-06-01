"""Packaging helpers: tarballs, checksums, ldd inspection, and manifests."""
from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List


def make_tarball(out_path: Path, root: Path, members: Iterable[str]) -> List[str]:
    """Create a gzip-compressed tarball at ``out_path``.

    ``members`` are paths relative to ``root``. Returns the list of member paths
    actually added (for the manifest). Raises if a member is missing — we never
    want to publish a half-empty archive.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    added: List[str] = []
    with tarfile.open(out_path, "w:gz") as tar:
        for rel in members:
            src = root / rel
            if not src.exists():
                raise FileNotFoundError(f"packaging member not found: {src}")
            tar.add(src, arcname=rel)
            added.append(rel)
    return added


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_sha256(path: Path) -> Path:
    """Write ``<path>.sha256`` next to the artifact in ``sha256sum`` format."""
    digest = sha256_file(path)
    sidecar = path.with_name(path.name + ".sha256")
    sidecar.write_text(f"{digest}  {path.name}\n")
    return sidecar


def ldd_deps(binary: Path) -> List[str]:
    """Return the shared-library dependency lines from ``ldd`` (best effort).

    Used to record, and later eyeball, the glibc/runtime footprint of a binary.
    Non-ELF files or a missing ``ldd`` simply yield an empty/short list.
    """
    try:
        out = subprocess.run(
            ["ldd", str(binary)], capture_output=True, text=True
        )
    except FileNotFoundError:
        return []
    if out.returncode != 0:
        return []
    return [ln.strip() for ln in out.stdout.splitlines() if ln.strip()]


def cc_version() -> str:
    for cc in ("cc", "clang", "gcc"):
        try:
            out = subprocess.run([cc, "--version"], capture_output=True, text=True)
            if out.returncode == 0:
                return out.stdout.splitlines()[0].strip()
        except FileNotFoundError:
            continue
    return "unknown"


def write_manifest(
    out_path: Path,
    *,
    tool: str,
    version: str,
    channel: str,
    arch: str,
    source_ref: str,
    build_flags: str,
    artifacts: List[dict],
    duration_seconds: float,
) -> Path:
    """Write a MANIFEST.json describing the build for provenance/reproducibility."""
    manifest = {
        "tool": tool,
        "version": version,
        "channel": channel,
        "arch": arch,
        "os": "linux",
        "source_ref": source_ref,
        "build_flags": build_flags,
        "compiler": cc_version(),
        "builder_host": platform.platform(),
        "built_at": datetime.now(timezone.utc).isoformat(),
        "duration_seconds": round(duration_seconds, 1),
        "artifacts": artifacts,
    }
    out_path.write_text(json.dumps(manifest, indent=2) + "\n")
    return out_path
