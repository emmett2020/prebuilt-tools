"""Smoke-test helpers used as the publish gate.

A recipe's ``smoke_test`` raises ``SmokeTestError`` on failure; the CLI turns
that into a non-zero exit so the workflow never reaches the publish step.
"""
from __future__ import annotations

import subprocess
from pathlib import Path


class SmokeTestError(RuntimeError):
    pass


def run_ok(
    cmd: list[str],
    *,
    expect_substr: str | None = None,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> str:
    """Run ``cmd``; raise SmokeTestError unless it exits 0 (and optionally
    contains ``expect_substr`` in its combined output)."""
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, env=env)
    output = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode != 0:
        raise SmokeTestError(
            f"command failed ({proc.returncode}): {' '.join(cmd)}\n{output}"
        )
    if expect_substr is not None and expect_substr not in output:
        raise SmokeTestError(
            f"expected {expect_substr!r} in output of {' '.join(cmd)}\n{output}"
        )
    return output


def must_exist(path: Path) -> None:
    if not path.exists():
        raise SmokeTestError(f"expected file missing: {path}")
