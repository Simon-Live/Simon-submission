"""GPU-free golden pipeline and `python -m part7 replay <job>` (TICKET-263, docs/specs/golden-replay.md).

Parts 3 to 6 and the Part 7 compare run on the CPU from a stored Part 2 `pose3d.json`. The same two
functions (`trainer_cpu`, `follower_cpu`) serve the golden test, the fixture regeneration and the replay
of a stored job, so the three cannot drift apart.

    python -m part7.golden regenerate   # rewrite tests/part7/fixtures/golden/expected.json from the real pipeline
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
from typing import Any

from part7 import compare, config, modules
from part7.parts import p3_skeleton, p4_animate, p5_analyse

EXIT_OK = 0
EXIT_DIFFERENT = 1
EXIT_UNUSABLE = 2

FIXTURE_DIR = config.REPO_ROOT / "tests" / "part7" / "fixtures" / "golden"
EXPECTED_FILE = "expected.json"
POSE_FILE = "pose3d.json"
TRAINER = "pexels-6326808"
TAKES = ("pexels-8026937", "pexels-4224405", "pexels-5034562")  # two followers and the mismatch take
FAULT_KEYS = ("measure", "side", "direction", "at_s", "magnitude_deg", "magnitude_m")
SCHEMA = "part7.golden/1"


class GoldenError(Exception):
    """A CPU stage failed or an input is missing."""


def _check(step: dict[str, Any], what: str, ok: tuple[int, ...] = (0,)) -> None:
    if step["exit"] not in ok:
        raise GoldenError(f"{what} exited {step['exit']}")


def trainer_cpu(pose: Path, work: Path, lock: modules.Modules) -> Path:
    """Part 3 `--view part4` and Part 4 `animate` from a trainer's pose; return `animation.json`."""
    steps, skeleton, keyframes, _note = p3_skeleton.part4(pose, "every:10", work, lock=lock)
    _check(steps[-1], "Part 3 (part4 view)")
    step, animation = p4_animate.run(skeleton, keyframes, work, lock=lock)
    _check(step, "Part 4 animate")
    return animation


def follower_cpu(pose: Path, animation: Path, work: Path, lock: modules.Modules,
                 person: str | int | None = None) -> tuple[Path, Path]:
    """Part 3 `--view part5 --fps 30` and Part 5 `analyse` (template phrasing); return `(follower, analysis)`."""
    step, follower = p3_skeleton.part5(pose, work, lock=lock, person=person)
    _check(step, "Part 3 (part5 view)")
    step, analysis, _code, _notes = p5_analyse.run(animation, follower, work, lock=lock, phrasing="template")
    _check(step, "Part 5 analyse", (0, 3))
    return follower, analysis


def summary(analysis: dict[str, Any]) -> dict[str, Any]:
    """The asserted facts of one analysis: status, score value and the fault set with times."""
    faults = [{k: f[k] for k in FAULT_KEYS if k in f}
              for f in analysis.get("faults") or [] if isinstance(f, dict)]
    return {"status": compare.status_code(analysis), "score": compare.score_value(analysis), "faults": faults}


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def run_golden(fixture_dir: Path, work: Path, lock: modules.Modules) -> dict[str, Any]:
    """Run the whole golden pipeline from the fixture poses and return what `expected.json` holds."""
    animation = trainer_cpu(fixture_dir / TRAINER / POSE_FILE, work / "trainer", lock)
    takes: dict[str, Any] = {}
    for clip in TAKES:
        _follower, analysis = follower_cpu(fixture_dir / clip / POSE_FILE, animation, work / clip, lock)
        takes[clip] = summary(_load(analysis))
    return {"schema": SCHEMA, "trainer": TRAINER, "takes": takes}


def regenerate(fixture_dir: Path = FIXTURE_DIR) -> dict[str, Any]:
    """Run the real pipeline once and write `expected.json`; the values are never typed by hand."""
    lock = modules.load()
    with tempfile.TemporaryDirectory(prefix="golden-") as tmp:
        doc = run_golden(fixture_dir, Path(tmp), lock)
    doc["pins"] = {k: lock.sha(k)[:12] for k in ("3", "4", "5")}  # informational, not asserted
    (fixture_dir / EXPECTED_FILE).write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return doc


# --------------------------------------------------------------------------- replay


# Fields that echo where the inputs lived on the run host; they differ by design between two runs.
IGNORED = {"analysis.json": frozenset({"expected.path", "follower.path"})}


def first_difference(stored: Any, fresh: Any, path: str = "", ignore: frozenset[str] = frozenset()) -> str | None:
    """The path of the first field where two parsed JSON values differ (document order), else None."""
    if path in ignore:
        return None
    if isinstance(stored, dict) and isinstance(fresh, dict):
        for key in stored:
            where = f"{path}.{key}" if path else str(key)
            if key not in fresh:
                return where
            found = first_difference(stored[key], fresh[key], where, ignore)
            if found:
                return found
        for key in fresh:
            if key not in stored:
                return f"{path}.{key}" if path else str(key)
        return None
    if isinstance(stored, list) and isinstance(fresh, list):
        for i, (a, b) in enumerate(zip(stored, fresh)):
            found = first_difference(a, b, f"{path}[{i}]", ignore)
            if found:
                return found
        return f"{path}[{min(len(stored), len(fresh))}]" if len(stored) != len(fresh) else None
    return None if stored == fresh and type(stored) is type(fresh) else (path or "(document)")


def _job_dir(job: str, state: Path | None) -> Path:
    direct = Path(job)
    if direct.is_dir():
        return direct
    return (state or config.dev_dir()) / "jobs" / job


def replay(job_dir: Path, lock: modules.Modules | None = None) -> tuple[int, str]:
    """Re-run the CPU stages of a stored follow job and compare to its stored outputs.

    Inputs: `work/expected.json` (the trainer animation) and `work/follower/part2/pose3d.json`.
    Compared: `work/follower/follower.json` and `work/follower/analysis.json`, each field by field.
    Returns `(0, message)` on equality, `(1, message naming the first differing field)`, `(2, why)` when
    the job lacks a file.
    """
    work = job_dir / "work"
    fdir = work / "follower"
    needed = {"animation": work / "expected.json", "pose": fdir / "part2" / POSE_FILE,
              "follower.json": fdir / "follower.json", "analysis.json": fdir / "analysis.json"}
    missing = [name for name, p in needed.items() if not p.is_file()]
    if missing:
        return EXIT_UNUSABLE, f"replay: {job_dir.name} lacks {', '.join(missing)}"
    meta = _load(job_dir / "job.json") if (job_dir / "job.json").is_file() else {}
    person = meta.get("person_id") if isinstance(meta, dict) else None
    lk = lock or modules.load()
    with tempfile.TemporaryDirectory(prefix="replay-") as tmp:
        try:
            follower, analysis = follower_cpu(needed["pose"], needed["animation"], Path(tmp), lk, person=person)
        except GoldenError as exc:
            return EXIT_UNUSABLE, f"replay: {exc}"
        for name, fresh in (("follower.json", follower), ("analysis.json", analysis)):
            found = first_difference(_load(needed[name]), _load(fresh), ignore=IGNORED.get(name, frozenset()))
            if found:
                return EXIT_DIFFERENT, f"replay: {name} differs at {found}"
    return EXIT_OK, f"replay: {job_dir.name} reproduces follower.json and analysis.json"


def cli_replay(job: str, state: Path | None = None) -> int:
    """`python -m part7 replay <job>`: a job id (under the state's jobs folder) or a job folder path."""
    code, message = replay(_job_dir(job, state))
    print(message, file=sys.stderr if code else sys.stdout)
    return code


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args != ["regenerate"]:
        print("usage: python -m part7.golden regenerate", file=sys.stderr)
        return EXIT_UNUSABLE
    print(json.dumps(regenerate(), indent=2))
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
