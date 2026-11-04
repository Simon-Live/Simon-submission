"""Go back to `simon.score.v1` (ADR-0018 and ADR-0019, "Reversal"): the commit recipe for "v2 or v3 failed on its seed", as one command.

    python3 scripts/make_score_fallback.py [--root DIR] [--no-regenerate] [--check]        (`make score-fallback`)

ADR-0018 ships v2 only if seed 59 holds every target, and ADR-0019 ships v3 only if seed 61 does; otherwise v1 stays. This
turns a tree that ships v2 or v3 into a tree that ships v1 and is green, in the order the ADRs state:

1. `part5/rules.json`: the `score` section becomes its `v1` block, the frozen params whose `params_sha256` fixtures/
   score-heldout.json recorded for seeds 47 and 53. Every other key is left as it is (the detection hash is checked
   before and after, and the script stops if it moved). A v3 section also keeps `v2`; it goes with the rest of the section
   (v2 stays reproducible from the record and git history: its hash is `60116de4...`).
2. `fixtures/output/analysis.fault-capped.example.json` and `analysis.double-capped.example.json` are removed: they are v2 and
   v3 samples (a ceiling that v1 does not have).
3. The goldens (`scripts/make_output_examples.py`) and the fitness baseline (`python -m part5.profiles_report
   --write-baseline`) are written again, because the score block is in every analysis.

`fixtures/score-heldout.json` is not touched: the freezes and the seed 59 and 61 attempts stay in it as the record, and
`part5.check.recorded_score_hash` looks the frozen hash up by the version the rules ship, so `make check-5` finds
`e818635b...` for v1 whatever was appended after. The tests that depend on the shipped version read it (tests/
shipped_score.py), so `make test` is green on the result. What the script cannot do is the publication of the seed's
result (docs/thresholds.md, fixtures/score-heldout.json, the ADR's Status): that is written by hand, as measured.

`--check` only says whether the tree ships v2 or v3 and could be rolled back (exit 0), ships v1 already (exit 3) or has no
`v1` block to go back to (exit 2). `--no-regenerate` stops after step 1 and 2. Exit 0 done, 1 a step failed, 2 not a v2 or v3
tree (no `v1` block to go back to, or rules that cannot be read), 3 the tree already ships v1 (nothing to go back to).
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
V1, V2, V3 = "simon.score.v1", "simon.score.v2", "simon.score.v3"
ADR = {V2: "ADR-0018", V3: "ADR-0019"}   # the ADR that states each version's reversal
SAMPLES = (Path("fixtures") / "output" / "analysis.fault-capped.example.json",
           Path("fixtures") / "output" / "analysis.double-capped.example.json")


class Refused(Exception):
    """The tree cannot be rolled back (`str(e)` is the plain message) with `code` as the exit status."""

    def __init__(self, message, code=2):
        super().__init__(message)
        self.code = code


def detection_hash(rules):
    """The detection hash `part5.check.detection_hash` records: the rules without `score`, sorted compact JSON."""
    kept = {k: v for k, v in rules.items() if k != "score"}
    return hashlib.sha256(json.dumps(kept, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def load_rules(root):
    path = Path(root) / "part5" / "rules.json"
    try:
        return path, json.loads(path.read_text())
    except (OSError, ValueError) as e:
        raise Refused(f"cannot read {path} ({e})")


def shipped_version(rules):
    block = rules.get("score")
    return block.get("version") if isinstance(block, dict) else None


def v1_rules(rules):
    """`rules` with the `score` section replaced by its `v1` block, or `Refused` saying why that cannot be done."""
    version = shipped_version(rules)
    if version == V1:
        raise Refused("part5/rules.json already ships simon.score.v1; there is nothing to go back to", 3)
    v1 = rules["score"].get("v1") if isinstance(rules.get("score"), dict) else None
    if version not in ADR or not isinstance(v1, dict) or v1.get("version") != V1:
        raise Refused(f"part5/rules.json ships {version!r} with no {V1} 'v1' block to go back to")
    return {**rules, "score": v1}


def write_rules(path, rules):
    """The rules file as `part5.calibrate` writes it: indent 2 and a final newline."""
    path.write_text(json.dumps(rules, indent=2) + "\n")


def run(command, root):
    """`command` run in `root` with `root` first on the import path, so a copy of the tree uses its own `part5`."""
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(root), os.environ.get("PYTHONPATH", "")]).rstrip(os.pathsep)}
    done = subprocess.run(command, cwd=root, env=env)
    if done.returncode != 0:
        raise Refused(f"failed: {' '.join(map(str, command))}", 1)


def fall_back(root=ROOT, regenerate=True, runner=run):
    """Go back to v1 in the tree at `root`; returns the lines to print. `Refused` when it cannot."""
    root = Path(root)
    path, rules = load_rules(root)
    version = shipped_version(rules)
    changed = v1_rules(rules)
    if detection_hash(changed) != detection_hash(rules):   # cannot happen: only `score` is replaced; a guard, not a feature
        raise Refused("replacing the score section moved the detection hash; nothing was written", 1)
    write_rules(path, changed)
    removed = [sample for sample in SAMPLES if (root / sample).exists()]
    for sample in removed:
        (root / sample).unlink()
    lines = [f"score-fallback: {path.relative_to(root)} ships {V1} (the `v1` block, params_sha256 recorded for seeds 47 and 53)"]
    lines += [f"score-fallback: removed {sample.as_posix()} (a {version} sample)" for sample in removed]
    if regenerate:
        runner([sys.executable, str(root / "scripts" / "make_output_examples.py")], root)
        runner([sys.executable, "-m", "part5.profiles_report", "--write-baseline"], root)
        lines.append("score-fallback: goldens and the fitness baseline written again")
    lines.append("score-fallback: next, in order: make test; make check-5-contract; python3 scripts/make_design_copies.py; "
                 f"then commit with the {version} result published (docs/thresholds.md, fixtures/score-heldout.json with "
                 f"scored_at and holds false, {ADR[version]} Status)")
    return lines


def main(argv=None, root=ROOT, runner=run):
    ap = argparse.ArgumentParser(prog="make_score_fallback.py", description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=str(root), help="the tree to roll back (default: this repository)")
    ap.add_argument("--no-regenerate", action="store_true", help="only replace the score section and remove the samples")
    ap.add_argument("--check", action="store_true", help="say whether the tree ships v2 or v3 and can go back; change nothing")
    args = ap.parse_args(argv)
    try:
        if args.check:
            rules = load_rules(args.root)[1]
            v1_rules(rules)
            print(f"score-fallback: {args.root} ships {shipped_version(rules)} and holds the {V1} block to go back to")
            return 0
        print("\n".join(fall_back(args.root, not args.no_regenerate, runner)))
    except Refused as e:
        print(f"score-fallback: {e}", file=sys.stderr)
        return e.code
    return 0


if __name__ == "__main__":
    sys.exit(main())
