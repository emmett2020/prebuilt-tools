"""LLVM recipe — builds the clang dev tools and a compiler/linker package.

Migrated from the original ``build_clangd.sh`` and extended:
  * static libstdc++ link to minimize runtime deps (glibc baseline = ubuntu-22.04),
  * ccache for cross-run incremental builds (the real lever against the 6h limit),
  * one build → two split tarballs: ``clang-tools`` (clangd + clang-format /
    clang-tidy / clang-apply-replacements) and ``compiler`` (clang / clang++ /
    lld — no overlap with clang-tools).
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import List

from builder.core import versions
from builder.core.recipe import NIGHTLY, RELEASE, Artifact, BuildContext, Recipe, register
from builder.core.smoke import must_exist, run_ok

REPO = "https://github.com/llvm/llvm-project.git"
OWNER_REPO = "llvm/llvm-project"

CMAKE_FLAGS = [
    "-G", "Ninja",
    "-DCMAKE_BUILD_TYPE=Release",
    '-DLLVM_ENABLE_PROJECTS=clang;clang-tools-extra;lld',
    "-DLLVM_STATIC_LINK_CXX_STDLIB=ON",
    "-DLLVM_ENABLE_ASSERTIONS=OFF",
    "-DLLVM_TARGETS_TO_BUILD=Native",
    "-DCMAKE_C_COMPILER_LAUNCHER=ccache",
    "-DCMAKE_CXX_COMPILER_LAUNCHER=ccache",
]


class LLVMRecipe(Recipe):
    name = "llvm"
    build_flags = " ".join(CMAKE_FLAGS)

    def latest_version(self, channel: str) -> str:
        if channel == NIGHTLY:
            return versions.nightly_stamp(REPO)
        tag = versions.latest_release_tag(OWNER_REPO)   # e.g. "llvmorg-19.1.0"
        return tag.removeprefix("llvmorg-")

    def build(self, ctx: BuildContext) -> Path:
        src = ctx.workdir / "llvm-project"
        install_prefix = ctx.workdir / "install"
        build_dir = src / "build"

        clone = ["git", "clone", "--depth=1", REPO, str(src)]
        if ctx.channel == RELEASE:
            clone[2:2] = ["--branch", f"llvmorg-{ctx.version}"]
        if not src.exists():
            subprocess.run(clone, check=True)

        env = os.environ.copy()
        env["CCACHE_DIR"] = str(ctx.ccache_dir)
        env.setdefault("CCACHE_MAXSIZE", "8G")

        build_dir.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["cmake", str(src / "llvm"), *CMAKE_FLAGS,
             f"-DCMAKE_INSTALL_PREFIX={install_prefix}"],
            cwd=build_dir, check=True, env=env,
        )
        subprocess.run(["ninja", f"-j{os.cpu_count() or 4}", "install"],
                       cwd=build_dir, check=True, env=env)
        return install_prefix

    def package(self, ctx: BuildContext, install_prefix: Path, out_dir: Path) -> List[Artifact]:
        from builder.core import pack

        major = ctx.version.split(".")[0] if ctx.channel == RELEASE else ""
        bins = lambda *names: [f"bin/{n}" for n in names if (install_prefix / "bin" / n).exists()]

        # lib/clang/<ver>/include ships the builtin headers clangd/clang need.
        clang_lib = [str(p.relative_to(install_prefix))
                     for p in (install_prefix / "lib" / "clang").glob("*")] \
            if (install_prefix / "lib" / "clang").exists() else []

        specs = {
            # clangd + the standalone source tools, all in one package.
            "clang-tools": bins(
                "clangd", "clang-format", "clang-tidy", "clang-apply-replacements",
            ) + clang_lib,
            # Compiler + linker only — no clangd / clang-format / clang-tidy /
            # clang-apply-replacements (those live in clang-tools above).
            "compiler": bins(
                "clang", "clang++", "lld", "ld.lld",
                *([f"clang-{major}"] if major else []),
            ) + clang_lib,
        }

        artifacts: List[Artifact] = []
        for kind, members in specs.items():
            members = sorted(set(members))
            if not members:
                continue
            tarball = out_dir / f"{self.asset_basename(ctx, kind)}.tar.gz"
            added = pack.make_tarball(tarball, install_prefix, members)
            artifacts.append(Artifact(path=tarball, kind=kind, contents=added))
        return artifacts

    def smoke_test(self, ctx: BuildContext, install_prefix: Path) -> None:
        from builder.core.smoke import SmokeTestError

        # clangd is the keystone artifact — require it and check it identifies
        # itself, as a strong anchor.
        clangd = install_prefix / "bin" / "clangd"
        must_exist(clangd)
        run_ok([str(clangd), "--version"], expect_substr="clangd")

        # --version every packaged binary. Note: bare `lld` is a multi-call
        # driver that errors on `--version` without a flavor, so the linker is
        # validated via its `ld.lld` alias (same binary) instead.
        major = ctx.version.split(".")[0] if ctx.channel == RELEASE else ""
        candidates = [
            "clang", "clang++", "clang-format", "clang-tidy",
            "clang-apply-replacements", "ld.lld",
        ]
        if major:
            candidates.append(f"clang-{major}")

        checked = ["clangd"]
        for name in candidates:
            binary = install_prefix / "bin" / name
            if binary.exists():
                run_ok([str(binary), "--version"])
                checked.append(name)

        if len(checked) < 2:
            raise SmokeTestError(f"only clangd was found to smoke-test: {checked}")


register(LLVMRecipe())
