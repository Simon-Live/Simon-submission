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


def _person_args(person: str | int | None) -> list[str]:
    """`--person <id>` for a pose3d.json that holds several people (people.md)."""
    return [] if person is None else ["--person", str(person)]


def _python_for(clone: Path) -> str:
    venv_py = clone / ".venv" / "bin" / "python"
    return str(venv_py) if venv_py.exists() else "python3"


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
) -> tuple[list[runner.Step], Path, Path, str | None]:
    """Run Part 3 `--view part4` and retry once with `every:5` on a 180-degree refusal (AC-H8)."""
    lk = lock or modules.load()
    clone = lk.path("3")
    work_p = Path(work)
    work_p.mkdir(parents=True, exist_ok=True)

    skel_path = work_p / "skeleton.json"
    kf_v1_path = work_p / "keyframes.v1.json"
    pose_str = str(Path(pose3d).resolve())
    skel_str = str(skel_path.resolve())
    kf_out_str = str(kf_v1_path.resolve())

    if isinstance(keyframes_or_every, Path) or (
        not str(keyframes_or_every).startswith("every:") and Path(str(keyframes_or_every)).exists()
    ):
        kf_arg = str(Path(keyframes_or_every).resolve())
    else:
        kf_arg = str(keyframes_or_every)

    py_exe = _python_for(clone)
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
        "--keyframes", kf_arg, *densify, "--keyframes-out", kf_out_str, "--body", BODY, *_person_args(person),
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
) -> tuple[runner.Step, Path]:
    """Run Part 3 `--view part5 --fps 30` to produce a follower skeleton clip (`--person` picks one of several)."""
    lk = lock or modules.load()
    clone = lk.path("3")
    work_p = Path(work)
    work_p.mkdir(parents=True, exist_ok=True)
    follower_path = work_p / "follower.json"
    py_exe = _python_for(clone)

    argv = [
        py_exe,
        "-m",
        "part3",
        "run",
        "--in",
        str(Path(pose3d).resolve()),
        "--out",
        str(follower_path.resolve()),
        "--view",
        "part5",
        "--fps",
        "30",
        "--body",
        BODY,
        *_person_args(person),
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
