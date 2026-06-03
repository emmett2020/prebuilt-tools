"""GCC recipe - builds a native C/C++ compiler package.

Release builds use GCC source tarballs. Nightly builds follow the newest GCC
release branch (for example ``releases/gcc-16``) rather than trunk, so the
rolling artifact tracks stable-branch fixes without taking mainline churn.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import urllib.request
from pathlib import Path
from typing import List

from builder.core import versions
from builder.core.recipe import NIGHTLY, RELEASE, Artifact, BuildContext, Recipe, register
from builder.core.smoke import SmokeTestError, must_exist, run_ok

REPO = "https://gcc.gnu.org/git/gcc.git"
RELEASE_INDEX = "https://gcc.gnu.org/ftp/gcc/releases/"

CONFIGURE_FLAGS = [
    "--enable-languages=c,c++",
    "--disable-bootstrap",
    "--disable-multilib",
    "--disable-nls",
    "--enable-checking=release",
    "--with-system-zlib",
]

PACKAGE_DIRS = ("bin", "lib", "lib64", "libexec", "include")


def _download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".tmp")
    req = urllib.request.Request(url, headers={"User-Agent": "prebuilt-tools-builder"})
    with urllib.request.urlopen(req, timeout=60) as resp, open(tmp, "wb") as f:
        shutil.copyfileobj(resp, f)
    tmp.replace(dest)


def _package_contents(root: Path, members: List[str]) -> List[str]:
    contents: List[str] = []
    for rel in members:
        path = root / rel
        if path.is_file():
            contents.append(rel)
            continue
        for child in sorted(path.rglob("*")):
            if child.is_file():
                contents.append(str(child.relative_to(root)))
    return contents


class GCCRecipe(Recipe):
    name = "gcc"
    build_flags = " ".join(CONFIGURE_FLAGS)

    def _latest_release_version(self) -> str:
        return versions.latest_version_from_index(
            RELEASE_INDEX, r"gcc-(\d+\.\d+\.\d+)/"
        )

    def _nightly_branch(self, version: str | None = None) -> str:
        match = re.search(r"(?:^|-)gcc(\d+)-", version or "")
        major = match.group(1) if match else self._latest_release_version().split(".")[0]
        return f"releases/gcc-{major}"

    def latest_version(self, channel: str) -> str:
        if channel == NIGHTLY:
            release = self._latest_release_version()
            major = release.split(".")[0]
            branch = f"releases/gcc-{major}"
            return versions.nightly_stamp(
                REPO, f"refs/heads/{branch}", label=f"gcc{major}"
            )
        return self._latest_release_version()

    def _require_tools(self, ctx: BuildContext) -> None:
        tools = ["gcc", "g++", "make", "tar", "xz", "bzip2", "wget", "ccache"]
        if ctx.channel == NIGHTLY:
            tools.extend(["git", "flex", "bison", "makeinfo"])
        missing = [tool for tool in tools if not shutil.which(tool)]
        if missing:
            raise SmokeTestError(
                "missing GCC build dependencies on PATH: " + ", ".join(missing)
            )

    def _release_source(self, ctx: BuildContext) -> Path:
        src = ctx.workdir / f"gcc-{ctx.version}"
        archive = ctx.workdir / f"gcc-{ctx.version}.tar.xz"
        if src.exists():
            return src

        if not archive.exists():
            url = f"{RELEASE_INDEX}gcc-{ctx.version}/gcc-{ctx.version}.tar.xz"
            _download(url, archive)

        subprocess.run(["tar", "-xf", str(archive), "-C", str(ctx.workdir)], check=True)
        if not src.exists():
            raise SmokeTestError(f"GCC archive did not extract to {src}")
        return src

    def _nightly_source(self, ctx: BuildContext) -> Path:
        src = ctx.workdir / "gcc"
        branch = self._nightly_branch(ctx.version)
        if not src.exists():
            subprocess.run(
                [
                    "git", "clone", "--depth=1", "--single-branch",
                    "--branch", branch, REPO, str(src),
                ],
                check=True,
            )

        update = src / "contrib" / "gcc_update"
        if update.exists():
            subprocess.run([str(update), "--touch"], cwd=src, check=True)
        return src

    def _prepare_source(self, ctx: BuildContext) -> Path:
        src = self._release_source(ctx) if ctx.channel == RELEASE else self._nightly_source(ctx)
        prereq = src / "contrib" / "download_prerequisites"
        if prereq.exists():
            subprocess.run([str(prereq)], cwd=src, check=True)
        return src

    def build(self, ctx: BuildContext) -> Path:
        self._require_tools(ctx)

        src = self._prepare_source(ctx)
        build_dir = ctx.workdir / "gcc-build"
        install_prefix = ctx.workdir / "install"
        build_dir.mkdir(parents=True, exist_ok=True)

        env = os.environ.copy()
        env["CCACHE_DIR"] = str(ctx.ccache_dir)
        env.setdefault("CCACHE_MAXSIZE", "8G")
        env.setdefault("CC", "ccache gcc")
        env.setdefault("CXX", "ccache g++")

        subprocess.run(
            [str(src / "configure"), f"--prefix={install_prefix}", *CONFIGURE_FLAGS],
            cwd=build_dir, check=True, env=env,
        )
        subprocess.run(["make", f"-j{os.cpu_count() or 4}"],
                       cwd=build_dir, check=True, env=env)
        subprocess.run(["make", "install-strip"], cwd=build_dir, check=True, env=env)
        return install_prefix

    def package(self, ctx: BuildContext, install_prefix: Path, out_dir: Path) -> List[Artifact]:
        from builder.core import pack

        members = [name for name in PACKAGE_DIRS if (install_prefix / name).exists()]
        if not members:
            raise SmokeTestError(f"GCC install prefix has no packageable dirs: {install_prefix}")

        tarball = out_dir / f"{self.asset_basename(ctx, '')}.tar.gz"
        pack.make_tarball(tarball, install_prefix, members)
        return [
            Artifact(
                path=tarball,
                kind="compiler",
                contents=_package_contents(install_prefix, members),
            )
        ]

    def smoke_test(self, ctx: BuildContext, install_prefix: Path) -> None:
        gcc = install_prefix / "bin" / "gcc"
        gxx = install_prefix / "bin" / "g++"
        must_exist(gcc)
        must_exist(gxx)
        run_ok([str(gcc), "--version"], expect_substr="gcc")
        run_ok([str(gxx), "--version"], expect_substr="g++")

        smoke_dir = ctx.workdir / "smoke-gcc"
        smoke_dir.mkdir(parents=True, exist_ok=True)

        c_src = smoke_dir / "hello.c"
        c_bin = smoke_dir / "hello-c"
        c_src.write_text('#include <stdio.h>\nint main(void){puts("c-ok");return 0;}\n')

        cxx_src = smoke_dir / "hello.cc"
        cxx_bin = smoke_dir / "hello-cxx"
        cxx_src.write_text(
            '#include <iostream>\nint main(){std::cout<<"cxx-ok\\n";return 0;}\n'
        )

        env = os.environ.copy()
        lib_paths = [
            str(path) for path in (install_prefix / "lib64", install_prefix / "lib")
            if path.exists()
        ]
        if lib_paths:
            existing = env.get("LD_LIBRARY_PATH")
            env["LD_LIBRARY_PATH"] = os.pathsep.join(
                lib_paths + ([existing] if existing else [])
            )

        run_ok([str(gcc), str(c_src), "-o", str(c_bin)], cwd=smoke_dir, env=env)
        run_ok([str(c_bin)], expect_substr="c-ok", cwd=smoke_dir, env=env)
        run_ok([str(gxx), str(cxx_src), "-o", str(cxx_bin)], cwd=smoke_dir, env=env)
        run_ok([str(cxx_bin)], expect_substr="cxx-ok", cwd=smoke_dir, env=env)


register(GCCRecipe())
