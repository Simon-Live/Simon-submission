"""Part 5 adapter: follower fault analysis and contract doctor (TICKET-010)."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import threading
import uuid

from part7 import applog, config, modules, private_mode, runner
from part7.parts import probe

PHRASING_CONCURRENCY = "4"
_ANALYSE_ARGV = ["uv", "run", "python", "-m", "part5", "analyse"]
PROFILE_SOURCE = "part7-rules"
NOTE_UNAVAILABLE = "Scoring rules for {mode} unavailable in this Part 5; standard rules used"


def _without_videos(args: list[str]) -> list[str]:
    """`args` without `--expected-video X` and `--follower-video Y`."""
    out: list[str] = []
    skip = False
    for a in args:
        if skip:
            skip = False
        elif a in ("--expected-video", "--follower-video"):
            skip = True
        else:
            out.append(a)
    return out


_KNOWN: dict[str, bool] | None = None  # the last probe answer; None until the first probe finishes
_WARMING = threading.Lock()


def known_capabilities() -> dict[str, bool]:
    """What `capabilities` last found, without probing: all false until the warm-up thread has finished.

    `api/config` calls this, so a request never waits on the three Part 5 probes (each can spawn `uv run`).
    """
    return dict(_KNOWN) if _KNOWN is not None else {"lang": False, "video": False, "private": False}


def warm(lock: modules.Modules | None = None) -> threading.Thread:
    """Run the probes in a background thread (at server start) and cache the answer for `known_capabilities`."""
    def work() -> None:
        global _KNOWN
        with _WARMING:
            _KNOWN = capabilities(lock)

    thread = threading.Thread(target=work, name="p5-capabilities", daemon=True)
    thread.start()
    return thread


def capabilities(lock: modules.Modules | None = None) -> dict[str, bool]:
    """What the pinned Part 5 offers, from the probes `run` uses (cached per clone): `lang`, `video`, `private`."""
    try:
        lk = lock or modules.load()
        clone = lk.path("5")
        return {
            "lang": probe.has_flag(5, _ANALYSE_ARGV, clone, "--lang", lk),
            "video": probe.has_flag(5, _ANALYSE_ARGV, clone, "--expected-video", lk)
            and probe.has_flag(5, _ANALYSE_ARGV, clone, "--follower-video", lk),
            "private": probe.cached(clone, "private-fix", lambda: private_mode.part5_has_fix(clone)),
        }
    except Exception:  # a missing clone or a failed probe means nothing is offered
        return {"lang": False, "video": False, "private": False}


def _add_profile(out_path: Path, mode: str) -> None:
    """Record the mode and where its rules came from, unless Part 5 already set a profile."""
    try:
        doc = json.loads(out_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if isinstance(doc, dict) and "profile" not in doc:
        doc["profile"], doc["profile_source"] = mode, PROFILE_SOURCE
        out_path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")


def phrasing_args(clone: Path, phrasing: str, lock: modules.Modules | None = None) -> tuple[list[str], str | None]:
    """Return the `--phrasing` argv for `live` or `template` and a note when the pin cannot do `live`."""
    argv = _ANALYSE_ARGV
    if phrasing == "live":
        text = probe.help_text(5, argv, clone, lock)
        if "muse-spark" in text and probe.mentions(text, "--live"):
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
    lang: str | None = None,
    expected_video: Path | str | None = None,
    follower_video: Path | str | None = None,
    private: bool | None = None,
) -> tuple[runner.Step, Path, str, list[str]]:
    """Run Part 5 `analyse` (exits 0 and 3 write a file) and return `(step, analysis, status_code, notes)`.

    Scoring path for `mode` (TICKET-094): Part 5's own `--profile <mode>` when its analyse help offers it; else
    the plain CLI, with a note for dance and rehab. The log line `part 5 scoring: ...` in the job's
    `steps/part7.log` says which path ran.
    `--replay <work>/replay.json` is passed when the pin offers it; the notes name what the pin lacks.
    `expected_visibility` (the trainer's `skeleton.json`) becomes `--expected-visibility` when the pin has the
    flag; Part 5 then refuses a take whose visible body cannot be scored (`not_enough_visible`,
    `moving_part_out_of_frame`).
    `lang` (not English) becomes `--lang`; `expected_video` and `follower_video` with live phrasing become
    `--expected-video`/`--follower-video` (a second opinion). Each is passed only when the pin offers the flag, and
    the notes name what it lacks. `private` (private_mode.py; None leaves it to `SIMON7_PRIVATE`, False wins over the
    env) never sends video and builds the phrasing flags from the plan `gpu_turn` yields.
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

    if lang and lang != "en":
        if probe.has_flag(5, _ANALYSE_ARGV, clone, "--lang", lk):
            extra += ["--lang", lang]
        else:
            notes.append("Part 5 at this pin writes English only")
    if expected_video is not None and follower_video is not None and phrasing == "live" and not private_mode.enabled(job_flag=private):
        if (probe.has_flag(5, _ANALYSE_ARGV, clone, "--expected-video", lk)
                and probe.has_flag(5, _ANALYSE_ARGV, clone, "--follower-video", lk)):
            extra += ["--expected-video", str(Path(expected_video).resolve()),
                      "--follower-video", str(Path(follower_video).resolve())]
            if "--live" not in extra and probe.has_flag(5, _ANALYSE_ARGV, clone, "--live", lk):
                extra.append("--live")
        else:
            notes.append("Part 5 at this pin gives no second opinion")

    # TICKET-094: Part 5's own `--profile` scores the mode; no mode passes nothing, and Part 5 reports "fitness".
    # Part 7 never patches Part 5 (ADR-0002): a Part 5 without the flag gets the plain CLI and a note.
    scored_by, tag_profile = "standard rules", False
    if mode is not None:
        if probe.has_flag(5, _ANALYSE_ARGV, clone, "--profile", lk):
            extra += ["--profile", mode]
            scored_by = f"Part 5 --profile {mode}"
        elif mode == "fitness":
            tag_profile = True  # Part 5's standard rule set, named so the result says what scored it
        else:
            notes.append(NOTE_UNAVAILABLE.format(mode=mode))
    applog.log(f"part 5 scoring: {scored_by}", applog.job_id_of(work_p), work_p)

    inputs = ["--expected", str(Path(expected).resolve()), "--follower", str(Path(follower).resolve())]

    def call(head: list[str], out: Path, args: list[str], log: str, env: dict[str, str]) -> runner.Step:
        return runner.run(
            5, [*head, *inputs, "--out", str(out.resolve()), *args], cwd=clone,
            env_extra={**env, "PART5_PHRASING_CONCURRENCY": PHRASING_CONCURRENCY},  # harmless where the pin ignores it
            timeout_s=config.TIMEOUTS["5"], log_path=work_p / "steps" / log, lock=lk)

    # Private mode (private-mode.md): the Part 5 call is built from the plan gpu_turn yields; inactive plans pass through.
    planned = private_mode.plan(job_flag=private, part5_clone=clone)
    with private_mode.gpu_turn(planned, work_p) as pm:
        if pm.note:
            notes.append(pm.note)
        args = list(extra)
        if pm.argv:
            i = args.index("--phrasing") if "--phrasing" in args else None
            if i is not None:
                del args[i:i + 2]
            args = [a for a in args if a != "--live"]  # the plan names the phrasing backend; no hosted call rides along
            args = _without_videos(args)  # private mode never sends video, whatever the caller passed
            args += pm.argv
        step = call(_ANALYSE_ARGV, out_path, args, "part5_analyse.log", pm.env)

    status_code = "error"
    if step["exit"] in (0, 3) and out_path.is_file():
        try:
            if tag_profile and mode is not None:
                _add_profile(out_path, mode)
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


def accepts_expected(data: bytes, tmp_root: Path | str, lock: modules.Modules | None = None) -> bool:
    """True when Part 5's doctor accepts `data` as an expected clip (a skeleton-only entry, or a student's own reference take).
    One scratch folder under `tmp_root`, removed afterwards."""
    scratch = Path(tmp_root) / uuid.uuid4().hex[:12]
    scratch.mkdir(parents=True)
    try:
        (scratch / "expected.json").write_bytes(data)
        return doctor(scratch / "expected.json", scratch, consumer="part5", lock=lock)["exit"] == 0
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
