"""Score one generated held-out seed set (docs/specs/journey-followup.md AC-S05, ADR-0007).

    python3 scripts/make_score_heldout.py SEED [--dry-run]       (`make score-heldout SEED=<n>`)

Generates the set under out/score-heldout/seed-<SEED>/ with `scripts/make_dummy_followers.py --seed <SEED>
--dropout-variant` and runs `python -m part5.score_report --set` on it, which prints the per-slice score
distribution and the verdict of each target. Prints the `labels.json` sha256 so the run can be recorded.

A seed already recorded in fixtures/score-heldout.json is retired: a held-out seed is generated and scored once,
after the score freeze commit, so the script refuses it (exit 2) before it generates or scores anything. The record
itself (docs/thresholds.md "Score" and fixtures/score-heldout.json) is written by hand, as measured.

It refuses every seed of both held-out detection series too (29, 31, 37, then 67, 71, 73; ADR-0017), also one that is
not yet generated: generating and scoring such a seed here would look at it before its attempt's freeze commit.

Exit 0 scored, 1 the generator or the scorer failed, 2 usage or a retired seed. `--dry-run` prints the commands.
"""
import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RECORD = ROOT / "fixtures" / "score-heldout.json"
OUT_ROOT = ROOT / "out" / "score-heldout"


class Refused(Exception):
    """The seed cannot be scored (usage or retired); `str(e)` is the plain message."""


def recorded_seeds(record=RECORD):
    """The seeds already scored once, from the append-only record."""
    try:
        attempts = json.loads(Path(record).read_text())["attempts"]
        return sorted({int(a["seed"]) for a in attempts})
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise Refused(f"cannot read {_rel(record)} ({e}); without it a retired seed cannot be told from a new one")


def _rel(path):
    try:
        return Path(path).resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def parse_seed(text):
    if not str(text).isdigit():
        got = f" (got {text!r})" if str(text) else ""
        raise Refused(f"SEED is required and must be a whole number: make score-heldout SEED=<seed>{got}")
    return int(text)


def detection_seeds():
    """The held-out seeds of `make check-5`, both series (ADR-0003, ADR-0017), from the one list that owns them."""
    sys.path.insert(0, str(ROOT))   # run directly (python3 scripts/make_score_heldout.py) the package is not installed
    from part5.check import HELDOUT_SEEDS
    return HELDOUT_SEEDS


def check_seed(text, record=RECORD):
    """The seed as an int, or `Refused` with the plain reason (usage, a detection held-out seed, or already recorded)."""
    seed = parse_seed(text)
    if seed in detection_seeds():   # ADR-0017: generating one here and scoring it would be a look before its freeze
        raise Refused(f"seed {seed} is a held-out detection seed (ADR-0003, ADR-0017); it is generated once by "
                      "`make heldout-data` after its attempt's freeze commit and scored once by `make check-5`, "
                      "never here. Use a score seed that is not in either held-out series")
    if seed in recorded_seeds(record):
        raise Refused(f"seed {seed} is already recorded in {_rel(record)}; recorded seeds are retired (ADR-0007), "
                      "a held-out seed is generated and scored once. Use a seed that has not been scored")
    return seed


def commands(seed, out_root=OUT_ROOT):
    """(generator, scorer) as argument lists, the same two commands the 47 and 53 record names."""
    out = Path(out_root) / f"seed-{seed}"
    generator = [sys.executable, str(ROOT / "scripts" / "make_dummy_followers.py"), "--seed", str(seed),
                 "--out", str(out), "--dropout-variant"]
    scorer = [sys.executable, "-m", "part5.score_report", "--set", str(out)]
    return generator, scorer, out


def _show(command):
    """The command as a person would type it: `python3`, then the arguments with repo paths made relative."""
    return " ".join(["python3"] + [_rel(c) if c.startswith(str(ROOT)) else c for c in command[1:]])


def main(argv=None, record=RECORD, out_root=OUT_ROOT, run=subprocess.run):
    ap = argparse.ArgumentParser(prog="make_score_heldout.py", description=__doc__.splitlines()[0])
    ap.add_argument("seed", nargs="?", default="", help="the held-out seed to score (a whole number)")
    ap.add_argument("--dry-run", action="store_true", help="print the commands and stop")
    args = ap.parse_args(argv)
    try:
        seed = check_seed(args.seed, record)
    except Refused as e:
        print(f"score-heldout: {e}", file=sys.stderr)
        return 2
    generator, scorer, out = commands(seed, out_root)
    for command in (generator, scorer):
        print(f"score-heldout: {_show(command)}")
    if args.dry_run:
        return 0
    for command in (generator, scorer):
        if run(command, cwd=ROOT).returncode != 0:
            print(f"score-heldout: failed: {_show(command)}", file=sys.stderr)
            return 1
        if command is generator:
            digest = hashlib.sha256((out / "labels.json").read_bytes()).hexdigest()
            print(f"score-heldout: labels.json sha256 {digest}")
    print(f"score-heldout: seed {seed} scored once; record it in docs/thresholds.md \"Score\" and "
          f"{_rel(record)} as measured, then it is retired")
    return 0


if __name__ == "__main__":
    sys.exit(main())
