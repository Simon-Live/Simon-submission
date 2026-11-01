"""Score one generated held-out seed set (docs/specs/journey-followup.md AC-S05, ADR-0007).

    python3 scripts/make_score_heldout.py SEED [--dry-run]       (`make score-heldout SEED=<n>`)

Generates the set under out/score-heldout/seed-<SEED>/ with `scripts/make_dummy_followers.py --seed <SEED>
--dropout-variant` and runs `python -m part5.score_report --set` on it, which prints the per-slice score
distribution and the verdict of each target. Prints the `labels.json` sha256 so the run can be recorded.

A seed already recorded in fixtures/score-heldout.json is retired: a held-out seed is generated and scored once,
after the score freeze commit, so the script refuses it (exit 2) before it generates or scores anything. The record
itself (docs/thresholds.md "Score" and fixtures/score-heldout.json) is written by hand, as measured.

Score v2 (ADR-0018): seed 59 is its seed, and it is refused until fixtures/score-heldout.json lists, under `freezes`,
a `simon.score.v2` freeze whose `params_sha256` is the hash of the `score` block of part5/rules.json now (the
orchestrator records it at the freeze, before the seed is generated). The score code is frozen with the params: seed 59 is
also refused unless the working tree is clean and `git diff <freeze_commit> HEAD -- <CODE_PATHS>` is empty: the code
(part5, scripts, contracts), the trainer's clips and feet (fixtures/input/expected, expected-feet) and the dependencies
(pyproject.toml, uv.lock); the freeze record's own commit touches fixtures/score-heldout.json and docs/thresholds.md only, so it
passes. It is refused when the record holds more than one v2 freeze (a re-freeze after seeing the seed) and when the seed's
directory under out/score-heldout/ already exists (a set is written and scored once). After scoring the script prints
`scored_at` (`git rev-parse HEAD`), for seed 59 `holds` (the report's `targets_v2.holds`) and the exact JSON line to append to
`attempts`; `make check-5` refuses a v2 block when the seed 59 attempt, with or without a `version`, has `holds` false or none.
Seed 61 is reserved for a later retry with a new approach family and is always refused.

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
RULES = ROOT / "part5" / "rules.json"
OUT_ROOT = ROOT / "out" / "score-heldout"
V2_SEED = 59        # ADR-0018: the seed simon.score.v2 is scored on, once, after its freeze is recorded
RESERVED_SEED = 61  # ADR-0007, ADR-0018: reserved for a retry with a new approach family
REPORT = "report.json"   # the v2 seed's JSON report, in its set's directory
# What a score freeze covers besides the params (they are in part5/rules.json): the code that reads them, the contracts, the
# trainer's clips and feet the score is measured against, and the dependencies. A change to any of them after the freeze is refused.
CODE_PATHS = ("part5", "scripts", "contracts", "fixtures/input/expected", "fixtures/input/expected-feet", "pyproject.toml",
              "uv.lock")


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


def score_check():
    """`part5.check`, imported lazily and with the repo on the path for the same reason as `detection_seeds`."""
    sys.path.insert(0, str(ROOT))
    import part5.check as check
    return check


def run_git(root, *args):
    """`(exit code, stdout)` of `git -C root args`; `(127, "")` when git cannot be run."""
    try:
        done = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    except OSError:
        return 127, ""
    return done.returncode, done.stdout


def require_frozen_code(commit, root=ROOT, git=run_git):
    """`Refused` unless the code seed 59 is scored with is the code that was frozen (ADR-0018): `commit` (the freeze entry's
    `freeze_commit`) is in the history, the working tree has no uncommitted change and no untracked file under `CODE_PATHS`,
    and `git diff <commit> HEAD -- <CODE_PATHS>` is empty. The params are hashed by the freeze record; this covers
    the code that reads them. The freeze record's commit itself touches fixtures/score-heldout.json and docs/thresholds.md,
    which are outside the paths, so recording the freeze does not trip it."""
    if not commit:
        raise Refused(f"seed {V2_SEED} needs the freeze entry to name its freeze_commit, the commit whose part5, scripts and "
                      "contracts were frozen with the params (ADR-0018)")
    if git(root, "rev-parse", "--verify", "--quiet", f"{commit}^{{commit}}")[0] != 0:
        raise Refused(f"seed {V2_SEED}: the freeze commit {commit} is not in this repository's history (or git cannot be run), "
                      "so the code it froze cannot be compared with the code here (ADR-0018)")
    code, dirty = git(root, "status", "--porcelain", "--untracked-files=no")
    code2, new = git(root, "status", "--porcelain", "--untracked-files=all", "--", *CODE_PATHS)
    if code != 0 or code2 != 0:
        raise Refused(f"seed {V2_SEED}: git status failed, so the tree cannot be shown to be clean (ADR-0018)")
    if dirty.strip() or new.strip():
        names = ", ".join(line[3:] for line in (dirty + new).splitlines()[:5])
        raise Refused(f"seed {V2_SEED} is scored from a clean tree only, and this one has uncommitted changes ({names}); "
                      "commit or discard them first (ADR-0018)")
    code, changed = git(root, "diff", "--name-only", commit, "HEAD", "--", *CODE_PATHS)
    if code != 0:
        raise Refused(f"seed {V2_SEED}: git diff against the freeze commit {commit} failed (ADR-0018)")
    if changed.strip():
        files = changed.split()
        raise Refused(f"seed {V2_SEED} was frozen with the code of {commit[:12]}, and {len(files)} file(s) under "
                      f"{', '.join(CODE_PATHS)} differ from it now ({', '.join(files[:5])}); the score code, the trainer's clips "
                      "and the dependencies are frozen with the params, so a change after the freeze needs a new freeze (ADR-0018)")


def require_v2_freeze(record, rules, root=ROOT, git=run_git):
    """`Refused` unless `record` lists a simon.score.v2 freeze whose hash is the `score` block of `rules` now, and the code
    under `root` is the code of the freeze's commit (`require_frozen_code`)."""
    check = score_check()
    version = check.score_version(rules)
    shipped = check.score_params_hash(rules)
    frozen = check.recorded_score_hash(record, check.VERSION)
    entries = [f for f in json.loads(Path(record).read_text()).get("freezes", []) if f.get("version") == check.VERSION]
    if version != check.VERSION:
        raise Refused(f"seed {V2_SEED} is the {check.VERSION} seed, and {_rel(rules)} ships {version}; the v2 score "
                      "is not the one in force (ADR-0018)")
    if frozen is None:
        raise Refused(f"seed {V2_SEED} needs the {check.VERSION} freeze: {_rel(record)} has no `freezes` entry for it. "
                      "The orchestrator records {version, freeze_commit, params_sha256} there at the freeze, with "
                      "`python -m part5.score_report --params-sha256` (ADR-0018); then this seed is generated once")
    if frozen != shipped:
        raise Refused(f"seed {V2_SEED} needs the score params frozen in {_rel(record)} (sha256 {frozen[:12]}), but "
                      f"{_rel(rules)} has sha256 {shipped[:12]}; the params are frozen before the seed is scored (ADR-0018)")
    if len(entries) > 1:   # one freeze, one seed: a second freeze is a re-freeze and rescore after seeing seed 59
        raise Refused(f"seed {V2_SEED}: {_rel(record)} holds {len(entries)} {check.VERSION} freeze entries; a score is frozen "
                      "once and scored once, and a re-freeze after seeing the seed is refused (ADR-0018)")
    require_frozen_code(check.recorded_freeze(record, check.VERSION).get("freeze_commit"), root, git)


def check_seed(text, record=RECORD, rules=RULES, root=ROOT, git=run_git, out_root=OUT_ROOT):
    """The seed as an int, or `Refused` with the plain reason (usage, a detection held-out seed, the reserved seed,
    a seed 59 without its freeze, or already recorded)."""
    seed = parse_seed(text)
    if seed in detection_seeds():   # ADR-0017: generating one here and scoring it would be a look before its freeze
        raise Refused(f"seed {seed} is a held-out detection seed (ADR-0003, ADR-0017); it is generated once by "
                      "`make heldout-data` after its attempt's freeze commit and scored once by `make check-5`, "
                      "never here. Use a score seed that is not in either held-out series")
    if seed == RESERVED_SEED:
        raise Refused(f"seed {seed} is reserved (ADR-0007, ADR-0018): it is for a retry of the score with a new approach "
                      "family, named in an ADR before it is generated. Use a seed that has not been scored")
    if seed in recorded_seeds(record):
        raise Refused(f"seed {seed} is already recorded in {_rel(record)}; recorded seeds are retired (ADR-0007), "
                      "a held-out seed is generated and scored once. Use a seed that has not been scored")
    if seed == V2_SEED:
        require_v2_freeze(record, rules, root, git)
        generated = Path(out_root) / f"seed-{seed}"
        if generated.exists():   # a set written once is never written or scored again, whatever the record says
            raise Refused(f"seed {seed} was already generated here ({_rel(generated)} exists); a seed is generated and scored "
                          "once (ADR-0018). If the generator failed before it scored, remove the directory by hand and say why "
                          "in the record")
    return seed


def commands(seed, out_root=OUT_ROOT):
    """(generator, scorer, out) as argument lists, the same two commands the 47 and 53 record names. The scorer of the v2
    seed also writes its JSON report beside the set (`report.json`), for the `holds` the attempt records."""
    out = Path(out_root) / f"seed-{seed}"
    generator = [sys.executable, str(ROOT / "scripts" / "make_dummy_followers.py"), "--seed", str(seed),
                 "--out", str(out), "--dropout-variant"]
    scorer = [sys.executable, "-m", "part5.score_report", "--set", str(out)]
    if seed == V2_SEED:
        scorer += ["--json-out", str(out / REPORT)]
    return generator, scorer, out


def _show(command):
    """The command as a person would type it: `python3`, then the arguments with repo paths made relative."""
    return " ".join(["python3"] + [_rel(c) if c.startswith(str(ROOT)) else c for c in command[1:]])


def v2_attempt(report, holds, labels_sha256, scored_at, record, rules, commands_run):
    """The `attempts` entry of the v2 seed, as `fixtures/score-heldout.json` records one: the version (`simon.score.v2`, so
    `make check-5` reads it as v2's), the freeze it was scored under, `scored_at`, `holds` (what `make check-5` refuses a v2
    block on when it is false), the commands, the labels hash and the measured slices and targets."""
    check = score_check()
    targets = {k: v["verdict"] for k, v in report["targets_v2"].items() if isinstance(v, dict) and "verdict" in v}
    targets["sweep"] = "fail" if report["targets_v2"]["sweep_failures"] else "pass"
    return {"seed": V2_SEED, "version": check.VERSION,
            "freeze_commit": check.recorded_freeze(record, check.VERSION).get("freeze_commit"),
            "params_sha256": check.score_params_hash(rules), "scored_at": scored_at, "holds": holds,
            "generator": _show(commands_run[0]), "scorer": _show(commands_run[1]), "labels_sha256": labels_sha256,
            "slices": report["distribution"], "targets": targets}


def main(argv=None, record=RECORD, out_root=OUT_ROOT, run=subprocess.run, rules=RULES, root=ROOT, git=run_git):
    ap = argparse.ArgumentParser(prog="make_score_heldout.py", description=__doc__.splitlines()[0])
    ap.add_argument("seed", nargs="?", default="", help="the held-out seed to score (a whole number)")
    ap.add_argument("--dry-run", action="store_true", help="print the commands and stop")
    args = ap.parse_args(argv)
    try:
        seed = check_seed(args.seed, record, rules, root, git, out_root)
    except Refused as e:
        print(f"score-heldout: {e}", file=sys.stderr)
        return 2
    generator, scorer, out = commands(seed, out_root)
    for command in (generator, scorer):
        print(f"score-heldout: {_show(command)}")
    if args.dry_run:
        return 0
    digest = None
    for command in (generator, scorer):
        if run(command, cwd=ROOT).returncode != 0:
            print(f"score-heldout: failed: {_show(command)}", file=sys.stderr)
            return 1
        if command is generator:
            digest = hashlib.sha256((out / "labels.json").read_bytes()).hexdigest()
            print(f"score-heldout: labels.json sha256 {digest}")
    scored_at = git(root, "rev-parse", "HEAD")[1].strip() or "unknown"
    print(f"score-heldout: scored_at {scored_at}")
    if seed == V2_SEED:
        try:
            report = json.loads((out / REPORT).read_text())
            holds = report["targets_v2"]["holds"]
        except (OSError, ValueError, KeyError, TypeError) as e:
            print(f"score-heldout: cannot read `holds` from {_rel(out / REPORT)} ({e}); the attempt must record it", file=sys.stderr)
            return 1
        print(f"score-heldout: holds {str(holds).lower()} (the report's targets_v2.holds"
              + ("" if holds else "; v2 does not ship: make score-fallback, ADR-0018") + ")")
        print(f"score-heldout: the line to append to `attempts` in {_rel(record)}, exactly as printed:")
        print(json.dumps(v2_attempt(report, holds, digest, scored_at, record, rules, (generator, scorer))))
    print(f"score-heldout: seed {seed} scored once; record it in docs/thresholds.md \"Score\" and "
          f"{_rel(record)} as measured, then it is retired")
    return 0


if __name__ == "__main__":
    sys.exit(main())
