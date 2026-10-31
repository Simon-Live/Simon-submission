"""Run Part 5's own command line with a rules file swapped in (ADR-0008).

Run with Part 5's interpreter, cwd the Part 5 clone, exactly as `p5_analyse` runs `python -m part5`:

    uv run python p5_mode_runner.py --probe
    uv run python p5_mode_runner.py --rules <rules.json> analyse --expected ... --out ...

It does not edit Part 5. It replaces `load_rules` in every Part 5 module that imports it, then calls
`part5.cli.main` with the remaining arguments, so the outputs have Part 5's own shape. Standard library only.
"""

from __future__ import annotations

import copy
import json
import os
import sys

REQUIRED = ("part5.pipeline", "part5.detect")  # the patch points the operator named; others are patched if present


def _import_all() -> list:
    """The part5 modules to patch, after importing the CLI so the whole scoring path is loaded."""
    sys.path.insert(0, os.getcwd())  # a script path puts its own folder first, not the clone
    import importlib

    cli = importlib.import_module("part5.cli")
    if not callable(getattr(cli, "main", None)):
        raise ImportError("part5.cli.main is missing")
    for name in REQUIRED:
        if not callable(getattr(importlib.import_module(name), "load_rules", None)):
            raise ImportError(f"{name}.load_rules is missing")
    return [m for n, m in list(sys.modules.items()) if (n == "part5" or n.startswith("part5.")) and
            callable(getattr(m, "load_rules", None))]


def patch(rules_path: str) -> list[str]:
    """Make every `load_rules` in Part 5 return the rules in `rules_path`; return the patched module names."""
    mods = _import_all()
    with open(rules_path, encoding="utf-8") as fh:
        variant = json.load(fh)

    def load_rules(path=None):  # noqa: ARG001, Part 5 calls it with an optional path
        return copy.deepcopy(variant)

    for m in mods:
        m.load_rules = load_rules
    return sorted(m.__name__ for m in mods)


def main(argv: list[str]) -> int:
    if argv[:1] == ["--probe"]:
        try:
            patched = _import_all()
        except Exception as exc:  # any import problem means the patch points are not there
            print(f"unavailable: {exc}")
            return 1
        print("ok " + " ".join(sorted(m.__name__ for m in patched)))
        return 0
    if len(argv) < 3 or argv[0] != "--rules":
        print("usage: p5_mode_runner.py --probe | --rules <rules.json> <part5 arguments>", file=sys.stderr)
        return 2
    patch(argv[1])
    from part5.cli import main as part5_main

    return part5_main(argv[2:])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
