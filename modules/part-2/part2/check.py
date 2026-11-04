"""Done-check for Part 2 (`make check-2`): one metrics JSON, exit 0 only when the README definition of done passes.

Spec: docs/specs/check-2.md (AC-K01 to AC-K14). ADR-0004 (scoring rules read-only), ADR-0006 (scored outputs).

Scores the committed outputs under the scored dir (`fixtures/output/scored/`, or PART2_SCORED_DIR, which
`make check-2 SCORED=out` sets) against `fixtures/input/` with the unchanged evals:
  one_person               scored/single            vs input/single/labels_2d.json   (part2.eval_reproj)
  one_person_coco          scored/coco-single       vs input/coco/labels_2d.json     (TICKET-037, check_coco)
  multi_person             scored/class (api-sam31) vs input/class/gt_tracks.json    (part2.eval_tracks)
  multi_person_local_open  scored/class-local-open, same eval, reported and never gated (ADR-0003)
  cpu_backend_3d           scored/cpu-single vs scored/single (part2.eval_3d); gates only `make check-2-cpu`
Top-level `pass` = one_person and one_person_coco and multi_person. Each mode's stamp (part2.stamp) must be
v2 and fresh; a mode that is missing, stale or crashes fails with the reason and the JSON is still printed.
cpu_backend_3d scores another CPU mode dir of the scored dir when --cpu-mode or PART2_CPU_MODE names one (TICKET-044:
`cpu-sam3db-single`, `make check-2-cpu CPU_MODE=...`), and reports seconds_per_frame when that file's
provenance.timing carries it (the cpu-sam3db variant writes it; cpu-single carries none, so its block is unchanged).
It scores a CPU backend's output only: the reference `single`, or a dir whose stamp names a backend other than cpu
and cpu-sam3db, is refused with one line (exit 1), and a missing dir names the `make outputs BACKEND=` that makes it.

    python -m part2.check [--scored DIR] [--block NAME]   # NAME cpu_backend_3d: exit 0 pass, 1 fail, 2 missing
    python -m part2.check --block cpu_backend_3d --cpu-mode cpu-sam3db-single
    python -m part2.check fingerprint <mode> | stamp <mode> <fp>   # v1 interface of k8s/ and hpc/ scripts
"""
import argparse
import hashlib
import importlib
import json
import os
import sys
from pathlib import Path

from part2 import stamp

ROOT = Path(__file__).resolve().parent.parent
SCORED_ENV = "PART2_SCORED_DIR"
DEFAULT_SCORED = "fixtures/output/scored"
CPU_ENV = "PART2_CPU_MODE"
DEFAULT_CPU = "cpu-single"
CPU_BACKENDS = ("cpu", "cpu-sam3db")  # the stamp backends the 3D bar accepts as a CPU mode dir
REFERENCE_MODE = "single"  # the GPU reference every CPU dir is scored against, never a CPU mode itself
GATED = ("one_person", "one_person_coco", "multi_person")
SCORED_TRACKER = "api-sam31"
OPEN_TRACKER = "local-open"
BODY_HEIGHT = "clip max of clicked nose to ankle-midpoint distance in px (stricter than full stature)"
COCO_LABELS = "fixtures/input/coco/labels_2d.json"


def scored_dir(root: Path = ROOT, flag=None) -> Path:
    """The flag, then PART2_SCORED_DIR, then fixtures/output/scored; relative paths are under root."""
    d = Path(flag or os.environ.get(SCORED_ENV) or DEFAULT_SCORED)
    return d if d.is_absolute() else Path(root) / d


def ready(root: Path, out: Path, inputs: list[str], outputs: list[str]) -> dict | None:
    """None when the fixture inputs exist and out/ holds the outputs with a fresh v2 stamp, else
    {"status": why, "stamp": state}."""
    missing = [n for n in inputs if not (root / n).exists()]
    if missing:
        return {"status": f"missing fixture input {', '.join(missing)}", "stamp": None}
    where = stamp.rel(out, root)
    for n in outputs:
        if not (out / n).is_file():
            return {"status": stamp.MISSING.format(path=f"{where}/{n}"), "stamp": "missing"}
    return stamp.check(out, root)


def _fail(problem: dict, out: Path, root: Path, **extra) -> dict:
    return {"pass": False, **extra, "status": problem["status"], **_changed(problem),
            "outputs": stamp.describe(out, root, problem)}


def _changed(problem: dict) -> dict:
    return {"changed_files": problem["changed_files"]} if problem.get("changed_files") else {}


def check_single(root: Path = ROOT, scored: Path | None = None) -> dict:
    scored = scored or scored_dir(root)
    out = scored / "single"
    labels = "fixtures/input/single/labels_2d.json"
    problem = ready(root, out, ["fixtures/input/single/frames", labels], ["pose3d.json", "camera.json"])
    if problem:
        return _fail(problem, out, root)
    from part2 import eval_reproj

    m = eval_reproj.evaluate_files(out / "pose3d.json", out / "camera.json", root / labels)
    m.pop("per_frame")
    m["body_height"] = BODY_HEIGHT
    return {**m, "outputs": stamp.describe(out, root)}


def check_coco(root: Path = ROOT, scored: Path | None = None) -> dict:
    """`one_person_coco` (TICKET-037): scored/coco-single against fixtures/input/coco/labels_2d.json with the
    unchanged eval_reproj rules, each image its own clip, through part2.eval_coco.block (metrics with "pass",
    no per-frame rows). A missing label file or a missing or stale output fails the block with the reason."""
    scored = scored or scored_dir(root)
    out = scored / "coco-single"
    problem = ready(root, out, [COCO_LABELS], [])
    if problem:
        return _fail(problem, out, root)
    eval_coco = importlib.import_module("part2.eval_coco")  # the module in sys.modules (tests put a fake there)
    m = eval_coco.block(out, root / COCO_LABELS)
    return {**m, "outputs": stamp.describe(out, root)}


def _check_tracks(root: Path, out: Path, tracker: str, **extra) -> dict:
    gt = "fixtures/input/class/gt_tracks.json"
    problem = ready(root, out, ["fixtures/input/class/frames", gt], ["tracks.json", "pose3d.json"])
    if problem:
        return _fail(problem, out, root, **extra)
    made_by = (stamp.load(out) or {}).get("tracker")
    if made_by != tracker:
        return {"pass": False, **extra, "status": f"{stamp.rel(out, root)} was tracked by {made_by}, not {tracker}; "
                f"run make outputs", "outputs": stamp.describe(out, root)}
    try:
        from part2 import eval_tracks
    except ImportError:
        return {"pass": False, **extra, "status": "not available: part2.eval_tracks missing (#13)"}
    m = eval_tracks.evaluate_files(out / "tracks.json", root / gt, out / "pose3d.json")
    return {**m, **extra, "outputs": stamp.describe(out, root)}


def check_class(root: Path = ROOT, scored: Path | None = None) -> dict:
    return _check_tracks(root, (scored or scored_dir(root)) / "class", SCORED_TRACKER)


def check_class_local_open(root: Path = ROOT, scored: Path | None = None) -> dict:
    return _check_tracks(root, (scored or scored_dir(root)) / "class-local-open", OPEN_TRACKER, gated=False)


def cpu_mode(flag=None) -> str:
    """The CPU mode dir the bar scores: the flag, then PART2_CPU_MODE, then cpu-single. It names a dir of the
    scored dir (where the reference `single` is), never a path: ValueError for one with a separator or dots."""
    name = flag or os.environ.get(CPU_ENV) or DEFAULT_CPU
    if Path(name).name != name or name in (".", ".."):
        raise ValueError(f'{CPU_ENV} or --cpu-mode names a mode dir of the scored dir, not the path "{name}"')
    return name


def making_backend(mode: str) -> str:
    """The `make outputs BACKEND=` value that writes the CPU mode dir `mode` (cpu-sam3db for cpu-sam3db-single); `cpu`
    for any other name, a GPU mode's included."""
    from part2 import outputs  # outputs imports this module, so it is read here and not at the top

    return next((m.backend for m in outputs.MODES if m.name == mode and m.backend in CPU_BACKENDS), "cpu")


def not_a_cpu_dir(cpu: Path, root: Path) -> str | None:
    """The one-line refusal when the dir named as the CPU mode is not a CPU backend's output: the GPU reference
    `single` by name, or any dir whose stamp names a backend other than cpu and cpu-sam3db. A dir with no readable
    backend (no stamp, a v1 stamp) is left to stamp.check, which says what is wrong with it."""
    where, backend = stamp.rel(cpu, root), (stamp.load(cpu) or {}).get("backend")
    choose = " or ".join(CPU_BACKENDS)
    if cpu.name == REFERENCE_MODE:
        return f"{where} is the GPU reference (backend {backend}), not a CPU mode dir; choose a dir made by {choose}"
    if backend is not None and backend not in CPU_BACKENDS:
        return f"{where} was made by backend {backend}, not a CPU backend; choose a dir made by {choose}"
    return None


def cpu_speed(pose3d_path: Path) -> dict:
    """{"seconds_per_frame", "timing"} from the CPU file's provenance.timing (the cpu-sam3db variant writes it,
    TICKET-044), else {}: a file without it (cpu-single) keeps the block as it was."""
    timing = (json.loads(pose3d_path.read_text()).get("provenance") or {}).get("timing") or {}
    if timing.get("seconds_per_frame") is None:
        return {}
    return {"seconds_per_frame": timing["seconds_per_frame"], "timing": timing}


def check_cpu_3d(root: Path = ROOT, scored: Path | None = None, mode: str | None = None) -> dict:
    """`cpu_backend_3d`: the CPU backend's 3D bar against the GPU reference; never in the top-level pass. `mode`
    (else PART2_CPU_MODE, else cpu-single) picks the CPU dir of the scored dir (cpu_mode)."""
    from part2 import eval_3d

    scored = scored or scored_dir(root)
    cpu, ref = scored / cpu_mode(mode), scored / "single"
    if not (cpu / "pose3d.json").is_file():
        return {"pass": False, "status": eval_3d.no_cpu(making_backend(cpu.name)), "cpu": stamp.rel(cpu, root),
                "reference": stamp.rel(ref, root)}
    refused = not_a_cpu_dir(cpu, root)
    if refused:
        return {"pass": False, "status": refused, "cpu": stamp.rel(cpu, root), "reference": stamp.rel(ref, root)}
    if not (ref / "pose3d.json").is_file():
        return {"pass": False, "status": eval_3d.NO_REF, "reference": stamp.rel(ref, root)}
    problems = {d: stamp.check(d, root) for d in (cpu, ref)}
    bad = next((problems[d] for d in (cpu, ref) if problems[d]), None)
    if bad:
        return {"pass": False, "status": bad["status"], **_changed(bad), "reference": stamp.rel(ref, root),
                "outputs": stamp.describe(cpu, root, problems[cpu])}
    block = eval_3d.block(cpu / "pose3d.json", ref / "pose3d.json")
    return {**block, **cpu_speed(cpu / "pose3d.json"), "cpu": stamp.rel(cpu, root), "reference": stamp.rel(ref, root),
            "outputs": stamp.describe(cpu, root)}


BLOCKS = {"one_person": check_single, "one_person_coco": check_coco, "multi_person": check_class,
          "multi_person_local_open": check_class_local_open, "cpu_backend_3d": check_cpu_3d}


def run(root: Path = ROOT, scored=None) -> dict:
    root = Path(root)
    scored = scored_dir(root, scored)
    report = {name: _safe(fn, root, scored) for name, fn in BLOCKS.items()}
    report["pass"] = all(report[name].get("pass") is True for name in GATED)
    return report


def _safe(fn, root, scored, **kw) -> dict:
    """An eval that crashes is a failed check with the reason, never a traceback instead of JSON."""
    try:
        return fn(root, scored, **kw)
    except Exception as e:  # noqa: BLE001
        return {"pass": False, "status": f"error: {type(e).__name__}: {e}"}


def block_exit(name: str, result: dict) -> int:
    """`make check-2-cpu` and friends: 0 pass, 1 fail, 2 an input missing (cpu_backend_3d only)."""
    if name == "cpu_backend_3d":
        from part2 import eval_3d

        return eval_3d.exit_code(result)
    return 0 if result.get("pass") is True else 1


# ---- v1 interface kept for k8s/gpu_outputs.sh and hpc/hpc_outputs.sh (unchanged upstream scripts) ------
# They write out/<mode>/stamp.json as {"fingerprint": ...}; check-2 reads that as stale with the v1 message.
PIPELINE_CODE = ["part2/frames.py", "part2/joints.py", "part2/body3d.py", "part2/canonical.py", "part2/track.py",
                 "k8s/requirements-gpu.txt", "k8s/constraints-gpu.txt", "k8s/setup_env.sh"]


def fingerprint(mode: str, root: Path = ROOT) -> str:
    """v1: sha256 over the team pipeline code and the mode's frames."""
    h = hashlib.sha256()
    for name in PIPELINE_CODE:
        p = Path(root) / name
        h.update(name.encode())
        h.update(p.read_bytes() if p.exists() else b"<missing>")
    frames_dir = Path(root) / "fixtures" / "input" / mode / "frames"
    for p in sorted(frames_dir.rglob("*")) if frames_dir.exists() else []:
        if p.is_file():
            h.update(str(p.relative_to(frames_dir)).encode())
            h.update(p.read_bytes())
    return h.hexdigest()


def write_stamp(mode: str, fp: str, root: Path = ROOT) -> Path:
    path = Path(root) / "out" / mode / "stamp.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"fingerprint": fp}))
    return path


def main(argv=None, root: Path = ROOT) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv and argv[0] in ("fingerprint", "stamp"):
        print(fingerprint(argv[1], root) if argv[0] == "fingerprint" else write_stamp(argv[1], argv[2], root))
        return 0
    ap = argparse.ArgumentParser(prog="python -m part2.check", description="Part 2 done-check (make check-2).")
    ap.add_argument("--scored", help=f"scored dir (default: {SCORED_ENV}, else {DEFAULT_SCORED})")
    ap.add_argument("--block", choices=sorted(BLOCKS), help="print one block and exit by it")
    ap.add_argument("--cpu-mode", help=f"with --block cpu_backend_3d: the CPU mode dir of the scored dir "
                    f"(default: {CPU_ENV}, else {DEFAULT_CPU})")
    a = ap.parse_args(argv)
    if a.cpu_mode and a.block != "cpu_backend_3d":
        ap.error("--cpu-mode goes with --block cpu_backend_3d")
    if a.block:
        kw = {"mode": a.cpu_mode} if a.cpu_mode else {}
        result = _safe(BLOCKS[a.block], Path(root), scored_dir(root, a.scored), **kw)
        print(json.dumps(result, indent=2))
        return block_exit(a.block, result)
    report = run(root, a.scored)
    print(json.dumps(report, indent=2))
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
