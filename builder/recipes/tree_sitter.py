"""tree-sitter recipe — builds the C runtime library (static + headers).

tree-sitter's C library is small and fast to compile, which makes it the ideal
recipe for validating the whole pipeline end-to-end. We build the static
``libtree-sitter.a`` plus headers via the upstream Makefile's ``install``
target — a near zero runtime-dependency artifact.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import List

from builder.core import versions
from builder.core.recipe import NIGHTLY, RELEASE, Artifact, BuildContext, Recipe, register
from builder.core.smoke import must_exist

REPO = "https://github.com/tree-sitter/tree-sitter.git"
OWNER_REPO = "tree-sitter/tree-sitter"


class TreeSitterRecipe(Recipe):
    name = "tree-sitter"
    build_flags = "make install (static libtree-sitter.a + headers)"

    def latest_version(self, channel: str) -> str:
        if channel == NIGHTLY:
            return versions.nightly_stamp(REPO)
        return versions.latest_release_tag(OWNER_REPO).removeprefix("v")

    def build(self, ctx: BuildContext) -> Path:
        src = ctx.workdir / "tree-sitter"
        install_prefix = ctx.workdir / "install"

        clone = ["git", "clone", "--depth=1", REPO, str(src)]
        if ctx.channel == RELEASE:
            clone[2:2] = ["--branch", f"v{ctx.version}"]
        if not src.exists():
            subprocess.run(clone, check=True)

        jobs = str(os.cpu_count() or 4)
        subprocess.run(["make", f"-j{jobs}"], cwd=src, check=True)
        subprocess.run(["make", "install", f"PREFIX={install_prefix}"],
                       cwd=src, check=True)
        return install_prefix

    def package(self, ctx: BuildContext, install_prefix: Path, out_dir: Path) -> List[Artifact]:
        from builder.core import pack

        members: List[str] = []
        # Static archive lives under lib/ or lib64/ depending on the platform.
        for libdir in ("lib", "lib64"):
            archive = install_prefix / libdir / "libtree-sitter.a"
            if archive.exists():
                members.append(f"{libdir}/libtree-sitter.a")
        inc = install_prefix / "include" / "tree_sitter"
        if inc.exists():
            members += [str(p.relative_to(install_prefix)) for p in inc.glob("*.h")]

        tarball = out_dir / f"{self.asset_basename(ctx, '')}.tar.gz"
        added = pack.make_tarball(tarball, install_prefix, sorted(set(members)))
        return [Artifact(path=tarball, kind="lib", contents=added)]

    def smoke_test(self, ctx: BuildContext, install_prefix: Path) -> None:
        must_exist(install_prefix / "include" / "tree_sitter" / "api.h")
        archive = next(
            (install_prefix / d / "libtree-sitter.a" for d in ("lib", "lib64")
             if (install_prefix / d / "libtree-sitter.a").exists()),
            None,
        )
        if archive is None:
            from builder.core.smoke import SmokeTestError
            raise SmokeTestError("libtree-sitter.a not found in lib/ or lib64/")


register(TreeSitterRecipe())
