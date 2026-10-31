"""Documented setup and contract/doctor checks for Parts 1 to 6 in their modules (TICKET-011, ADR-0007)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
from typing import Any

from part7 import config, modules, runner
from part7.parts import p4_animate

SETUP_TIMEOUT_S = 600.0
GPU_CHECK_TIMEOUT_S = 180.0
# Prints the torch build and device; exits 3 when CUDA is not usable from the venv.
_GPU_PROBE = (
    "import sys; sys.path.insert(0, sys.argv[1]); import torch; ok = torch.cuda.is_available(); "
    "print('torch', torch.__version__, 'cuda', ok, torch.cuda.get_device_name(0) if ok else '-'); "
    "sys.exit(0 if ok else 3)"
)


def _default_setup_commands(part: str, clone: Path) -> list[list[str]]:
    if part == "1":
        return [["make", ".venv/.installed"]]  # make skips the install when requirements.txt is unchanged
    if part == "2":
        return [["uv", "sync"]]
    if part == "3":
        venv_py = clone / ".venv" / "bin" / "python"
        venv_pip = clone / ".venv" / "bin" / "pip"
        cmds: list[list[str]] = []
        if not venv_py.is_file():
            cmds.append(["python3", "-m", "venv", ".venv"])
        cmds.append([str(venv_pip), "install", "-q", "-r", "requirements.txt"])
        return cmds
    if part == "4":
        return []
    if part == "5":
        return [["uv", "sync"]]
    if part == "6":
        return []
    return []


def _default_doctor_command(part: str, clone: Path) -> tuple[list[str], dict[str, str] | None, str]:
    if part == "1":
        py = clone / ".venv" / "bin" / "python"
        return (
            [str(py), "-m", "unittest", "keyframe_finder.schema_test"],
            None,
            "keyframe_finder.schema_test",
        )
    if part == "2":
        return (
            ["uv", "run", "part2", "run", "--help"],
            None,
            "part2 run --backend",
        )
    if part == "3":
        py = clone / ".venv" / "bin" / "python"
        return (
            [str(py), "-m", "part3", "contract", "--json"],
            None,
            "part3 contract",
        )
    if part == "4":
        mod = p4_animate._mod_name(clone)
        fixture = clone / "fixtures" / "output" / "exercise" / "animation.json"
        return (
            ["python3", "-m", f"{mod}.contract", "validate", "animation", str(fixture)],
            {"PYTHONPATH": str(clone / "src")},
            f"{mod}.contract validate",
        )
    if part == "5":
        return (
            ["uv", "run", "python", "-m", "part5", "contract"],
            None,
            "part5 contract",
        )
    if part == "6":
        return (
            ["python3", "-m", "part6", "contract"],
            None,
            "part6 contract",
        )
    return (["true"], None, "true")


def _contract_version_is_1(stdout: str) -> bool:
    """Part 6's `contract` prints a JSON document whose `contract_version` must be 1."""
    try:
        doc = json.loads(stdout)
    except json.JSONDecodeError:
        return False
    return isinstance(doc, dict) and doc.get("contract_version") == 1


def _gpu_venv_check(clone: Path) -> tuple[list[str], dict[str, str], str] | None:
    """Read-only probe of Part 2's shared GPU venv (ASM-012); None when the venv does not exist."""
    gpu_py = config.part2_gpu_venv_path() / "bin" / "python"
    if not gpu_py.is_file():
        return None
    return (
        [str(gpu_py), "-c", _GPU_PROBE, str(clone)],
        {"PYTHONPATH": str(clone)},
        "part2 gpu venv: torch sees CUDA",
    )


def _setup_checks(part: str, clone: Path) -> list[tuple[list[str], dict[str, str] | None, str]]:
    """Checks that follow a part's setup commands: Parts 4 and 6 have no setup, Part 2 has the GPU venv."""
    if part in ("4", "6"):
        return [_default_doctor_command(part, clone)]
    if part == "2":
        probe = _gpu_venv_check(clone)
        return [probe] if probe is not None else []
    return []


def _stamp(part: str, sha12: str, state: Path | str | None, clone: Path | None = None) -> Path:
    """The marker that setup ran for `part` at `sha12` in the checkout `clone`.

    Venvs live inside each module checkout, so a second checkout (a worktree, the staging checkout) at the
    same sha still needs its own setup: the marker names the checkout by a hash of its resolved path.
    """
    where = "" if clone is None else "-" + hashlib.sha256(str(Path(clone).resolve()).encode()).hexdigest()[:10]
    return config.state_root(state) / "setup" / f"part-{part}-{sha12}{where}.ok"


def _module_state(lk: modules.Modules, part: str) -> tuple[Path, str, str | None]:
    """`(module dir, sha12 or "unknown", error)`; the error names the part when the module is unusable."""
    clone = lk.path(part)
    try:
        sha12 = lk.sha12(part)
    except modules.ModuleError:
        return clone, "unknown", f"part {part}: module missing at {clone} (run make parts)"
    if not clone.is_dir():
        return clone, sha12, f"part {part}: module missing at {clone} (run make parts)"
    return clone, sha12, None


def setup_all(
    lock: modules.Modules | None = None,
    state: Path | str | None = None,
    commands: dict[str, list[list[str]]] | None = None,
    only: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Run each part's documented setup commands in its module, then its checks; a part whose setup ran for its current sha is skipped.

    `commands` replaces the setup commands of the parts it names and turns the default checks off
    (tests use it with stub commands). `only` limits the run to the parts it names. Each part's result carries `duration_s`, the sum of its steps.
    """
    lk = lock or modules.load()
    log_dir = config.state_root(state) / "logs" / "setup"
    log_dir.mkdir(parents=True, exist_ok=True)

    results: dict[str, Any] = {}
    all_ok = True

    for part in (only or modules.PART_IDS):
        clone, sha12, missing = _module_state(lk, part)
        if missing:
            all_ok = False
            results[part] = {"ok": False, "commit": sha12, "steps": [], "duration_s": 0.0, "error": missing}
            continue
        stamp = _stamp(part, sha12, state, clone)
        if stamp.is_file():
            results[part] = {"ok": True, "commit": sha12, "steps": [], "duration_s": 0.0, "error": None,
                             "skipped": True, "notes": [f"setup already ran for {sha12}"]}
            continue

        part_cmds = (
            commands[part]
            if (commands is not None and part in commands)
            else _default_setup_commands(part, clone)
        )
        checks = _setup_checks(part, clone) if commands is None else []
        steps: list[runner.Step] = []
        part_ok = True
        err_msg: str | None = None
        notes: list[str] = []

        for idx, cmd in enumerate(part_cmds):
            step = runner.run(
                part,
                cmd,
                cwd=clone,
                timeout_s=SETUP_TIMEOUT_S,
                log_path=log_dir / f"part{part}-setup-{idx}.log",
                lock=lk,
            )
            steps.append(step)
            if step["exit"] != 0:
                part_ok = False
                err_msg = f"part {part}: setup command {' '.join(cmd)} failed at {sha12}"
                break

        if part_ok:
            for idx, (argv, env_extra, label) in enumerate(checks):
                step = runner.run(
                    part,
                    argv,
                    cwd=clone,
                    env_extra=env_extra,
                    timeout_s=GPU_CHECK_TIMEOUT_S,
                    log_path=log_dir / f"part{part}-check-{idx}.log",
                    lock=lk,
                )
                steps.append(step)
                check_ok = step["exit"] == 0
                if check_ok and part == "6":
                    check_ok = _contract_version_is_1(step.stdout)
                if not check_ok:
                    part_ok = False
                    err_msg = f"part {part}: check {label} failed at {sha12}"
                    break

        if part == "2" and commands is None and part_ok and not checks:
            notes.append("gpu venv not found: Part 2 runs with --backend cpu or through its uv environment")

        if not part_ok:
            all_ok = False
        else:
            stamp.parent.mkdir(parents=True, exist_ok=True)
            stamp.write_text(sha12 + "\n", encoding="utf-8")
        results[part] = {
            "ok": part_ok,
            "commit": sha12,
            "steps": steps,
            "duration_s": round(sum(float(s["duration_s"]) for s in steps), 4),
            "error": err_msg,
            "notes": notes,
        }

    return {"ok": all_ok, "parts": results}


def doctor_parts(
    lock: modules.Modules | None = None,
    state: Path | str | None = None,
    commands: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """Verify each part's contract or help command in its module."""
    lk = lock or modules.load()
    log_dir = config.state_root(state) / "logs" / "doctor-parts"
    log_dir.mkdir(parents=True, exist_ok=True)

    results: dict[str, Any] = {}
    all_ok = True

    for part in modules.PART_IDS:
        clone, sha12, _missing = _module_state(lk, part)
        default_cmd, env_extra, label = _default_doctor_command(part, clone)
        if commands is not None and part in commands:
            cmd = commands[part]
            env_extra = None
            label = " ".join(cmd)
        else:
            cmd = default_cmd

        if not clone.is_dir():
            all_ok = False
            results[part] = {
                "ok": False,
                "commit": sha12,
                "step": None,
                "error": f"part {part}: {label} not found at {sha12}",
            }
            continue

        exe_path = Path(cmd[0])
        if exe_path.is_absolute() and not exe_path.exists():
            all_ok = False
            results[part] = {
                "ok": False,
                "commit": sha12,
                "step": None,
                "error": f"part {part}: {label} not found at {sha12}",
            }
            continue

        try:
            step = runner.run(
                part,
                cmd,
                cwd=clone,
                env_extra=env_extra,
                timeout_s=config.TIMEOUTS["doctor"],
                log_path=log_dir / f"part{part}-doctor.log",
                lock=lk,
            )
        except OSError:
            all_ok = False
            results[part] = {
                "ok": False,
                "commit": sha12,
                "step": None,
                "error": f"part {part}: {label} not found at {sha12}",
            }
            continue

        stdout = step.get("stdout", "")
        part_ok = step["exit"] == 0
        if part_ok and commands is None:
            if part == "2" and "--backend" not in stdout:
                part_ok = False
            elif part == "6" and not _contract_version_is_1(stdout):
                part_ok = False

        err_msg = None if part_ok else f"part {part}: {label} not found at {sha12}"
        if not part_ok:
            all_ok = False

        results[part] = {
            "ok": part_ok,
            "commit": sha12,
            "step": step,
            "error": err_msg,
        }

    return {"ok": all_ok, "parts": results}


def cli_setup_parts(
    lock: modules.Modules | None = None,
    state: Path | str | None = None,
) -> int:
    """CLI entry point for `part7 setup-parts`."""
    try:
        res = setup_all(lock=lock, state=state)
    except Exception as exc:
        print(f"setup-parts: {exc}", file=sys.stderr)
        return 1
    for p_info in res["parts"].values():
        if p_info.get("error"):
            print(p_info["error"], file=sys.stderr)
    print(json.dumps(res, indent=2))
    return 0 if res["ok"] else 1


def cli_doctor_parts(
    lock: modules.Modules | None = None,
    state: Path | str | None = None,
) -> int:
    """CLI entry point for `part7 doctor-parts`."""
    try:
        res = doctor_parts(lock=lock, state=state)
    except Exception as exc:
        print(f"doctor-parts: {exc}", file=sys.stderr)
        return 1
    for p_info in res["parts"].values():
        if p_info.get("error"):
            print(p_info["error"], file=sys.stderr)
    print(json.dumps(res, indent=2))
    return 0 if res["ok"] else 1
