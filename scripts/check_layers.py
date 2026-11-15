#!/usr/bin/env python3
"""Verify the seven-layer architecture is actually enforced, not just drawn.

The reorganization moved 103 top-level modules into layer packages. Folders
alone prove nothing: what matters is that a lower layer never imports a
higher one. This script checks that mechanically over the whole package and
exits non-zero on violation, so CI can keep it true.

Layer order (index = depth; a module may import its own layer or any LOWER
layer, never a higher one):

    core(0) < security(1) < observability(2) < services(3) < providers(4)
    < orchestration(5) < server(6)

`eval` and `extras` are side branches at depth 3.5: they may import lower
layers, and nothing below them may import them.

Rationale for the specific violations this catches: during the migration two
upward edges survived (services importing provider data classes) because the
move-time guard only inspected modules being moved. This checker inspects
the END state, which is what actually matters.

Usage:
    python scripts/check_layers.py [--package webscout_mcp] [--quiet]

Exit codes: 0 clean, 1 violations found.
"""

from __future__ import annotations

import argparse
import os
import re
import sys

RANK = {
    "core": 0,
    "security": 1,
    "observability": 2,
    "services": 3,
    "providers": 4,
    "orchestration": 5,
    "server": 6,
}
SIDE_BRANCH = {"eval", "extras"}


def collect(pkg: str) -> dict[tuple[str, str], set[tuple[str, str]]]:
    """Map (layer, module) -> set of (layer, module) it imports."""
    modules: dict[tuple[str, str], set[tuple[str, str]]] = {}
    for root, dirs, files in os.walk(pkg):
        dirs[:] = [d for d in dirs if not d.startswith("__")]
        rel = os.path.relpath(root, pkg)
        layer = rel if rel != "." else "ROOT"
        for f in files:
            if not f.endswith(".py") or f == "__init__.py":
                continue
            name = f[:-3]
            src = open(os.path.join(root, f), encoding="utf-8", errors="replace").read()
            deps: set[tuple[str, str]] = set()
            for m in re.finditer(r"^from \.\.(\w+)\.(\w+) import", src, re.MULTILINE):
                deps.add((m.group(1), m.group(2)))
            for m in re.finditer(r"^from \.\.(\w+) import", src, re.MULTILINE):
                deps.add((m.group(1), ""))
            modules[(layer, name)] = deps
    return modules


def check(pkg: str) -> tuple[list[str], list[str], int]:
    modules = collect(pkg)
    upward: list[str] = []
    leaks: list[str] = []
    for (layer, name), deps in modules.items():
        if layer not in RANK:
            continue
        my = RANK[layer]
        for dl, dm in deps:
            if dl in RANK and RANK[dl] > my:
                upward.append(f"{layer}/{name} -> {dl}/{dm} (+{RANK[dl] - my})")
            if dl in SIDE_BRANCH and my < 3.5:
                leaks.append(f"{layer}/{name} -> {dl}/{dm}")
    return upward, leaks, len(modules)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--package", default="webscout_mcp")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    if not os.path.isdir(args.package):
        print(f"package directory not found: {args.package}", file=sys.stderr)
        return 2

    upward, leaks, count = check(args.package)
    if not args.quiet:
        print(f"modules scanned: {count}")
    if upward:
        print(f"UPWARD IMPORTS: {len(upward)}")
        for v in sorted(upward):
            print(f"  {v}")
    if leaks:
        print(f"SIDE-BRANCH LEAKS: {len(leaks)}")
        for v in sorted(leaks):
            print(f"  {v}")
    if not upward and not leaks:
        if not args.quiet:
            print("layer discipline holds: no upward imports, no side-branch leaks")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
