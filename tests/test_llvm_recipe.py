"""LLVM packaging split — guards the two-package layout and smoke coverage.

Uses a fabricated install tree (fake executables that print on --version), so
it runs anywhere without compiling LLVM.
"""
import stat
import tempfile
import unittest
from pathlib import Path

from builder.core.recipe import RELEASE, BuildContext
from builder.core.smoke import SmokeTestError
from builder.recipes.llvm import LLVMRecipe

ALL_BINS = [
    "clangd", "clang-format", "clang-tidy", "clang-apply-replacements",
    "clang", "clang++", "clang-19", "ld.lld",
]


def _fake_install(tmp: Path, *, clangd_says="clangd version 19.1.0", lld_ok=True):
    prefix = tmp / "install"
    (prefix / "bin").mkdir(parents=True)
    (prefix / "lib" / "clang" / "19" / "include").mkdir(parents=True)

    def mk(name, body):
        f = prefix / "bin" / name
        f.write_text(body)
        f.chmod(f.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    mk("clangd", f"#!/bin/sh\necho '{clangd_says}'\n")
    for b in ALL_BINS[1:]:
        mk(b, f"#!/bin/sh\necho '{b} version 19.1.0'\n")
    # bare lld: real driver errors on --version without a flavor
    mk("lld", "#!/bin/sh\necho 'use ld.lld' >&2\n" + ("exit 0\n" if lld_ok else "exit 1\n"))
    return prefix


def _ctx(tmp: Path):
    return BuildContext(version="19.1.0", channel=RELEASE, arch="amd",
                        workdir=tmp, ccache_dir=tmp / "cc", os_tag="ubuntu-22.04")


class LLVMPackageTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.prefix = _fake_install(self.tmp)
        self.out = self.tmp / "dist"; self.out.mkdir()
        self.arts = LLVMRecipe().package(_ctx(self.tmp), self.prefix, self.out)

    def _by_kind(self):
        return {a.kind: set(a.contents) for a in self.arts}

    def test_two_packages_produced(self):
        self.assertEqual({a.kind for a in self.arts}, {"clang-tools", "compiler"})

    def test_clang_tools_bundles_the_dev_tools(self):
        contents = self._by_kind()["clang-tools"]
        for b in ["clangd", "clang-format", "clang-tidy", "clang-apply-replacements"]:
            self.assertIn(f"bin/{b}", contents)

    def test_compiler_excludes_dev_tools(self):
        contents = self._by_kind()["compiler"]
        for b in ["clangd", "clang-format", "clang-tidy", "clang-apply-replacements"]:
            self.assertNotIn(f"bin/{b}", contents)
        # but does carry the compiler + linker
        for b in ["clang", "clang++", "lld", "ld.lld"]:
            self.assertIn(f"bin/{b}", contents)

    def test_both_packages_ship_resource_dir(self):
        for contents in self._by_kind().values():
            self.assertIn("lib/clang/19", contents)

    def test_tarballs_named_by_kind(self):
        names = {a.path.name for a in self.arts}
        self.assertIn("llvm-clang-tools-19.1.0-ubuntu-22.04-amd.tar.gz", names)
        self.assertIn("llvm-compiler-19.1.0-ubuntu-22.04-amd.tar.gz", names)


class LLVMSmokeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_smoke_passes_and_skips_bare_lld(self):
        prefix = _fake_install(self.tmp, lld_ok=False)  # bare lld errors; must be skipped
        LLVMRecipe().smoke_test(_ctx(self.tmp), prefix)  # should not raise

    def test_smoke_fails_when_clangd_misidentifies(self):
        prefix = _fake_install(self.tmp, clangd_says="not the right tool")
        with self.assertRaises(SmokeTestError):
            LLVMRecipe().smoke_test(_ctx(self.tmp), prefix)

    def test_smoke_fails_when_clangd_missing(self):
        prefix = _fake_install(self.tmp)
        (prefix / "bin" / "clangd").unlink()
        with self.assertRaises(SmokeTestError):
            LLVMRecipe().smoke_test(_ctx(self.tmp), prefix)


if __name__ == "__main__":
    unittest.main()
