"""Recipe abstraction and registry.

A *recipe* encapsulates everything specific to one tool: how to discover its
latest upstream version, how to build it for a given architecture, what to
package, and how to smoke-test the result. Adding a new prebuilt tool means
adding one recipe module under ``builder/recipes/`` — the CLI and workflows
stay untouched.
"""
from __future__ import annotations

import abc
import importlib
import pkgutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

# Channels.
RELEASE = "release"
NIGHTLY = "nightly"
CHANNELS = (RELEASE, NIGHTLY)

# Architectures. Keys are the canonical names used in asset filenames; the
# value is the matching ``uname -m`` output so a runner can self-identify.
ARCHES = {"amd64": "x86_64", "arm64": "aarch64"}


@dataclass
class BuildContext:
    """Inputs handed to a recipe for a single build."""

    version: str            # resolved upstream version, e.g. "19.1.0" or "nightly-20260601-abcd123"
    channel: str            # RELEASE or NIGHTLY
    arch: str               # "amd64" or "arm64"
    workdir: Path           # scratch directory the recipe may use freely
    ccache_dir: Path        # persistent ccache directory (may be empty on first run)


@dataclass
class Artifact:
    """One packaged tarball plus the relative paths it contains."""

    path: Path                       # the produced .tar.gz on disk
    kind: str                        # short label, e.g. "clangd" / "full-toolchain"
    contents: List[str] = field(default_factory=list)  # member paths, for the manifest


class Recipe(abc.ABC):
    """Base class every tool recipe must implement."""

    #: Stable short name used on the CLI and in asset filenames (e.g. "llvm").
    name: str = ""

    @abc.abstractmethod
    def latest_version(self, channel: str) -> str:
        """Return the upstream version to build for ``channel``.

        For RELEASE this is the latest stable tag (normalized, no ``v`` / prefix).
        For NIGHTLY this is a date+commit stamp identifying upstream HEAD.
        """

    @abc.abstractmethod
    def build(self, ctx: BuildContext) -> Path:
        """Build the tool and return the install prefix directory."""

    @abc.abstractmethod
    def package(self, ctx: BuildContext, install_prefix: Path, out_dir: Path) -> List[Artifact]:
        """Package one or more tarballs from ``install_prefix`` into ``out_dir``."""

    @abc.abstractmethod
    def smoke_test(self, ctx: BuildContext, install_prefix: Path) -> None:
        """Sanity-check the build. Raise on failure to block publishing."""

    # -- helpers shared by subclasses ------------------------------------

    def asset_basename(self, ctx: BuildContext, kind: str) -> str:
        """Canonical, API-free asset name: ``<tool>[-<kind>]-<version>-linux-<arch>``.

        For nightly the version component is the literal string ``nightly`` so
        the rolling tag/URL never changes.
        """
        version = "nightly" if ctx.channel == NIGHTLY else ctx.version
        tool = self.name if not kind or kind == self.name else f"{self.name}-{kind}"
        return f"{tool}-{version}-linux-{ctx.arch}"


# --------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------

_REGISTRY: Dict[str, Recipe] = {}


def register(recipe: Recipe) -> Recipe:
    """Register a recipe instance. Called at import time by each recipe module."""
    if not recipe.name:
        raise ValueError(f"{recipe!r} has no name")
    if recipe.name in _REGISTRY:
        raise ValueError(f"duplicate recipe name: {recipe.name}")
    _REGISTRY[recipe.name] = recipe
    return recipe


def _load_all() -> None:
    """Import every module under builder.recipes so they self-register."""
    from builder import recipes  # local import to avoid cycles

    for mod in pkgutil.iter_modules(recipes.__path__):
        importlib.import_module(f"{recipes.__name__}.{mod.name}")


def get(name: str) -> Recipe:
    _load_all()
    try:
        return _REGISTRY[name]
    except KeyError:
        raise SystemExit(f"unknown recipe: {name!r} (known: {', '.join(available())})")


def available() -> List[str]:
    _load_all()
    return sorted(_REGISTRY)
