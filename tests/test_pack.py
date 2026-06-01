"""Packaging: tarball creation/guards, checksums, manifest."""
import hashlib
import json
import tarfile
import tempfile
import unittest
from pathlib import Path

from builder.core import pack


class PackTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        (self.root / "bin").mkdir()
        (self.root / "bin" / "tool").write_text("binary")
        (self.root / "readme").write_text("hi")

    def test_make_tarball_contains_members_and_is_gzip(self):
        out = self.root / "out.tar.gz"
        added = pack.make_tarball(out, self.root, ["bin/tool", "readme"])
        self.assertEqual(added, ["bin/tool", "readme"])
        with tarfile.open(out, "r:gz") as t:   # raises if not gzip
            self.assertEqual(sorted(t.getnames()), ["bin/tool", "readme"])

    def test_make_tarball_missing_member_raises(self):
        out = self.root / "out.tar.gz"
        with self.assertRaises(FileNotFoundError):
            pack.make_tarball(out, self.root, ["bin/tool", "does-not-exist"])

    def test_sha256_matches_hashlib(self):
        f = self.root / "readme"
        self.assertEqual(pack.sha256_file(f),
                         hashlib.sha256(f.read_bytes()).hexdigest())

    def test_write_sha256_returns_digest_and_writes_sidecar(self):
        f = self.root / "readme"
        digest = pack.write_sha256(f)
        self.assertEqual(digest, pack.sha256_file(f))
        sidecar = f.with_name("readme.sha256")
        self.assertTrue(sidecar.exists())
        # `sha256sum -c` format: "<digest>  <filename>"
        self.assertEqual(sidecar.read_text().strip(), f"{digest}  readme")

    def test_write_manifest_records_os_tag(self):
        out = self.root / "MANIFEST.json"
        pack.write_manifest(
            out, tool="llvm", version="19.1.0", channel="release", arch="amd",
            os_tag="ubuntu-24.04", source_ref="19.1.0", build_flags="-O3",
            artifacts=[{"name": "a.tar.gz"}], duration_seconds=1.23)
        data = json.loads(out.read_text())
        self.assertEqual(data["os"], "ubuntu-24.04")
        self.assertEqual(data["arch"], "amd")
        self.assertEqual(data["artifacts"][0]["name"], "a.tar.gz")


if __name__ == "__main__":
    unittest.main()
