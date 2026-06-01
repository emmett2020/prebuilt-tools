"""Upstream version discovery and release-tag idempotency.

Migrated and de-duplicated from the original ``build_clangd.yml`` inline shell
(which queried the GitHub API with curl/grep and checked ``git rev-parse`` for
an existing tag — and contained the arm/amd tag-suffix bug this replaces).
"""
from __future__ import annotations

import json
import os
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


def latest_release_tag(owner_repo: str) -> str:
    """Return the latest *release* tag of a GitHub repo, e.g. ``llvmorg-19.1.0``."""
    data = _gh_json(f"https://api.github.com/repos/{owner_repo}/releases/latest")
    return data["tag_name"]


def default_branch_head(repo_url: str) -> str:
    """Return the short commit SHA of the default branch HEAD via ``git ls-remote``."""
    out = subprocess.run(
        ["git", "ls-remote", repo_url, "HEAD"],
        check=True, capture_output=True, text=True,
    ).stdout.split()
    if not out:
        raise RuntimeError(f"git ls-remote returned nothing for {repo_url}")
    return out[0][:12]


def nightly_stamp(repo_url: str) -> str:
    """A nightly version stamp: ``nightly-<UTCdate>-<shortsha>``."""
    date = datetime.now(timezone.utc).strftime("%Y%m%d")
    return f"nightly-{date}-{default_branch_head(repo_url)}"


def tag_exists(tag: str) -> bool:
    """True if ``tag`` already exists in the current git repo (release idempotency).

    Requires the checkout to have fetched tags (``fetch-depth: 0`` in CI).
    """
    return subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", f"refs/tags/{tag}"],
        capture_output=True,
    ).returncode == 0
