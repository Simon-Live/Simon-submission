"""Part 3 adapter: skeleton consistency (`--view part4` and `--view part5`) and doctor (TICKET-010)."""

from __future__ import annotations

import contextlib
import json
from pathlib import Path
from typing import Iterator

from part7 import config, modules, runner
from part7.parts import probe

BODY = "simon-standard"  # the same body profile on both sides (journey.md "Commands")
DENSIFY = "every:10"
FLOOR_WORK = "--floor-work"  # Part 3 TICKET-040 v2: `run` only (`doctor` rejects it); off unless the entry is floor work
NOTE_FLOOR_ON = "Part 3 floor work: on"
NOTE_FLOOR_MISSING = "floor work requested, Part 3 pin lacks --floor-work"


def _person_args(person: str | int | None) -> list[str]:
    """`--person <id>` for a pose3d.json that holds several people (people.md)."""
    return [] if person is None else ["--person", str(person)]


def _mirror(pose3d: Path | str, work: Path, mirrored: bool, py_exe: str, clone: Path,
            lk: modules.Modules) -> tuple[str, list[str]]:
    """TICKET-310: the `--in` path and flip args for a take the person marked as a mirrored (selfie) video.

    Part 3's `--flip on` when its `run --help` offers it; else a copy of the pose with Part 3's top-level
    `mirrored: true` hint, which `--flip auto` (the default) reads (Part 3 ADR-0005). Not mirrored: unchanged.
    """
    pose = Path(pose3d).resolve()
    if not mirrored:
        return (str(pose), [])
    if probe.has_flag(3, [py_exe, "-m", "part3", "run"], clone, "--flip", lk):
        return (str(pose), ["--flip", "on"])
    doc = json.loads(pose.read_text(encoding="utf-8"))
    doc["mirrored"] = True
    hinted = work / "pose3d.mirrored.json"
    hinted.write_text(json.dumps(doc), encoding="utf-8")
    return (str(hinted.resolve()), [])


def _python_for(clone: Path) -> str:
    venv_py = clone / ".venv" / "bin" / "python"
    return str(venv_py) if venv_py.exists() else "python3"


def floor_work_args(floor_work: bool, lk: modules.Modules | None = None) -> tuple[list[str], str | None]:
    """`(extra run argv, job note)` for a take on an entry marked floor work; `([], None)` for any other entry.

    The flag is passed only when the pinned Part 3 lists it, so an older Part 3 still runs (the note says it did not).
    """
    if not floor_work:
        return [], None
    lock = lk or modules.load()
    clone = lock.path("3")
    if probe.has_flag(3, [_python_for(clone), "-m", "part3", "run"], clone, FLOOR_WORK, lock):
        return [FLOOR_WORK], NOTE_FLOOR_ON
    return [], NOTE_FLOOR_MISSING


@contextlib.contextmanager
def _ensure_part4_keyframes_beside(skel_path: Path) -> Iterator[None]:
    """Ensure a `simon.keyframes.v1` `keyframes.json` sits beside `skel_path` during `part3 doctor --for part4`."""
    if not skel_path.is_file():
        yield
        return

    parent = skel_path.parent
    beside = parent / "keyframes.json"
    v1_file = parent / "keyframes.v1.json"

    original_bytes: bytes | None = None
    needs_temp = False

    if beside.is_file():
        try:
            b_bytes = beside.read_bytes()
            b_doc = json.loads(b_bytes.decode("utf-8"))
            if not (isinstance(b_doc, dict) and isinstance(b_doc.get("keyframes"), list)):
                original_bytes = b_bytes
                needs_temp = True
        except Exception:
            original_bytes = beside.read_bytes()
            needs_temp = True
    else:
        needs_temp = True

    if not needs_temp:
        yield
        return

    replacement_bytes: bytes | None = None
    if v1_file.is_file():
        try:
            replacement_bytes = v1_file.read_bytes()
        except OSError:
            replacement_bytes = None

    if replacement_bytes is None:
        try:
            s_doc = json.loads(skel_path.read_text(encoding="utf-8"))
            if isinstance(s_doc, dict) and isinstance(s_doc.get("keyframes"), list):
                tl = s_doc.get("timeline") if isinstance(s_doc.get("timeline"), dict) else {}
                fps = s_doc.get("fps", tl.get("fps", 30))
                frame_count = tl.get("frame_count", s_doc.get("frame_count", 1))
                duration_s = tl.get("duration_s", s_doc.get("duration_s", (frame_count - 1) / 30.0))
                kf_list = [
                    {"index": k["index"], "t": k["t"]}
                    for k in s_doc["keyframes"]
                    if isinstance(k, dict) and "index" in k and "t" in k
                ]
                synthesized = {
                    "format": "simon.keyframes.v1",
                    "fps": fps,
                    "duration_s": duration_s,
                    "frame_count": frame_count,
                    "keyframes": kf_list,
                }
                replacement_bytes = (json.dumps(synthesized, indent=2) + "\n").encode("utf-8")
        except Exception:
            replacement_bytes = None

    if replacement_bytes is None:
        yield
        return

    try:
        beside.write_bytes(replacement_bytes)
        yield
    finally:
        if original_bytes is not None:
            beside.write_bytes(original_bytes)
        else:
            beside.unlink(missing_ok=True)


def part4(
    pose3d: Path | str,
    keyframes_or_every: Path | str,
    work: Path | str,
    lock: modules.Modules | None = None,
    state: Path | str | None = None,
    person: str | int | None = None,
    mirrored: bool = False,
    floor_args: list[str] | None = None,
) -> tuple[list[runner.Step], Path, Path, str | None]:
    """Run Part 3 `--view part4` and retry once with `every:5` on a 180-degree refusal (AC-H8)."""
    lk = lock or modules.load()
    clone = lk.path("3")
    work_p = Path(work)
    work_p.mkdir(parents=True, exist_ok=True)

    skel_path = work_p / "skeleton.json"
    kf_v1_path = work_p / "keyframes.v1.json"
    skel_str = str(skel_path.resolve())
    kf_out_str = str(kf_v1_path.resolve())

    if isinstance(keyframes_or_every, Path) or (
        not str(keyframes_or_every).startswith("every:") and Path(str(keyframes_or_every)).exists()
    ):
        kf_arg = str(Path(keyframes_or_every).resolve())
    else:
        kf_arg = str(keyframes_or_every)

    py_exe = _python_for(clone)
    pose_str, flip = _mirror(pose3d, work_p, mirrored, py_exe, clone, lk)
    densify: list[str] = []
    notes: list[str] = []
    if not kf_arg.startswith("every:"):
        if probe.has_flag(3, [py_exe, "-m", "part3", "run"], clone, "--keyframes-densify", lk):
            densify = ["--keyframes-densify", DENSIFY]
        else:
            kf_arg = DENSIFY
            notes.append("Part 3 at this pin has no densify, key frames every:10")
    argv = [
        py_exe, "-m", "part3", "run", "--in", pose_str, "--out", skel_str, "--view", "part4",
        "--keyframes", kf_arg, *densify, "--keyframes-out", kf_out_str, "--body", BODY, *_person_args(person), *flip,
        *(floor_args or []),
    ]
    step1 = runner.run(
        3,
        argv,
        cwd=clone,
        timeout_s=config.TIMEOUTS["3"],
        log_path=work_p / "steps" / "part3_part4.log",
        lock=lk,
    )
    steps = [step1]
    out_text = step1.get("stdout", "")

    if step1["exit"] == 2 and ("180" in out_text or "smaller every" in out_text):
        argv_retry = [
            py_exe,
            "-m",
            "part3",
            "run",
            "--in",
            pose_str,
            "--out",
            skel_str,
            "--view",
            "part4",
            "--keyframes",
            "every:5",
            "--keyframes-out",
            kf_out_str,
            "--body",
            BODY,
            *_person_args(person),
            *flip,
            *(floor_args or []),
        ]
        step2 = runner.run(
            3,
            argv_retry,
            cwd=clone,
            timeout_s=config.TIMEOUTS["3"],
            log_path=work_p / "steps" / "part3_part4_retry.log",
            lock=lk,
        )
        steps.append(step2)
        notes.append("retried Part 3 with every:5")

    return (steps, skel_path, kf_v1_path, "; ".join(notes) or None)


def part5(
    pose3d: Path | str,
    work: Path | str,
    lock: modules.Modules | None = None,
    state: Path | str | None = None,
    person: str | int | None = None,
    mirrored: bool = False,
    floor_args: list[str] | None = None,
) -> tuple[runner.Step, Path]:
    """Run Part 3 `--view part5 --fps 30` to produce a follower skeleton clip (`--person` picks one of several)."""
    lk = lock or modules.load()
    clone = lk.path("3")
    work_p = Path(work)
    work_p.mkdir(parents=True, exist_ok=True)
    follower_path = work_p / "follower.json"
    py_exe = _python_for(clone)
    pose_str, flip = _mirror(pose3d, work_p, mirrored, py_exe, clone, lk)

    argv = [
        py_exe,
        "-m",
        "part3",
        "run",
        "--in",
        pose_str,
        "--out",
        str(follower_path.resolve()),
        "--view",
        "part5",
        "--fps",
        "30",
        "--body",
        BODY,
        *_person_args(person),
        *flip,
        *(floor_args or []),
    ]
    step = runner.run(
        3,
        argv,
        cwd=clone,
        timeout_s=config.TIMEOUTS["3"],
        log_path=work_p / "steps" / "part3_part5.log",
        lock=lk,
    )
    return (step, follower_path)


def doctor(
    path: Path | str,
    consumer: str,
    work: Path | str,
    lock: modules.Modules | None = None,
    state: Path | str | None = None,
) -> runner.Step:
    """Run Part 3's `doctor <path> --for <consumer>` command."""
    lk = lock or modules.load()
    clone = lk.path("3")
    work_p = Path(work)
    target = Path(path).resolve()
    py_exe = _python_for(clone)
    ctx = (
        _ensure_part4_keyframes_beside(target)
        if consumer == "part4"
        else contextlib.nullcontext()
    )
    with ctx:
        return runner.run(
            3,
            [
                py_exe,
                "-m",
                "part3",
                "doctor",
                str(target),
                "--for",
                consumer,
            ],
            cwd=clone,
            timeout_s=config.TIMEOUTS["doctor"],
            log_path=work_p / "steps" / f"part3_doctor_{consumer}.log",
            lock=lk,
        )
