"""Asset-name / release-tag conventions — the contract downstream URLs rely on.

These guard the class of bug where the published asset filename and its git
release tag silently drift apart, or where the nightly rolling name stops being
stable.
"""
import unittest
from pathlib import Path

from builder.__main__ import _release_tag
from builder.core.recipe import NIGHTLY, RELEASE, BuildContext
from builder.recipes.llvm import LLVMRecipe


def _ctx(version, channel, arch="amd", os_tag="ubuntu-22.04"):
    return BuildContext(version=version, channel=channel, arch=arch,
                        workdir=Path("/tmp"), ccache_dir=Path("/tmp"), os_tag=os_tag)


class AssetNamingTest(unittest.TestCase):
    def setUp(self):
        self.r = LLVMRecipe()  # name == "llvm"

    def test_release_basename_shape(self):
        ctx = _ctx("19.1.0", RELEASE)
        self.assertEqual(
            self.r.asset_basename(ctx, "clang-tools"),
            "llvm-clang-tools-19.1.0-ubuntu-22.04-amd",
        )

    def test_empty_kind_omits_kind_segment(self):
        ctx = _ctx("19.1.0", RELEASE)
        self.assertEqual(
            self.r.asset_basename(ctx, ""),
            "llvm-19.1.0-ubuntu-22.04-amd",
        )

    def test_kind_equal_to_tool_is_not_doubled(self):
        ctx = _ctx("19.1.0", RELEASE)
        # kind == tool name should not produce "llvm-llvm-..."
        self.assertEqual(self.r.asset_basename(ctx, "llvm"),
                         self.r.asset_basename(ctx, ""))

    def test_nightly_uses_literal_token_not_version(self):
        # The rolling URL must never change with the daily commit stamp.
        ctx = _ctx("nightly-20260601-deadbeef", NIGHTLY, arch="arm")
        self.assertEqual(
            self.r.asset_basename(ctx, "compiler"),
            "llvm-compiler-nightly-ubuntu-22.04-arm",
        )

    def test_tag_matches_basename_for_same_inputs(self):
        # _release_tag (used for the git/Release tag) must equal the base of the
        # asset filename, or the published file won't live under its tag.
        for channel, version in [(RELEASE, "19.1.0"), (NIGHTLY, "nightly-x")]:
            ctx = _ctx(version, channel)
            tag = _release_tag(self.r, version, channel, ctx.arch, ctx.os_tag)
            self.assertEqual(tag, self.r.asset_basename(ctx, ""))


if __name__ == "__main__":
    unittest.main()
