"""Shared test doubles."""
import stat
from pathlib import Path

from builder.core import pack, recipe
from builder.core.recipe import Artifact, BuildContext, Recipe, register
from builder.core.smoke import run_ok


class FakeRecipe(Recipe):
    """Minimal recipe: writes one fake executable and packages it (no compile)."""
    name = "mock-tool"
    build_flags = "mock-flags"

    def latest_version(self, channel):
        return "1.2.3"

    def build(self, ctx: BuildContext) -> Path:
        prefix = ctx.workdir / "install"
        (prefix / "bin").mkdir(parents=True, exist_ok=True)
        f = prefix / "bin" / "mocktool"
        f.write_text("#!/bin/sh\necho 'mocktool 1.2.3'\n")
        f.chmod(f.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        return prefix

    def package(self, ctx, install_prefix, out_dir):
        tb = out_dir / f"{self.asset_basename(ctx, '')}.tar.gz"
        added = pack.make_tarball(tb, install_prefix, ["bin/mocktool"])
        return [Artifact(path=tb, kind="mock-tool", contents=added)]

    def smoke_test(self, ctx, install_prefix):
        run_ok([str(install_prefix / "bin" / "mocktool"), "--version"])


def ensure_registered() -> FakeRecipe:
    """Register FakeRecipe once (idempotent across test-module imports)."""
    if FakeRecipe.name not in recipe._REGISTRY:
        register(FakeRecipe())
    return recipe._REGISTRY[FakeRecipe.name]
