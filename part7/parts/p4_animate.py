"""Part 4 adapter: 30 fps keyframe animation and contract validation (TICKET-010)."""

from __future__ import annotations

from pathlib import Path
import shutil

from part7 import config, modules, runner


def _mod_name(clone: Path) -> str:
    src = clone / "src"
    if src.is_dir():
        for child in sorted(src.iterdir()):
            if child.is_dir() and (child / "__init__.py").is_file():
                return child.name
    return "_".join(("simon", "anim"))


def validate(
    kind: str,
    path: Path | str,
    work: Path | str,
    lock: modules.Modules | None = None,
    state: Path | str | None = None,
) -> runner.Step:
    """Run Part 4's `contract validate <kind> <path>` check."""
    lk = lock or modules.load()
    clone = lk.path("4")
    mod = _mod_name(clone)
    work_p = Path(work)
    return runner.run(
        4,
        [
            "python3",
            "-m",
            f"{mod}.contract",
            "validate",
            kind,
            str(Path(path).resolve()),
        ],
        cwd=clone,
        env_extra={"PYTHONPATH": str(clone / "src")},
        timeout_s=config.TIMEOUTS["doctor"],
        log_path=work_p / "steps" / f"part4_validate_{kind}.log",
        lock=lk,
    )


def run(
    skeleton: Path | str,
    keyframes_v1: Path | str,
    work: Path | str,
    lock: modules.Modules | None = None,
    state: Path | str | None = None,
) -> tuple[runner.Step, Path]:
    """Copy `skeleton.json` and `keyframes.json` into `<work>/part4/` and run Part 4 `animate`."""
    lk = lock or modules.load()
    clone = lk.path("4")
    mod = _mod_name(clone)
    work_p = Path(work)
    dir4 = work_p / "part4"
    dir4.mkdir(parents=True, exist_ok=True)

    skel_dst = dir4 / "skeleton.json"
    kf_dst = dir4 / "keyframes.json"
    if Path(skeleton).resolve() != skel_dst.resolve():
        shutil.copyfile(skeleton, skel_dst)
    if Path(keyframes_v1).resolve() != kf_dst.resolve():
        shutil.copyfile(keyframes_v1, kf_dst)

    out_path = dir4 / "animation.json"
    step = runner.run(
        4,
        [
            "python3",
            "-m",
            f"{mod}.animate",
            "--in",
            str(dir4.resolve()),
            "--out",
            str(out_path.resolve()),
        ],
        cwd=clone,
        env_extra={"PYTHONPATH": str(clone / "src")},
        timeout_s=config.TIMEOUTS["4"],
        log_path=work_p / "steps" / "part4_animate.log",
        lock=lk,
    )
    return (step, out_path)


def doctor(
    path: Path | str,
    work: Path | str,
    kind: str = "animation",
    lock: modules.Modules | None = None,
    state: Path | str | None = None,
) -> runner.Step:
    """Validate an output or input file against Part 4's contract."""
    return validate(kind, path, work, lock=lock, state=state)
