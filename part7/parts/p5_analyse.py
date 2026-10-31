"""Part 5 adapter: follower fault analysis and contract doctor (TICKET-010)."""

from __future__ import annotations

import json
from pathlib import Path

from part7 import config, modes, modules, runner
from part7.parts import probe

PHRASING_CONCURRENCY = "4"
_ANALYSE_ARGV = ["uv", "run", "python", "-m", "part5", "analyse"]


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

    `mode` becomes `--profile <mode>` only when Part 5's analyse help offers `--profile`, else a note is added.
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

    if mode is not None:
        # ASM: Part 5 TICKET-042 adds `--profile`; until the pin has it, the mode changes coaching and practice only
        if probe.has_flag(5, _ANALYSE_ARGV, clone, "--profile", lk):
            extra += ["--profile", mode]
        else:
            notes.append(modes.NOTE_NO_PROFILE)

    step = runner.run(
        5,
        [*_ANALYSE_ARGV, "--expected", str(Path(expected).resolve()), "--follower", str(Path(follower).resolve()),
         "--out", str(out_path.resolve()), *extra],
        cwd=clone,
        env_extra={"PART5_PHRASING_CONCURRENCY": PHRASING_CONCURRENCY},  # harmless where the pin ignores it
        timeout_s=config.TIMEOUTS["5"],
        log_path=work_p / "steps" / "part5_analyse.log",
        lock=lk,
    )

    status_code = "error"
    if step["exit"] in (0, 3) and out_path.is_file():
        try:
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
