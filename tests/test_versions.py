"""Version discovery — offline only (uses a local git repo, no network).

Network-backed helpers (latest_release_tag) are intentionally not unit-tested
here; these cover the git-based logic that gates idempotency and nightly stamps.
"""
import os
import re
import subprocess
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

from builder.core import versions


def _git(repo: Path, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True,
                   capture_output=True, text=True)


@contextmanager
def _chdir(path: Path):
    prev = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(prev)


class VersionsTest(unittest.TestCase):
    def setUp(self):
        self.repo = Path(tempfile.mkdtemp())
        _git(self.repo, "init", "-q")
        _git(self.repo, "config", "user.email", "t@t")
        _git(self.repo, "config", "user.name", "t")
        (self.repo / "f").write_text("x")
        _git(self.repo, "add", "f")
        _git(self.repo, "commit", "-qm", "init")

    def test_tag_exists_true_and_false(self):
        _git(self.repo, "tag", "llvm-19.1.0-ubuntu-22.04-amd64")
        with _chdir(self.repo):
            self.assertTrue(versions.tag_exists("llvm-19.1.0-ubuntu-22.04-amd64"))
            self.assertFalse(versions.tag_exists("llvm-99.9.9-ubuntu-22.04-amd64"))

    def test_default_branch_head_is_12_hex(self):
        sha = versions.default_branch_head(str(self.repo))
        self.assertRegex(sha, r"^[0-9a-f]{12}$")

    def test_nightly_stamp_shape(self):
        stamp = versions.nightly_stamp(str(self.repo))
        self.assertRegex(stamp, r"^nightly-\d{8}-[0-9a-f]{12}$")


if __name__ == "__main__":
    unittest.main()
