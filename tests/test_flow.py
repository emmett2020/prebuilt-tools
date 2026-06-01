"""End-to-end flow of `cmd_build`, driven through the CLI with a mock recipe.

A fake recipe stands in for a real tool (no compilation), so this exercises the
orchestration that ties everything together: build -> package -> smoke gate ->
checksums -> manifest -> result JSON -> $GITHUB_OUTPUT, plus the failure paths.
"""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from builder import __main__ as cli
from builder.core.smoke import SmokeTestError
from tests._fakes import FakeRecipe, ensure_registered

ensure_registered()


class FlowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.out = self.tmp / "dist"
        self.results = self.tmp / "results"
        self.gh_output = self.tmp / "gh_output"
        self.gh_output.write_text("")

    def _run_build(self):
        argv = [
            "build", "--recipe", "mock-tool", "--channel", "release",
            "--os", "ubuntu-22.04", "--arch", "amd", "--version", "1.2.3",
            "--workdir", str(self.tmp / "work"), "--out", str(self.out),
            "--results-dir", str(self.results),
        ]
        with mock.patch.dict(os.environ, {"GITHUB_OUTPUT": str(self.gh_output)}):
            return cli.main(argv)

    def _only_result(self):
        from builder.core import report
        [r] = report.load_results(self.results)
        return r

    # -- happy path --------------------------------------------------------

    def test_happy_path_full_flow(self):
        rc = self._run_build()
        self.assertEqual(rc, 0)

        # tarball + its checksum sidecar exist
        tarball = self.out / "mock-tool-1.2.3-ubuntu-22.04-amd.tar.gz"
        self.assertTrue(tarball.exists())
        self.assertTrue(tarball.with_name(tarball.name + ".sha256").exists())

        # manifest written, carries os + the per-artifact ldd field
        manifest = json.loads((self.out / "MANIFEST.json").read_text())
        self.assertEqual(manifest["os"], "ubuntu-22.04")
        self.assertEqual(manifest["build_flags"], "mock-flags")
        self.assertEqual(len(manifest["artifacts"]), 1)
        self.assertIn("ldd", manifest["artifacts"][0])
        self.assertIn("sha256", manifest["artifacts"][0])

        # result recorded as built, and tag emitted to $GITHUB_OUTPUT
        self.assertEqual(self._only_result().status, "built")
        self.assertIn("tag=mock-tool-1.2.3-ubuntu-22.04-amd",
                      self.gh_output.read_text())

    # -- failure paths (publish gate) -------------------------------------

    def test_smoke_failure_blocks_manifest_and_returns_2(self):
        with mock.patch.object(FakeRecipe, "smoke_test",
                               side_effect=SmokeTestError("clangd missing")):
            rc = self._run_build()
        self.assertEqual(rc, 2)
        # Smoke is the gate: it runs before checksums/manifest, so neither exists.
        self.assertFalse((self.out / "MANIFEST.json").exists())
        r = self._only_result()
        self.assertEqual(r.status, "failed")
        self.assertIn("smoke", r.note)

    def test_build_exception_returns_1_and_records_failure(self):
        with mock.patch.object(FakeRecipe, "build",
                               side_effect=RuntimeError("compiler exploded")):
            rc = self._run_build()
        self.assertEqual(rc, 1)
        self.assertEqual(self._only_result().status, "failed")

    def test_empty_artifacts_is_a_failure(self):
        with mock.patch.object(FakeRecipe, "package", return_value=[]):
            rc = self._run_build()
        self.assertEqual(rc, 1)
        self.assertEqual(self._only_result().status, "failed")

    def test_empty_exception_message_does_not_crash_handler(self):
        # Guards the _first_line() fix: an empty-message exception must still be
        # recorded, not raise IndexError inside the except block.
        with mock.patch.object(FakeRecipe, "build", side_effect=RuntimeError()):
            rc = self._run_build()
        self.assertEqual(rc, 1)
        self.assertEqual(self._only_result().status, "failed")


if __name__ == "__main__":
    unittest.main()
