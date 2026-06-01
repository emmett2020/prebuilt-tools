# llvm-prebuilt-binary

Prebuilt binaries for slow-to-compile tools (LLVM/clangd, tree-sitter, …),
rebuilt daily by GitHub Actions and published to GitHub Releases. Downstream
repositories download the artifacts directly instead of recompiling.

A small, dependency-free Python driver (`builder/`) does the work; adding a new
tool is just adding one recipe file.

## Downloading artifacts

Asset names and Release tags follow a fixed convention, so downstream consumers
can construct URLs by string formatting — **no GitHub API calls needed**:

```
<tool>[-<kind>]-<version>-<os>-<arch>.tar.gz
```

- `os` ∈ `ubuntu-22.04` (glibc 2.35), `ubuntu-24.04` (glibc 2.39)
- `arch` ∈ `amd64`, `arm64`
- **release** channel: `version` is the upstream version, tag is permanent
- **nightly** channel: `version` is the literal `nightly`, the tag rolls
  (overwritten only after a successful build + smoke test, so a failed build
  never replaces the last good artifact)

```bash
OWNER=emmett2020/llvm-prebuilt-binary

# Latest stable clangd for x86_64, built on the broad-compat ubuntu-22.04 baseline
VER=19.1.0
A=llvm-clangd-$VER-ubuntu-22.04-amd64
curl -fsSL -o clangd.tar.gz \
  "https://github.com/$OWNER/releases/download/$A/$A.tar.gz"

# Verify checksum (each asset ships a .sha256 sidecar)
curl -fsSL -o clangd.tar.gz.sha256 \
  "https://github.com/$OWNER/releases/download/$A/$A.tar.gz.sha256"
sha256sum -c clangd.tar.gz.sha256

# Rolling nightly tree-sitter on arm64 (URL never changes)
N=tree-sitter-nightly-ubuntu-22.04-arm64
curl -fsSL "https://github.com/$OWNER/releases/download/$N/$N.tar.gz" | tar xz
```

Each Release also includes a `MANIFEST.json` recording the source ref, compiler,
build flags, per-artifact sha256, and build duration for provenance.

**Compatibility — pick the `os` to match your runtime's glibc:**

| Build OS | glibc | Runs on (examples) |
|----------|-------|--------------------|
| `ubuntu-22.04` | ≥ 2.35 | Ubuntu 22.04+, Debian 12+ — **most portable, prefer this** |
| `ubuntu-24.04` | ≥ 2.39 | Ubuntu 24.04+ only — use if you need 24.04's newer toolchain |

Binaries built on a given OS require that OS's glibc **or newer**. C++ tools
also link libstdc++ statically to reduce runtime dependencies. Built for Linux
`amd64` / `arm64` only (no macOS/Windows yet).

### Available tools / artifact kinds

| Tool | Kinds (split tarballs) |
|------|------------------------|
| `llvm` | `clangd`, `clang-tools` (clang-format/clang-tidy), `full-toolchain` |
| `tree-sitter` | static `libtree-sitter.a` + headers |

## How it works

```
builder/
  __main__.py        # CLI: list / check / build / report
  core/              # recipe base+registry, version discovery, packaging, smoke, reporting
  recipes/           # one module per tool (llvm.py, tree_sitter.py)
.github/workflows/
  build.yml          # daily (staggered: release 01:00 UTC, nightly 13:00 UTC) + PR dry-run
  manual_build.yml   # workflow_dispatch: build one tool/arch, optionally publish
```

- **Idempotency:** for `release`, a build is skipped if its tag already exists.
  `nightly` always rebuilds and rolls its tag.
- **The 6h job limit** is handled by persisting `ccache` across runs
  (`actions/cache`) so repeated/resumed runs of the same version are fast —
  staggered cron only spreads load, it does not extend a single job.
- **Publish gate:** the smoke test must pass before anything is released.

### CLI

```bash
python -m builder list
python -m builder check  --recipe tree-sitter --channel release --arch amd64
python -m builder build  --recipe tree-sitter --channel nightly --arch amd64 \
                         --workdir work --out dist --results-dir results
python -m builder report --results-dir results
```

## Adding a new tool

Create `builder/recipes/<tool>.py` implementing `Recipe`
(`latest_version`, `build`, `package`, `smoke_test`) and call
`register(<Recipe>())` at module import. Add a matrix entry in
`.github/workflows/build.yml`. Validate with `manual_build.yml` before merging.

## Repository configuration

Daily email notifications are sent only if these are set:

| Kind | Name | Purpose |
|------|------|---------|
| Variable | `NOTIFY_EMAIL` | recipient address (configurable; not hard-coded) |
| Secret | `SMTP_HOST` / `SMTP_PORT` | SMTP server |
| Secret | `SMTP_USERNAME` / `SMTP_PASSWORD` | SMTP credentials |

If `NOTIFY_EMAIL` is unset, the build report is still written to the Actions
job summary, and GitHub's native scheduled-failure email serves as a fallback.
