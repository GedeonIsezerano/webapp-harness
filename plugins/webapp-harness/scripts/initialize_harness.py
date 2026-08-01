"""Compatibility entry point for GitHub-backed harness initialization."""

from __future__ import annotations

import sys

from github_harness import main

if __name__ == "__main__":
    raise SystemExit(main(["initialize", *sys.argv[1:]]))
