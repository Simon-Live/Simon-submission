"""MHR synthetic body bench, evaluation half (TICKET-278): SAM 3D Body against known 3D joints, score spread, fault recall.

Spec: docs/specs/mhr-bench.md. Stdlib only. Reads `bench/bodies/manifest.json` (written by the render lane) and each
render's Part 2 `pose3d.json` and Part 5 `analysis.json`; writes `bench/results/<date>/mhr-bench.json`.

    python -m part7.mhr_bench [--root D] [--manifest P] [--jobs-root D] [--out FILE | --results-dir D] [--date YYYY-MM-DD]

Exit 0 when the report is written (flags do not fail the run), 2 when an input is missing or malformed.
Every number is from synthetic renders; the report says so.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import statistics
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST_SCHEMA = "simon.bench.bodies/1"
GT_SCHEMA = "simon.bench.gt_joints/1"
ANGLES = ("front", "45", "side")
CONDITIONS = ("clean", "knee15")
SCORE_OUTLIER_POINTS = 10.0
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
# MHR70 keypoint name -> index in SAM 3D Body's 70 keypoints (part2/joints.py). The Part 2 canonical joint has the same name.
MHR70_INDEX = {
    "left_shoulder": 5, "right_shoulder": 6, "left_elbow": 7, "right_elbow": 8, "left_wrist": 62, "right_wrist": 41,
    "left_hip": 9, "right_hip": 10, "left_knee": 11, "right_knee": 12, "left_ankle": 13, "right_ankle": 14,
}
COMPARED = tuple(MHR70_INDEX)
DOMAIN_GAP_NOTE = (
    "Synthetic MHR renders with textured skin and a plain background, not recordings of people. The ground truth is "
    "MHR's own joints, the body family SAM 3D Body regresses, so agreement may be flattered; the render-to-photo domain "
    "gap may also raise error. These numbers do not transfer to real video unchanged."
)


class BenchError(ValueError):
    """An input that cannot be scored. The message names the file or render."""


# ---------------------------------------------------------------- geometry (pure Python, 3-vectors as tuples)

def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _norm(a):
    return math.sqrt(_dot(a, a))


def _unit(a, what: str):
    n = _norm(a)
    if n < 1e-9:
        raise BenchError(f"{what}: degenerate, cannot build the canonical frame")
    return (a[0] / n, a[1] / n, a[2] / n)


def canonicalize(joints: dict[str, tuple], up=(0.0, 1.0, 0.0), what: str = "pose") -> dict[str, tuple]:
    """Hip-centred frame of part2/canonical.py: origin hip midpoint, y up, x right hip to left hip made level, z = x cross y."""
    lh, rh = joints["left_hip"], joints["right_hip"]
    origin = tuple((a + b) / 2 for a, b in zip(lh, rh))
    y = _unit(up, what)
    x = _sub(lh, rh)
    d = _dot(x, y)
    x = _unit((x[0] - d * y[0], x[1] - d * y[1], x[2] - d * y[2]), f"{what} hip line")
    z = _cross(x, y)
    return {n: (_dot(_sub(p, origin), x), _dot(_sub(p, origin), y), _dot(_sub(p, origin), z)) for n, p in joints.items()}


def mpjpe(pred: list[tuple], gt: list[tuple]) -> float:
    """Mean Euclidean distance between paired points."""
    return sum(_norm(_sub(p, g)) for p, g in zip(pred, gt)) / len(gt)


def _jacobi_eigh4(a: list[list[float]]) -> tuple[list[float], list[list[float]]]:
    """Eigenvalues and eigenvectors (columns of v) of a symmetric 4x4 by Jacobi rotations."""
    n = 4
    a = [row[:] for row in a]
    v = [[1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]
    for _ in range(100):
        off = sum(a[i][j] ** 2 for i in range(n) for j in range(i + 1, n))
        if off < 1e-24:
            break
        for p in range(n - 1):
            for q in range(p + 1, n):
                if abs(a[p][q]) < 1e-30:
                    continue
                theta = (a[q][q] - a[p][p]) / (2 * a[p][q])
                t = (1.0 if theta >= 0 else -1.0) / (abs(theta) + math.sqrt(theta * theta + 1))
                c = 1 / math.sqrt(t * t + 1)
                s = t * c
                for k in range(n):
                    akp, akq = a[k][p], a[k][q]
                    a[k][p], a[k][q] = c * akp - s * akq, s * akp + c * akq
                for k in range(n):
                    apk, aqk = a[p][k], a[q][k]
                    a[p][k], a[q][k] = c * apk - s * aqk, s * apk + c * aqk
                for k in range(n):
                    vkp, vkq = v[k][p], v[k][q]
                    v[k][p], v[k][q] = c * vkp - s * vkq, s * vkp + c * vkq
    return [a[i][i] for i in range(n)], v


def _quat_to_matrix(q) -> list[list[float]]:
    w, x, y, z = q
    return [[1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
            [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
            [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)]]


def procrustes_align(pred: list[tuple], gt: list[tuple]) -> list[tuple]:
    """`pred` mapped onto `gt` by the best similarity transform: rotation (proper, never a reflection; Horn's
    quaternion method), uniform scale and translation."""
    n = len(pred)
    cp = tuple(sum(p[i] for p in pred) / n for i in range(3))
    cg = tuple(sum(g[i] for g in gt) / n for i in range(3))
    P = [_sub(p, cp) for p in pred]
    G = [_sub(g, cg) for g in gt]
    S = [[sum(P[k][i] * G[k][j] for k in range(n)) for j in range(3)] for i in range(3)]
    sxx, sxy, sxz = S[0]
    syx, syy, syz = S[1]
    szx, szy, szz = S[2]
    N = [[sxx + syy + szz, syz - szy, szx - sxz, sxy - syx],
         [syz - szy, sxx - syy - szz, sxy + syx, szx + sxz],
         [szx - sxz, sxy + syx, -sxx + syy - szz, syz + szy],
         [sxy - syx, szx + sxz, syz + szy, -sxx - syy + szz]]
    vals, vecs = _jacobi_eigh4(N)
    best = max(range(4), key=lambda i: vals[i])
    q = [vecs[r][best] for r in range(4)]
    qn = math.sqrt(sum(c * c for c in q))
    R = _quat_to_matrix([c / qn for c in q])
    RP = [tuple(sum(R[i][j] * p[j] for j in range(3)) for i in range(3)) for p in P]
    denom = sum(_dot(p, p) for p in P)
    scale = sum(_dot(r, g) for r, g in zip(RP, G)) / denom if denom > 1e-12 else 1.0
    return [(scale * r[0] + cg[0], scale * r[1] + cg[1], scale * r[2] + cg[2]) for r in RP]


def pa_mpjpe(pred: list[tuple], gt: list[tuple]) -> float:
    return mpjpe(procrustes_align(pred, gt), gt)


# ---------------------------------------------------------------- inputs

def _read_json(path: Path, what: str):
    try:
        return json.loads(Path(path).read_text())
    except FileNotFoundError:
        raise BenchError(f"{what}: {path} not found") from None
    except json.JSONDecodeError as e:
        raise BenchError(f"{what}: {Path(path).name} is not valid JSON ({e.msg})") from None


def validate_manifest(doc: dict) -> dict:
    def need(cond: bool, msg: str) -> None:
        if not cond:
            raise BenchError(f"manifest: {msg}")

    need(isinstance(doc, dict) and doc.get("schema") == MANIFEST_SCHEMA, f"schema must be {MANIFEST_SCHEMA!r}")
    need(doc.get("synthetic") is True, "synthetic must be true (these are renders, never real recordings)")
    renders = doc.get("renders")
    need(isinstance(renders, list) and renders, "renders must be a non-empty list")
    seen_ids, seen_keys = set(), set()
    for i, r in enumerate(renders):
        need(isinstance(r, dict), f"renders[{i}] must be an object")
        rid = r.get("render_id")
        need(isinstance(rid, str) and rid, f"renders[{i}].render_id must be a non-empty string")
        for key in ("shape_id", "gt_joints", "job_id"):
            need(isinstance(r.get(key), str) and r[key], f"{rid}: {key} must be a non-empty string")
        need(r.get("angle") in ANGLES, f"{rid}: angle must be one of {', '.join(ANGLES)}")
        need(r.get("condition") in CONDITIONS, f"{rid}: condition must be one of {', '.join(CONDITIONS)}")
        key = (r["shape_id"], r["angle"], r["condition"])
        need(rid not in seen_ids, f"{rid}: duplicate render_id")
        need(key not in seen_keys, f"{rid}: duplicate (shape_id, angle, condition) {key}")
        seen_ids.add(rid)
        seen_keys.add(key)
        shas = r.get("frames_sha256")
        need(isinstance(shas, list) and shas and all(isinstance(s, str) and SHA_RE.match(s) for s in shas),
             f"{rid}: frames_sha256 must be a non-empty list of 64 hex sha256")
        pf = r.get("planted_fault")
        if r["condition"] == "knee15":
            need(isinstance(pf, dict), f"{rid}: a knee15 render needs planted_fault")
            win = pf.get("window_s")
            need(isinstance(pf.get("measure"), str) and pf["measure"] and pf.get("side") in ("left", "right")
                 and isinstance(win, list) and len(win) == 2 and all(isinstance(t, (int, float)) for t in win)
                 and 0 <= win[0] <= win[1], f"{rid}: planted_fault needs measure, side and window_s [t0, t1]")
        else:
            need(pf is None, f"{rid}: a clean render must have planted_fault null")
    return doc


def load_gt(path: Path, render_id: str) -> dict[int, dict[str, tuple]]:
    """{frame: {mhr70 name: (x, y, z) in mm}} for the compared joints, or BenchError naming the render."""
    doc = _read_json(path, f"{render_id} gt_joints")
    if not isinstance(doc, dict) or doc.get("schema") != GT_SCHEMA or doc.get("unit") != "mm" or doc.get("up_axis") != "y":
        raise BenchError(f"{render_id}: gt_joints must have schema {GT_SCHEMA!r}, unit 'mm' and up_axis 'y'")
    out: dict[int, dict[str, tuple]] = {}
    for fr in doc.get("frames") or []:
        joints = fr.get("joints") or {}
        missing = [j for j in COMPARED if j not in joints]
        if missing:
            raise BenchError(f"{render_id}: gt frame {fr.get('frame')} lacks joints {', '.join(missing)}")
        out[int(fr["frame"])] = {j: tuple(float(c) for c in joints[j]) for j in COMPARED}
    if not out:
        raise BenchError(f"{render_id}: gt_joints holds no frames")
    return out


def load_pose(path: Path, render_id: str, person: int = 0) -> dict[int, dict[str, tuple]]:
    """{frame: {joint: (x, y, z) in mm}} from Part 2's pose3d.json (metres), person id `person`."""
    doc = _read_json(path, f"{render_id} pose3d")
    out: dict[int, dict[str, tuple]] = {}
    for fr in doc.get("frames") or []:
        for p in fr.get("people") or []:
            if p.get("id") == person:
                try:
                    out[int(fr["frame"])] = {j: tuple(1000.0 * float(p["joints"][j][k]) for k in "xyz") for j in COMPARED}
                except KeyError as e:
                    raise BenchError(f"{render_id}: pose3d frame {fr.get('frame')} lacks joint {e}") from None
    return out


def render_errors(pose: dict, gt: dict, render_id: str) -> tuple[float, float]:
    """(MPJPE, PA-MPJPE) in mm over the frames both hold, each frame in its own hip-centred canonical frame."""
    frames = sorted(set(pose) & set(gt))
    if not frames:
        raise BenchError(f"{render_id}: pose3d and gt_joints share no frame")
    m, pa = [], []
    for f in frames:
        p, g = canonicalize(pose[f], what=f"{render_id} pose frame {f}"), canonicalize(gt[f], what=f"{render_id} gt frame {f}")
        pv, gv = [p[j] for j in COMPARED], [g[j] for j in COMPARED]
        m.append(mpjpe(pv, gv))
        pa.append(pa_mpjpe(pv, gv))
    return sum(m) / len(m), sum(pa) / len(pa)


def fault_found(analysis: dict, planted: dict) -> bool:
    """A Part 5 fault of the planted measure and side whose time lies inside the planted window."""
    t0, t1 = planted["window_s"]
    for f in analysis.get("faults") or []:
        if f.get("measure") != planted["measure"] or f.get("side") != planted["side"]:
            continue
        at = f.get("at_s")
        if at is None and f.get("follower_t_s"):
            at = f["follower_t_s"][0]
        if isinstance(at, (int, float)) and t0 <= at <= t1:
            return True
    return False


# ---------------------------------------------------------------- aggregation

def _flags(rows: list[dict]) -> list[dict]:
    flags = [{"kind": "missed_fault", "shape_id": r["shape_id"], "angle": r["angle"],
              "detail": "the 15 degree knee fault was planted and Part 5 did not report it inside the planted window"}
             for r in rows if r["fault_planted"] and not r["fault_found"]]
    clean = body_clean_scores(rows)
    if clean:
        med = statistics.median(clean.values())
        for shape, s in sorted(clean.items()):
            if abs(s - med) > SCORE_OUTLIER_POINTS:
                flags.append({"kind": "score_outlier", "shape_id": shape, "angle": None,
                              "detail": f"clean score {s:.1f} is {abs(s - med):.1f} points from the median {med:.1f}"})
    return flags


def body_clean_scores(rows: list[dict]) -> dict[str, float]:
    """Mean clean score per shape over its angles."""
    by: dict[str, list[float]] = {}
    for r in rows:
        if r["condition"] == "clean":
            by.setdefault(r["shape_id"], []).append(r["score"])
    return {s: sum(v) / len(v) for s, v in by.items()}


def summarize(rows: list[dict]) -> dict:
    clean = body_clean_scores(rows)
    if not clean:
        raise BenchError("no clean render: the score spread needs at least one")
    planted = [r for r in rows if r["fault_planted"]]
    if not planted:
        raise BenchError("no knee15 render: fault recall needs at least one planted fault")
    return {"score_spread": round(max(clean.values()) - min(clean.values()), 2),
            "fault_recall": round(sum(r["fault_found"] for r in planted) / len(planted), 4), "n": len(rows)}


def run(manifest_path: Path, jobs_root: Path, repo_root: Path = ROOT, command: str = "") -> dict:
    raw = Path(manifest_path).read_bytes() if Path(manifest_path).exists() else None
    if raw is None:
        raise BenchError(f"manifest: {manifest_path} not found")
    manifest = validate_manifest(_read_json(manifest_path, "manifest"))
    rows = []
    for r in manifest["renders"]:
        rid = r["render_id"]
        work = Path(jobs_root) / r["job_id"] / "work"
        mp, pa = render_errors(load_pose(work / "part2" / "pose3d.json", rid), load_gt(repo_root / r["gt_joints"], rid), rid)
        analysis = _read_json(work / "follower" / "analysis.json", f"{rid} analysis")
        score = (analysis.get("score") or {}).get("value")
        if not isinstance(score, (int, float)) or isinstance(score, bool):
            raise BenchError(f"{rid}: analysis.json has no numeric score.value")
        planted = r["planted_fault"]
        rows.append({"shape_id": r["shape_id"], "angle": r["angle"], "condition": r["condition"],
                     "mpjpe_mm": round(mp, 2), "pa_mpjpe_mm": round(pa, 2), "score": float(score),
                     "fault_planted": planted is not None,
                     "fault_found": bool(planted and fault_found(analysis, planted))})
    return {"source_manifest_sha256": hashlib.sha256(raw).hexdigest(), "command": command, "n": len(rows),
            "per_body": rows, "summary": summarize(rows), "flags": _flags(rows), "synthetic": True,
            "domain_gap_note": DOMAIN_GAP_NOTE}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m part7.mhr_bench", description=__doc__.split("\n")[0])
    ap.add_argument("--root", default=str(ROOT), help="repo root that the other paths and gt_joints are relative to")
    ap.add_argument("--manifest", default="bench/bodies/manifest.json")
    ap.add_argument("--jobs-root", default="bench/bodies/jobs")
    ap.add_argument("--results-dir", default="bench/results")
    ap.add_argument("--out", help="write here instead of <results-dir>/<date>/mhr-bench.json")
    ap.add_argument("--date", default=None, help="results folder date, default today")
    a = ap.parse_args(argv)
    command = "python -m part7.mhr_bench --manifest {} --jobs-root {}".format(a.manifest, a.jobs_root)
    try:
        day = date.fromisoformat(a.date) if a.date else date.today()
        base = Path(a.root)
        report = run(base / a.manifest, base / a.jobs_root, base, command)
    except (BenchError, ValueError) as e:
        print(f"mhr-bench: {e}", file=sys.stderr)
        return 2
    out = Path(a.out) if a.out else base / a.results_dir / day.isoformat() / "mhr-bench.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n")
    s = report["summary"]
    print(f"mhr-bench (SYNTHETIC renders): n={s['n']} score spread {s['score_spread']} fault recall {s['fault_recall']} "
          f"flags {len(report['flags'])} -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
