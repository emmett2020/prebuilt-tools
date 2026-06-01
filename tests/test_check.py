"""`cmd_check` flow: version resolution + idempotency, driven through the CLI.

This is what the workflow's "Resolve version & idempotency" step runs; it decides
whether each matrix job builds at all, so its release/nightly asymmetry matters.
"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from builder import __main__ as cli
from tests._fakes import ensure_registered

ensure_registered()


def _outputs(text: str) -> dict:
    return dict(line.split("=", 1) for line in text.splitlines() if "=" in line)


class CheckFlowTest(unittest.TestCase):
    def setUp(self):
        self.gh = Path(tempfile.mkdtemp()) / "out"
        self.gh.write_text("")

    def _check(self, channel):
        argv = ["check", "--recipe", "mock-tool", "--channel", channel,
                "--os", "ubuntu-22.04", "--arch", "amd"]
        with mock.patch.dict(os.environ, {"GITHUB_OUTPUT": str(self.gh)}):
            rc = cli.main(argv)
        return rc, _outputs(self.gh.read_text())

    def test_release_skips_when_tag_exists(self):
        with mock.patch("builder.core.versions.tag_exists", return_value=True):
            rc, out = self._check("release")
        self.assertEqual(rc, 0)
        self.assertEqual(out["needs_build"], "false")
        self.assertEqual(out["version"], "1.2.3")
        self.assertEqual(out["tag"], "mock-tool-1.2.3-ubuntu-22.04-amd")

    def test_release_builds_when_tag_absent(self):
        with mock.patch("builder.core.versions.tag_exists", return_value=False):
            _, out = self._check("release")
        self.assertEqual(out["needs_build"], "true")

    def test_nightly_always_builds_even_if_tag_exists(self):
        # nightly is a rolling tag: tag_exists must be ignored entirely.
        with mock.patch("builder.core.versions.tag_exists", return_value=True) as te:
            _, out = self._check("nightly")
        self.assertEqual(out["needs_build"], "true")
        self.assertEqual(out["tag"], "mock-tool-nightly-ubuntu-22.04-amd")
        te.assert_not_called()


if __name__ == "__main__":
    unittest.main()
