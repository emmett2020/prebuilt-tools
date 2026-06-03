"""Upstream version discovery and release-tag idempotency.

Migrated and de-duplicated from the original ``build_clangd.yml`` inline shell
(which queried the GitHub API with curl/grep and checked ``git rev-parse`` for
an existing tag — and contained the arm/amd tag-suffix bug this replaces).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import urllib.request
from datetime import datetime, timezone


def _gh_json(url: str) -> dict:
    headers = {
        "User-Agent": "prebuilt-tools-builder",
        "Accept": "application/vnd.github+json",
    }
    # Authenticate when a token is available (CI) to dodge the 60 req/hr
    # unauthenticated rate limit.
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def _url_text(url: str) -> str:
    headers = {"User-Agent": "prebuilt-tools-builder"}
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        return resp.read().decode(charset, errors="replace")


def _dotted_version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def latest_version_from_index(index_url: str, pattern: str) -> str:
    """Return the highest dotted version captured from a simple HTML index.

    ``pattern`` must contain one capture group for a version such as
    ``16.1.0``. This is intentionally small and dependency-free for GNU-style
    directory listings where release metadata is exposed as linked filenames.
    """
    rx = re.compile(pattern)
    versions = {m.group(1) for m in rx.finditer(_url_text(index_url))}
    if not versions:
        raise RuntimeError(f"no versions matched {pattern!r} in {index_url}")
    return max(versions, key=_dotted_version_key)


def latest_release_tag(owner_repo: str) -> str:
    """Return the latest *release* tag of a GitHub repo, e.g. ``llvmorg-19.1.0``."""
    data = _gh_json(f"https://api.github.com/repos/{owner_repo}/releases/latest")
    return data["tag_name"]


def remote_ref_head(repo_url: str, ref: str = "HEAD") -> str:
    """Return the short commit SHA of a remote ref via ``git ls-remote``."""
    out = subprocess.run(
        ["git", "ls-remote", repo_url, ref],
        check=True, capture_output=True, text=True,
    ).stdout.split()
    if not out:
        raise RuntimeError(f"git ls-remote returned nothing for {repo_url} {ref}")
    return out[0][:12]


def default_branch_head(repo_url: str) -> str:
    """Return the short commit SHA of the default branch HEAD via ``git ls-remote``."""
    return remote_ref_head(repo_url, "HEAD")


def nightly_stamp(repo_url: str, ref: str = "HEAD", label: str | None = None) -> str:
    """A nightly version stamp: ``nightly-<UTCdate>-<shortsha>``."""
    date = datetime.now(timezone.utc).strftime("%Y%m%d")
    pieces = ["nightly", date]
    if label:
        pieces.append(label)
    pieces.append(remote_ref_head(repo_url, ref))
    return "-".join(pieces)


def tag_exists(tag: str) -> bool:
    """True if ``tag`` already exists in the current git repo (release idempotency).

    Requires the checkout to have fetched tags (``fetch-depth: 0`` in CI).
    """
    return subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", f"refs/tags/{tag}"],
        capture_output=True,
    ).returncode == 0
