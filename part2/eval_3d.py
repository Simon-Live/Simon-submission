"""The CPU backend's 3D bar (Muse on #46, adopted unchanged in ADR-0002): agreement with the GPU reference
and bone-length stability on the single fixture. It gates only the CPU backend (`make check-2-cpu`) and is
never part of the README definition of done.

Spec: docs/specs/backends-gpu-cpu.md ("3D bar", AC-B09), docs/specs/check-2.md ("CPU 3D bar", AC-K07).

evaluate(cpu_pose3d, ref_pose3d) -> {pass, mean_m, p95_m, worst_joint, bone_cv_mean, bone_cv_max, frames, ...}
- Matched on `frame`, person id 0, both in pose3d.json's canonical frame (hip-centred per frame).
- mean_m: mean over matched frames and the 17 joints of the Euclidean distance; p95_m: 95th percentile of
  those per-joint distances; worst_joint: the joint with the largest mean distance.
- bone_cv_mean: mean over the 12 non-face bones of part2.joints.BONES of std / mean over the CPU output's
  frames; bone_cv_max beside it.
- pass: mean_m <= 0.10 and bone_cv_mean <= 0.05.
The reference is a model output (SAM 3D Body), not ground truth: the bar measures agreement with it.
block() also carries the check-2 spec names (mean_joint_distance_m, bone_length_cv_mean, bone_length_cv_max).

    python -m part2.eval_3d [--cpu pose3d.json] [--reference pose3d.json | viewer.html] [--lifter name]
exits 0 when the bar passes, 1 when it fails, 2 when an input file is missing. A `part2 demo viewer` html
works as the reference: its embedded canonical joints are read.
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np

from part2.joints import CANONICAL
from part2.lifters import bone_cv

ROOT = Path(__file__).resolve().parent.parent
MAX_MEAN_M = 0.10
MAX_BONE_CV = 0.05
PERSON = 0
CPU_DEFAULT = ROOT / "fixtures" / "output" / "scored" / "cpu-single" / "pose3d.json"
REF_DEFAULT = ROOT / "fixtures" / "output" / "scored" / "single" / "pose3d.json"
NO_CPU = "no cpu outputs; run make outputs BACKEND=cpu"
NO_REF = "no gpu reference; run make outputs BACKEND=gpu"
# The names docs/specs/check-2.md gives the bar's numbers in the cpu_backend_3d block, beside AC-B09's.
SPEC_NAMES = {"mean_joint_distance_m": "mean_m", "bone_length_cv_mean": "bone_cv_mean", "bone_length_cv_max": "bone_cv_max"}


def joints_by_frame(pose3d: dict, person=PERSON) -> dict:
    """{frame: (17, 3)} for one person id, canonical joint order."""
    out = {}
    for f in pose3d["frames"]:
        for p in f["people"]:
            if p["id"] == person:
                out[f["frame"]] = np.array([[p["joints"][j][k] for k in "xyz"] for j in CANONICAL], dtype=float)
    return out


def evaluate(cpu_pose3d: dict, ref_pose3d: dict, person=PERSON, lifter: str | None = None) -> dict:
    cpu, ref = joints_by_frame(cpu_pose3d, person), joints_by_frame(ref_pose3d, person)
    if lifter is None:
        lifter = (cpu_pose3d.get("provenance") or {}).get("lifter")
    common = sorted(set(cpu) & set(ref))
    out = {"lifter": lifter, "frames": len(common), "cpu_frames": len(cpu), "reference_frames": len(ref),
           "missing_frames": len(set(ref) - set(cpu))}
    if not common:
        return {"pass": False, **out, "status": f"no frames with person {person} in both files"}
    d = np.linalg.norm(np.stack([cpu[f] for f in common]) - np.stack([ref[f] for f in common]), axis=-1)
    cv = bone_cv(np.stack([cpu[f] for f in sorted(cpu)]))
    res = {"mean_m": _r(d.mean()), "p95_m": _r(np.percentile(d, 95)), "worst_joint": CANONICAL[int(d.mean(0).argmax())],
           "bone_cv_mean": _r(cv.mean()), "bone_cv_max": _r(cv.max())}
    ok = res["mean_m"] <= MAX_MEAN_M and res["bone_cv_mean"] <= MAX_BONE_CV
    return {"pass": bool(ok), **res, **out, "thresholds": {"mean_m": MAX_MEAN_M, "bone_cv_mean": MAX_BONE_CV}}


def load_pose3d(path) -> dict:
    """pose3d.json, or the canonical joints embedded in a `part2 demo viewer` html."""
    text = Path(path).read_text()
    if Path(path).suffix.lower() != ".html":
        return json.loads(text)
    marker = "const D = "
    if marker not in text:
        raise ValueError(f"{path}: no embedded viewer data ({marker!r})")
    data, _ = json.JSONDecoder().raw_decode(text[text.index(marker) + len(marker):])
    names = data["joints"]
    frames = [{"frame": f["frame"], "t_ms": f["t_ms"], "people": [] if f["joints"] is None else [
        {"id": data["id"], "joints": {n: {"x": x, "y": y, "z": z, "conf": 1.0} for n, (x, y, z) in zip(names, f["joints"])}}]}
        for f in data["frames"]]
    return {"frames": frames}


def block(cpu_path=CPU_DEFAULT, ref_path=REF_DEFAULT, lifter: str | None = None) -> dict:
    """The `cpu_backend_3d` block of `make check-2`; `status` names a missing input."""
    cpu_path, ref_path = Path(cpu_path), Path(ref_path)
    if not cpu_path.is_file():
        return {"pass": False, "status": NO_CPU, "reference": _rel(ref_path)}
    if not ref_path.is_file():
        return {"pass": False, "status": NO_REF, "reference": _rel(ref_path)}
    cpu = load_pose3d(cpu_path)
    if lifter is None and not (cpu.get("provenance") or {}).get("lifter"):
        stamp = cpu_path.parent / "stamp.json"
        lifter = json.loads(stamp.read_text()).get("lifter") if stamp.is_file() else None
    res = evaluate(cpu, load_pose3d(ref_path), lifter=lifter)
    named = {k: res[v] for k, v in SPEC_NAMES.items() if v in res}
    return {**res, **named, "cpu": _rel(cpu_path), "reference": _rel(ref_path)}


def exit_code(result: dict) -> int:
    """0 pass, 1 fail, 2 an input file missing (make check-2-cpu)."""
    if result.get("status") in (NO_CPU, NO_REF):
        return 2
    return 0 if result.get("pass") is True else 1


def _rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def _r(x) -> float:
    return round(float(x), 4)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m part2.eval_3d", description="The CPU backend's 3D bar.")
    ap.add_argument("--cpu", type=Path, default=CPU_DEFAULT, help="CPU backend pose3d.json")
    ap.add_argument("--reference", type=Path, default=REF_DEFAULT, help="GPU pose3d.json or a part2 demo viewer html")
    ap.add_argument("--lifter", help="lifter name to report when the CPU file does not carry provenance")
    a = ap.parse_args(argv)
    try:
        result = block(a.cpu, a.reference, a.lifter)
    except (ValueError, KeyError, TypeError) as e:
        result = {"pass": False, "status": f"error: {type(e).__name__}: {e}"}
    print(json.dumps(result, indent=2))
    return exit_code(result)


if __name__ == "__main__":
    sys.exit(main())
