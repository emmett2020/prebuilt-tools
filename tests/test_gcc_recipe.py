"""GCC recipe: version discovery, packaging, and smoke-test behavior."""
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from builder.__main__ import _release_tag
from builder.core.recipe import NIGHTLY, RELEASE, BuildContext
from builder.recipes.gcc import GCCRecipe


def _ctx(version="16.1.0", channel=RELEASE, arch="amd", os_tag="ubuntu-22.04"):
    tmp = Path(tempfile.mkdtemp())
    return BuildContext(
        version=version, channel=channel, arch=arch,
        workdir=tmp, ccache_dir=tmp / ".ccache", os_tag=os_tag,
    )


def _mk(path: Path, text: str, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(mode)


class GCCVersionTest(unittest.TestCase):
    def setUp(self):
        self.r = GCCRecipe()

    def test_release_version_uses_gnu_index(self):
        with mock.patch(
            "builder.core.versions.latest_version_from_index", return_value="16.1.0"
        ) as latest:
            self.assertEqual(self.r.latest_version(RELEASE), "16.1.0")
        latest.assert_called_once()

    def test_nightly_tracks_latest_release_branch(self):
        with mock.patch(
            "builder.core.versions.latest_version_from_index", return_value="16.1.0"
        ), mock.patch(
            "builder.core.versions.remote_ref_head", return_value="abcdef123456"
        ) as head:
            stamp = self.r.latest_version(NIGHTLY)

        self.assertRegex(stamp, r"^nightly-\d{8}-gcc16-abcdef123456$")
        head.assert_called_once_with(
            "https://gcc.gnu.org/git/gcc.git", "refs/heads/releases/gcc-16"
        )

    def test_nightly_branch_can_be_derived_from_stamp(self):
        self.assertEqual(
            self.r._nightly_branch("nightly-20260603-gcc16-abcdef123456"),
            "releases/gcc-16",
        )

    def test_nightly_asset_and_tag_are_rolling(self):
        ctx = _ctx("nightly-20260603-gcc16-abcdef123456", NIGHTLY, arch="arm")
        self.assertEqual(
            self.r.asset_basename(ctx, ""),
            "gcc-nightly-ubuntu-22.04-arm",
        )
        self.assertEqual(
            _release_tag(self.r, ctx.version, ctx.channel, ctx.arch, ctx.os_tag),
            "gcc-nightly-ubuntu-22.04-arm",
        )


class GCCPackageTest(unittest.TestCase):
    def setUp(self):
        self.r = GCCRecipe()
        self.ctx = _ctx()
        self.prefix = self.ctx.workdir / "install"
        self.out = self.ctx.workdir / "dist"
        _mk(self.prefix / "bin" / "gcc", "gcc")
        _mk(self.prefix / "bin" / "g++", "g++")
        _mk(self.prefix / "lib" / "gcc" / "specs", "specs")
        _mk(self.prefix / "lib64" / "libstdc++.so", "lib")
        _mk(self.prefix / "libexec" / "gcc" / "cc1plus", "cc1")
        _mk(self.prefix / "include" / "c++" / "vector", "vector")
        _mk(self.prefix / "share" / "man" / "man1" / "gcc.1", "manual")

    def test_package_contains_compiler_dirs_without_docs(self):
        artifacts = self.r.package(self.ctx, self.prefix, self.out)

        self.assertEqual(len(artifacts), 1)
        self.assertEqual(artifacts[0].kind, "compiler")
        self.assertEqual(
            artifacts[0].path.name, "gcc-16.1.0-ubuntu-22.04-amd.tar.gz"
        )

        with tarfile.open(artifacts[0].path, "r:gz") as tar:
            names = set(tar.getnames())
        self.assertIn("bin/gcc", names)
        self.assertIn("bin/g++", names)
        self.assertIn("lib64/libstdc++.so", names)
        self.assertIn("libexec/gcc/cc1plus", names)
        self.assertIn("include/c++/vector", names)
        self.assertNotIn("share/man/man1/gcc.1", names)
        self.assertIn("bin/gcc", artifacts[0].contents)
        self.assertIn("bin/g++", artifacts[0].contents)
        self.assertIn("libexec/gcc/cc1plus", artifacts[0].contents)
        self.assertNotIn("bin", artifacts[0].contents)


class GCCSmokeTest(unittest.TestCase):
    def setUp(self):
        self.r = GCCRecipe()
        self.ctx = _ctx()
        self.prefix = self.ctx.workdir / "install"

    def _fake_compiler(self, name: str, version_line: str, run_text: str) -> None:
        script = """#!/bin/sh
if [ "$1" = "--version" ]; then
  echo "%s"
  exit 0
fi
out=""
while [ "$#" -gt 0 ]; do
  if [ "$1" = "-o" ]; then
    shift
    out="$1"
  fi
  shift
done
if [ -z "$out" ]; then
  echo "missing -o" >&2
  exit 1
fi
{
  echo '#!/bin/sh'
  echo 'echo %s'
} > "$out"
chmod +x "$out"
""" % (version_line, run_text)
        _mk(self.prefix / "bin" / name, script, 0o755)

    def test_smoke_compiles_and_runs_c_and_cxx_samples(self):
        self._fake_compiler("gcc", "gcc (GCC) 16.1.0", "c-ok")
        self._fake_compiler("g++", "g++ (GCC) 16.1.0", "cxx-ok")

        self.r.smoke_test(self.ctx, self.prefix)

        self.assertTrue((self.ctx.workdir / "smoke-gcc" / "hello-c").exists())
        self.assertTrue((self.ctx.workdir / "smoke-gcc" / "hello-cxx").exists())


if __name__ == "__main__":
    unittest.main()
