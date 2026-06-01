"""Command-line entry point for the prebuilt-artifact builder.

Subcommands:
  check    Resolve the upstream version and decide whether a build is needed
           (release = skip if the tag already exists; nightly = always build).
           Writes key=value lines to $GITHUB_OUTPUT for the workflow.
  build    Build + package + checksum + manifest + smoke-test one recipe for one
           arch/channel. The smoke test is the publish gate: a failure exits
           non-zero so the workflow never publishes. Also writes a result JSON.
  report   Aggregate result JSONs into a Markdown summary ($GITHUB_STEP_SUMMARY)
           and the tracking-issue body; emits notify=true|false to decide
           whether the workflow should comment (which notifies watchers).
  list     List available recipes.
"""
from __future__ import annotations

import argparse
import os
import platform
import sys
import time
from pathlib import Path

from builder.core import pack, recipe, report
from builder.core.recipe import NIGHTLY, RELEASE
from builder.core.smoke import SmokeTestError


def _gh_output(**kv: str) -> None:
    """Append key=value pairs to $GITHUB_OUTPUT (and echo for local runs)."""
    out = os.environ.get("GITHUB_OUTPUT")
    lines = [f"{k}={v}" for k, v in kv.items()]
    for ln in lines:
        print(ln)
    if out:
        with open(out, "a") as f:
            f.write("\n".join(lines) + "\n")


def _first_line(text: str, limit: int = 120) -> str:
    """First non-empty-safe line of ``text``, truncated — for result notes."""
    return (text.splitlines() or [""])[0][:limit]


# Map the various spellings `uname -m` / platform.machine() may report onto our
# short canonical arch names.
_MACHINE_TO_ARCH = {
    "x86_64": "amd", "amd64": "amd",
    "aarch64": "arm", "arm64": "arm",
}


def _detect_arch() -> str:
    machine = platform.machine().lower()
    try:
        return _MACHINE_TO_ARCH[machine]
    except KeyError:
        raise SystemExit(f"unsupported architecture: {machine}")


def _release_tag(r: recipe.Recipe, version: str, channel: str, arch: str, os_tag: str) -> str:
    """The git tag / GitHub Release tag for this artifact set.

    Release: ``<tool>-<version>-<os>-<arch>`` (permanent).
    Nightly: ``<tool>-nightly-<os>-<arch>`` (rolling, overwritten on success).
    """
    v = "nightly" if channel == NIGHTLY else version
    return f"{r.name}-{v}-{os_tag}-{arch}"


def cmd_list(_: argparse.Namespace) -> int:
    for name in recipe.available():
        print(name)
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    r = recipe.get(args.recipe)
    version = r.latest_version(args.channel)
    tag = _release_tag(r, version, args.channel, args.arch, args.os)

    from builder.core import versions
    if args.channel == NIGHTLY:
        needs_build = True            # nightly always rebuilds (rolling)
    else:
        needs_build = not versions.tag_exists(tag)

    _gh_output(
        version=version,
        tag=tag,
        needs_build=str(needs_build).lower(),
    )
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    r = recipe.get(args.recipe)
    arch = args.arch
    version = args.version or r.latest_version(args.channel)
    workdir = Path(args.workdir).resolve()
    out_dir = Path(args.out).resolve()
    ccache_dir = Path(args.ccache_dir).resolve() if args.ccache_dir else workdir / ".ccache"
    workdir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    ccache_dir.mkdir(parents=True, exist_ok=True)
    results_dir = Path(args.results_dir).resolve() if args.results_dir else None

    ctx = recipe.BuildContext(
        version=version, channel=args.channel, arch=arch,
        workdir=workdir, ccache_dir=ccache_dir, os_tag=args.os,
    )

    def record(status: str, *, size: int = 0, duration: float = 0.0, note: str = "") -> None:
        if results_dir:
            report.write_result(results_dir, report.Result(
                tool=r.name, channel=args.channel, arch=arch, os=args.os, status=status,
                version=version, duration_seconds=duration, size_bytes=size, note=note,
            ))

    start = time.time()
    try:
        install_prefix = r.build(ctx)
        artifacts = r.package(ctx, install_prefix, out_dir)
        if not artifacts:
            raise RuntimeError("recipe produced no artifacts")

        # Smoke test is the publish gate.
        r.smoke_test(ctx, install_prefix)

        # Checksums + per-artifact manifest entries.
        total = 0
        art_meta = []
        for art in artifacts:
            digest = pack.write_sha256(art.path)   # also reused below, no re-hash
            size = art.path.stat().st_size
            total += size
            # Record the runtime (shared-library) footprint of each executable
            # member, so the glibc baseline of the shipped binaries is auditable.
            ldd = {}
            for rel in art.contents:
                member = install_prefix / rel
                if member.is_file() and os.access(member, os.X_OK):
                    deps = pack.ldd_deps(member)
                    if deps:
                        ldd[rel] = deps
            art_meta.append({
                "name": art.path.name,
                "kind": art.kind,
                "size_bytes": size,
                "sha256": digest,
                "contents": art.contents,
                "ldd": ldd,
            })

        pack.write_manifest(
            out_dir / "MANIFEST.json",
            tool=r.name, version=version, channel=args.channel, arch=arch, os_tag=args.os,
            source_ref=version, build_flags=getattr(r, "build_flags", ""),
            artifacts=art_meta, duration_seconds=time.time() - start,
        )
    except SmokeTestError as e:
        record("failed", duration=time.time() - start, note=_first_line(f"smoke: {e}"))
        print(f"SMOKE TEST FAILED: {e}", file=sys.stderr)
        return 2
    except Exception as e:  # noqa: BLE001 - record then re-raise as failure
        record("failed", duration=time.time() - start, note=_first_line(str(e)))
        print(f"BUILD FAILED: {e}", file=sys.stderr)
        return 1

    duration = time.time() - start
    record("built", size=total, duration=duration)
    tag = _release_tag(r, version, args.channel, arch, args.os)
    _gh_output(version=version, tag=tag, out_dir=str(out_dir))
    print(f"OK: {len(artifacts)} artifact(s), {total} bytes, tag={tag}, {duration:.0f}s")
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    results = report.load_results(Path(args.results_dir))
    md = report.render_markdown(results)

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as f:
            f.write(md)
    else:
        print(md)

    if args.issue_body_file:
        Path(args.issue_body_file).write_text(report.render_issue_body(results))

    # notify=true tells the workflow to add an Issue comment (which emails
    # watchers) — only when something actually built or failed, never on a
    # day where every job was skipped.
    _gh_output(notify=str(report.should_notify(results)).lower())

    # Non-zero if anything failed, so the report job itself goes red. The
    # body/notify outputs above are emitted first so the publish step (run with
    # if: always()) still updates the issue.
    return 1 if report.any_failed(results) else 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m builder")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add_common(sp: argparse.ArgumentParser, *, need_arch: bool = True) -> None:
        sp.add_argument("--recipe", required=True, choices=None,
                        help="recipe name (see `list`)")
        sp.add_argument("--channel", default=RELEASE, choices=recipe.CHANNELS)
        sp.add_argument("--os", required=True,
                        help="build platform label for asset names/tags, e.g. ubuntu-22.04 "
                             "(required, so artifacts are never mislabeled)")
        if need_arch:
            sp.add_argument("--arch", default=None, choices=list(recipe.ARCHES),
                            help="target arch; auto-detected from uname if omitted")

    sp = sub.add_parser("list"); sp.set_defaults(func=cmd_list)

    sp = sub.add_parser("check"); add_common(sp); sp.set_defaults(func=cmd_check)

    sp = sub.add_parser("build"); add_common(sp)
    sp.add_argument("--version", default=None, help="override resolved version")
    sp.add_argument("--workdir", default="work")
    sp.add_argument("--out", default="dist")
    sp.add_argument("--ccache-dir", default=None)
    sp.add_argument("--results-dir", default=None, help="dir to write result JSON")
    sp.set_defaults(func=cmd_build)

    sp = sub.add_parser("report")
    sp.add_argument("--results-dir", required=True)
    sp.add_argument("--issue-body-file", default=None,
                    help="write the tracking-issue body (markdown) here")
    sp.set_defaults(func=cmd_report)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    # Resolve arch default lazily so `list`/`report` don't require it.
    if getattr(args, "arch", "missing") is None:
        args.arch = _detect_arch()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
