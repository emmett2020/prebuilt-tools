"""Report aggregation: result round-trip, failure detection, rendering."""
import tempfile
import unittest
from pathlib import Path

from builder.core import report
from builder.core.report import Result


class ReportTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def test_result_roundtrip_preserves_os(self):
        report.write_result(self.dir, Result(
            tool="llvm", channel="release", arch="arm", status="built",
            os="ubuntu-24.04", version="19.1.0", size_bytes=42))
        [loaded] = report.load_results(self.dir)
        self.assertEqual(loaded.os, "ubuntu-24.04")
        self.assertEqual(loaded.arch, "arm")
        self.assertEqual(loaded.size_bytes, 42)

    def test_distinct_os_results_do_not_collide(self):
        # Same tool/channel/arch on two OSes must produce two files, not one.
        for os_tag in ("ubuntu-22.04", "ubuntu-24.04"):
            report.write_result(self.dir, Result(
                tool="llvm", channel="release", arch="amd", status="built",
                os=os_tag, version="19.1.0"))
        self.assertEqual(len(report.load_results(self.dir)), 2)

    def test_any_failed(self):
        rs = [Result("llvm", "release", "amd", "built"),
              Result("llvm", "release", "arm", "failed", note="boom")]
        self.assertTrue(report.any_failed(rs))
        self.assertFalse(report.any_failed([Result("t", "release", "amd", "built")]))

    def test_should_notify_only_on_built_or_failed(self):
        # something built -> notify
        self.assertTrue(report.should_notify([Result("t", "release", "amd", "built")]))
        # a failure -> notify
        self.assertTrue(report.should_notify([Result("t", "release", "amd", "failed")]))
        # all skipped -> stay silent
        self.assertFalse(report.should_notify([
            Result("t", "release", "amd", "skipped"),
            Result("t", "release", "arm", "skipped"),
        ]))
        self.assertFalse(report.should_notify([]))

    def test_issue_body_has_table_and_timestamp(self):
        body = report.render_issue_body([Result("llvm", "nightly", "amd", "built",
                                                 os="ubuntu-22.04", version="x")])
        self.assertIn("| Tool |", body)
        self.assertIn("_Updated", body)
        self.assertIn("UTC", body)

    def test_markdown_has_os_column_and_rows(self):
        rs = [Result("llvm", "nightly", "amd", "built", os="ubuntu-22.04",
                     version="x", size_bytes=1024)]
        md = report.render_markdown(rs)
        self.assertIn("| OS |", md)
        self.assertIn("ubuntu-22.04", md)

    def test_corrupt_result_file_is_skipped(self):
        (self.dir / "bad.json").write_text("{ not json")
        report.write_result(self.dir, Result("t", "release", "amd", "built"))
        self.assertEqual(len(report.load_results(self.dir)), 1)


if __name__ == "__main__":
    unittest.main()
