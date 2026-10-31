"""Part 5 adapter: follower fault analysis and contract doctor (TICKET-010)."""

from __future__ import annotations

import json
from pathlib import Path

from part7 import applog, config, mode_rules, modules, runner
from part7.parts import probe

PHRASING_CONCURRENCY = "4"
_ANALYSE_ARGV = ["uv", "run", "python", "-m", "part5", "analyse"]
_MODE_RUNNER = Path(__file__).resolve().parent.parent / "p5_mode_runner.py"
_RUNNER_PREFIX = ["uv", "run", "python", str(_MODE_RUNNER)]


def mode_runner_ok(clone: Path, lock: modules.Modules | None = None) -> bool:
    """True when the pinned Part 5 has the patch points the mode runner needs (probed by import, cached)."""
    return probe.cached(clone, "mode-runner", lambda: runner.run(
        5, [*_RUNNER_PREFIX, "--probe"], cwd=clone, timeout_s=probe.HELP_TIMEOUT_S, lock=lock)["exit"] == 0)


def _add_profile(out_path: Path, mode: str) -> None:
    """Record the mode and where its rules came from, unless Part 5 already set a profile."""
    try:
        doc = json.loads(out_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if isinstance(doc, dict) and "profile" not in doc:
        doc["profile"], doc["profile_source"] = mode, mode_rules.PROFILE_SOURCE
        out_path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")


def _fault_keys(path: Path) -> set[tuple[str, str]] | None:
    """The `(measure, side)` of every fault in an analysis file, None when it cannot be read."""
    try:
        return {(f["measure"], f.get("side")) for f in json.loads(path.read_text(encoding="utf-8")).get("faults") or []}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None


def _standard_then_mode(call, work: Path, out_path: Path, extra: list[str], head: list[str], mode: str,
                        notes: list[str]) -> tuple[runner.Step, bool]:
    """Standard rules first, then the mode's; keep the mode's result only when it adds no fault (ADR-0008).

    The standard run writes the final files. The mode run writes beside them and replaces them when it passes
    the check; otherwise the standard result stays and a job note says why.
    """
    std = call(list(_ANALYSE_ARGV), out_path, extra, "part5_analyse_standard.log")
    if std["exit"] not in (0, 3) or not out_path.is_file():
        return std, False
    mode_out = work / f"analysis-{mode}.json"
    mode_extra = [str(work / f"replay-{mode}.json") if a == str((work / "replay.json").resolve()) else a
                  for a in extra]
    step = call(head, mode_out, mode_extra, "part5_analyse.log")
    std_keys, mode_keys = _fault_keys(out_path), _fault_keys(mode_out)
    ok = step["exit"] in (0, 3) and mode_out.is_file() and std_keys is not None and mode_keys is not None
    if ok and mode_keys <= std_keys:
        mode_out.replace(out_path)
        replay = work / f"replay-{mode}.json"
        if replay.is_file():
            replay.replace(work / "replay.json")
        applog.log(f"part 5 scoring: {mode} rules kept", applog.job_id_of(work), work)
        return step, True
    note = mode_rules.NOTE_ADDS_FAULT if ok else mode_rules.NOTE_RUN_FAILED.format(mode=mode)
    notes.append(note)
    applog.log(f"part 5 scoring: {mode} rules dropped, standard rules used ({note})", applog.job_id_of(work), work)
    return std, False


def phrasing_args(clone: Path, phrasing: str, lock: modules.Modules | None = None) -> tuple[list[str], str | None]:
    """Return the `--phrasing` argv for `live` or `template` and a note when the pin cannot do `live`."""
    argv = _ANALYSE_ARGV
    if phrasing == "live":
        text = probe.help_text(5, argv, clone, lock)
        if "muse-spark" in text and "--live" in text:
            return (["--phrasing", "muse-spark", "--live"], None)
        return (["--phrasing", "template"], "live phrasing is not offered by Part 5 at this pin, template used")
    return (["--phrasing", "template"], None)


def run(
    expected: Path | str,
    follower: Path | str,
    work: Path | str,
    lock: modules.Modules | None = None,
    state: Path | str | None = None,
    phrasing: str = "template",
    expected_visibility: Path | str | None = None,
    mode: str | None = None,
) -> tuple[runner.Step, Path, str, list[str]]:
    """Run Part 5 `analyse` (exits 0 and 3 write a file) and return `(step, analysis, status_code, notes)`.

    Scoring path for `mode` (ADR-0008, superseded in practice at Part 5 d655d50, TICKET-094): Part 5's `--profile <mode>` when its analyse help offers it; else, for
    dance and rehab, Part 5's own CLI through `p5_mode_runner` with rules derived from its `rules.json`; else the
    plain CLI (fitness or no mode; for dance and rehab on a Part 5 the runner cannot patch, with a note).
    The log line `part 5 scoring: ...` in the job's `steps/part7.log` says which path ran.
    `--replay <work>/replay.json` is passed when the pin offers it; the notes name what the pin lacks.
    `expected_visibility` (the trainer's `skeleton.json`) becomes `--expected-visibility` when the pin has the
    flag; Part 5 then refuses a take whose visible body cannot be scored (`not_enough_visible`,
    `moving_part_out_of_frame`).
    """
    lk = lock or modules.load()
    clone = lk.path("5")
    work_p = Path(work)
    work_p.mkdir(parents=True, exist_ok=True)
    out_path = work_p / "analysis.json"
    notes: list[str] = []

    extra, note = phrasing_args(clone, phrasing, lk)
    if note:
        notes.append(note)
    if probe.has_flag(5, _ANALYSE_ARGV, clone, "--replay", lk):
        extra += ["--replay", str((work_p / "replay.json").resolve())]
    else:
        notes.append("Part 5 at this pin writes no replay file")

    if expected_visibility is not None:
        if probe.has_flag(5, _ANALYSE_ARGV, clone, "--expected-visibility", lk):
            extra += ["--expected-visibility", str(Path(expected_visibility).resolve())]
        else:
            notes.append("Part 5 at this pin cannot check what is visible, the take was scored without that check")

    # TICKET-094: Part 5's own `--profile` wins when the pin has it (d655d50 and later); no mode passes nothing, and
    # Part 5 reports "fitness". ADR-0008's Part 7 rules for dance and rehab run only on a pin without the flag.
    argv_head, scored_by, tag_profile, use_runner = list(_ANALYSE_ARGV), "standard rules", False, False
    if mode is not None:
        if probe.has_flag(5, _ANALYSE_ARGV, clone, "--profile", lk):
            extra += ["--profile", mode]
            scored_by = f"Part 5 --profile {mode}"
        elif mode in mode_rules.FACTORS:
            if mode_runner_ok(clone, lk):
                variant = mode_rules.write_variant(clone, mode, work_p / f"rules-{mode}.json")
                argv_head = [*_RUNNER_PREFIX, "--rules", str(variant.resolve()), "analyse"]
                scored_by, tag_profile, use_runner = f"Part 7 {mode} rules", True, True
            else:
                notes.append(mode_rules.NOTE_UNAVAILABLE.format(mode=mode))
        elif mode == "fitness":
            tag_profile = True  # Part 5's standard rule set, named so the result says what scored it
    applog.log(f"part 5 scoring: {scored_by}", applog.job_id_of(work_p), work_p)

    inputs = ["--expected", str(Path(expected).resolve()), "--follower", str(Path(follower).resolve())]

    def call(head: list[str], out: Path, args: list[str], log: str) -> runner.Step:
        return runner.run(
            5, [*head, *inputs, "--out", str(out.resolve()), *args], cwd=clone,
            env_extra={"PART5_PHRASING_CONCURRENCY": PHRASING_CONCURRENCY},  # harmless where the pin ignores it
            timeout_s=config.TIMEOUTS["5"], log_path=work_p / "steps" / log, lock=lk)

    tag = mode
    if use_runner and mode is not None:
        step, kept = _standard_then_mode(call, work_p, out_path, extra, argv_head, mode, notes)
        tag = mode if kept else "fitness"  # a dropped mode result is the standard rules, and says so
    else:
        step = call(argv_head, out_path, extra, "part5_analyse.log")

    status_code = "error"
    if step["exit"] in (0, 3) and out_path.is_file():
        try:
            if tag_profile and tag is not None:
                _add_profile(out_path, tag)
            doc = json.loads(out_path.read_text(encoding="utf-8"))
            st = doc.get("status")
            if isinstance(st, dict):
                status_code = str(st.get("code") or "ok")
            elif isinstance(st, str) and st:
                status_code = st
            else:
                status_code = "ok"
        except (OSError, json.JSONDecodeError):
            status_code = "error"

    return (step, out_path, status_code, notes)


def doctor(
    path: Path | str,
    work: Path | str,
    consumer: str = "part7",
    lock: modules.Modules | None = None,
    state: Path | str | None = None,
) -> runner.Step:
    """Run Part 5's `doctor <path> --for <consumer>` command."""
    lk = lock or modules.load()
    clone = lk.path("5")
    work_p = Path(work)
    return runner.run(
        5,
        [
            "uv",
            "run",
            "python",
            "-m",
            "part5",
            "doctor",
            str(Path(path).resolve()),
            "--for",
            consumer,
        ],
        cwd=clone,
        timeout_s=config.TIMEOUTS["doctor"],
        log_path=work_p / "steps" / f"part5_doctor_{consumer}.log",
        lock=lk,
    )
