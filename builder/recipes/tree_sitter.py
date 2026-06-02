"""tree-sitter recipe — builds the ``tree-sitter`` CLI binary.

The CLI (the command used to generate/test grammars) is a Rust crate, built with
``cargo build --release``. The recipe ships the single self-contained
``tree-sitter`` executable. Requires a Rust toolchain (``cargo``) on PATH —
present on GitHub-hosted ubuntu runners.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import List

from builder.core import versions
from builder.core.recipe import NIGHTLY, RELEASE, Artifact, BuildContext, Recipe, register
from builder.core.smoke import SmokeTestError, must_exist, run_ok

REPO = "https://github.com/tree-sitter/tree-sitter.git"
OWNER_REPO = "tree-sitter/tree-sitter"


class TreeSitterRecipe(Recipe):
    name = "tree-sitter"
    build_flags = "cargo build --release --bin tree-sitter"

    def latest_version(self, channel: str) -> str:
        if channel == NIGHTLY:
            return versions.nightly_stamp(REPO)
        return versions.latest_release_tag(OWNER_REPO).removeprefix("v")

    def build(self, ctx: BuildContext) -> Path:
        if not shutil.which("cargo"):
            raise SmokeTestError(
                "cargo (Rust toolchain) not found on PATH — required to build the "
                "tree-sitter CLI. Install Rust (rustup) or use a runner that ships it."
            )

        src = ctx.workdir / "tree-sitter"
        install_prefix = ctx.workdir / "install"

        clone = ["git", "clone", "--depth=1", REPO, str(src)]
        if ctx.channel == RELEASE:
            clone[2:2] = ["--branch", f"v{ctx.version}"]
        if not src.exists():
            subprocess.run(clone, check=True)

        subprocess.run(["cargo", "build", "--release", "--bin", "tree-sitter"],
                       cwd=src, check=True)

        binary = src / "target" / "release" / "tree-sitter"
        if not binary.exists():
            raise SmokeTestError(f"cargo did not produce {binary}")

        dest = install_prefix / "bin" / "tree-sitter"
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(binary, dest)
        # Strip to shrink the binary (best effort — missing strip is non-fatal).
        subprocess.run(["strip", str(dest)], check=False)
        return install_prefix

    def package(self, ctx: BuildContext, install_prefix: Path, out_dir: Path) -> List[Artifact]:
        from builder.core import pack

        tarball = out_dir / f"{self.asset_basename(ctx, '')}.tar.gz"
        added = pack.make_tarball(tarball, install_prefix, ["bin/tree-sitter"])
        return [Artifact(path=tarball, kind="cli", contents=added)]

    def smoke_test(self, ctx: BuildContext, install_prefix: Path) -> None:
        binary = install_prefix / "bin" / "tree-sitter"
        must_exist(binary)
        run_ok([str(binary), "--version"], expect_substr="tree-sitter")


register(TreeSitterRecipe())
