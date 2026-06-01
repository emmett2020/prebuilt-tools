"""Prebuilt artifact build & publish platform.

A recipe-driven builder for producing prebuilt binaries of slow-to-compile
tools (llvm, tree-sitter, ...) and publishing them to GitHub Releases so that
downstream repositories can download them directly instead of recompiling.

Standard library only — no third-party Python dependencies.
"""
