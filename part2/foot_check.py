"""python -m part2.foot_check [--scored DIR] [FILE ...]: a measured, ungated check of pose3d.json's foot points (TICKET-043).

Spec: docs/specs/integration-contract.md (AC-C16). With no FILE, or with --scored, it checks the scored outputs of the
gpu backend, the one that writes foot points: every pose3d.json of those sets under the scored dir (scored_files; the
flag, then PART2_SCORED_DIR, then fixtures/output/scored, the one rule `make check-2` uses, part2.check.scored_dir),
so a file that is missing is reported as unreadable instead of left out. FILE alone checks only those files.
`make check-feet` passes --scored only for SCORED=DIR. Prints one JSON report:

  files[]: per file
    person_frames, with_all_six     person-frames, and those whose `extra_joints` holds all six points
    coverage                        with_all_six / person_frames (0.0 for a file without foot points)
    points                          foot points present (an entry with finite x, y, z; a null or missing one is not)
    low_conf                        fraction of present points with conf below LOW_CONF (the writer's conf for a
                                    point projected outside the image is 0.3)
    points_with_ankle,              present points whose own ankle is readable (the only ones that can be measured)
    points_without_ankle            and those whose ankle is missing, null or not finite (not measured, never counted
                                    as within the bound or outside it)
    points_within_bound,            points with an ankle within BOUND_M of it, as a count and a fraction of
    within_bound, max_ankle_m       points_with_ankle (0.0 when there are none), and the largest point to ankle
                                    distance (m; null when no point could be measured)
    people{id}.segments{a-b}        per person over frames: n, mean_m and cv (std / mean, None below two frames) of
                                    ankle to heel, ankle to big toe and big toe to small toe, each side; the id is
                                    written as JSON, so 0 and "0" are two people
  summary: person_frames, with_all_six, coverage, points, points_without_ankle and within_bound over every readable
  file.

BOUND_M = 0.35: an adult foot measures under about 0.30 m from the back of the heel to the tip of the big toe and the
ankle joint sits between the two, so on a plausible foot no point is farther than that from its own ankle; the rest
is margin for the model's error. A point beyond it says the foot is implausible, not that the file is invalid.

Reported, never gated: exit 0 whatever the numbers. Exit 2 when a named or expected file cannot be read, is not JSON or
has no frames list; that file's entry names the error and the other files are still reported. The README gate
(make check-2) never reads this.
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np

from part2 import coco_set, outputs  # light imports (no model code); outputs.MODES is the one list of scored modes
from part2.check import scored_dir
from part2.doctor import DoctorError, people_in, read_json
from part2.joints import EXTRA, EXTRA_ANKLE
from part2.schema import is_number

ROOT = Path(__file__).resolve().parent.parent
BACKEND = "gpu"  # the backend that writes foot points (SAM 3D Body); the cpu backend's 17 points have none
BOUND_M = 0.35
LOW_CONF = 0.5
SEGMENTS = tuple((a, b) for side in ("left", "right") for a, b in (
    (f"{side}_ankle", f"{side}_heel"), (f"{side}_ankle", f"{side}_big_toe"), (f"{side}_big_toe", f"{side}_small_toe")))


def point(p: dict, name: str):
    """(xyz array, conf) of a joint or foot point of person p, or None when it is missing, null or not finite."""
    src = p.get("extra_joints") if name in EXTRA else p.get("joints")
    q = src.get(name) if isinstance(src, dict) else None
    if not isinstance(q, dict) or not all(is_number(q.get(k)) for k in "xyz"):
        return None
    return np.array([q["x"], q["y"], q["z"]], dtype=float), q.get("conf")


def check_doc(doc: dict) -> dict:
    """The per-file report (module docstring) for one pose3d document."""
    n = full = present = low = measured = within = 0
    max_d = None
    lengths: dict = {}
    for p in people_in(doc):
        n += 1
        got = {name: point(p, name) for name in EXTRA}
        full += all(v is not None for v in got.values())
        for name, v in got.items():
            if v is None:
                continue
            present += 1
            low += is_number(v[1]) and v[1] < LOW_CONF
            ankle = point(p, EXTRA_ANKLE[name])
            if ankle is not None:
                d = float(np.linalg.norm(v[0] - ankle[0]))
                measured += 1
                within += d <= BOUND_M
                max_d = d if max_d is None else max(max_d, d)
        segs = lengths.setdefault(json.dumps(p.get("id")), {f"{a}-{b}": [] for a, b in SEGMENTS})  # 0 is not "0"
        for a, b in SEGMENTS:
            pa, pb = point(p, a), point(p, b)
            if pa is not None and pb is not None:
                segs[f"{a}-{b}"].append(float(np.linalg.norm(pa[0] - pb[0])))
    return {"person_frames": n, "with_all_six": full, "coverage": _ratio(full, n), "points": present,
            "low_conf": _ratio(low, present), "points_with_ankle": measured, "points_without_ankle": present - measured,
            "points_within_bound": within, "within_bound": _ratio(within, measured),
            "max_ankle_m": None if max_d is None else round(max_d, 4),
            "people": {pid: {"segments": {k: _stats(v) for k, v in segs.items()}} for pid, segs in lengths.items()}}


def _stats(xs: list) -> dict:
    if not xs:
        return {"n": 0, "mean_m": None, "cv": None}
    mean = float(np.mean(xs))
    cv = float(np.std(xs) / mean) if len(xs) >= 2 and mean > 0 else None
    return {"n": len(xs), "mean_m": round(mean, 4), "cv": None if cv is None else round(cv, 4)}


def _ratio(a: int, b: int):
    return round(a / b, 4) if b else 0.0


def scored_files(scored) -> tuple[list[Path], list[dict]]:
    """(paths, problems): every pose3d.json of the gpu scored sets under `scored`, whether or not it exists: one per
    mode `outputs.MODES` lists for the gpu backend (coco-single, whose runner writes one per image, expands to one
    per image of the committed manifest `coco_set.MANIFEST`), so a mode added to MODES is checked with no edit here
    and a missing file is reported as unreadable. problems: [{file, error}] when the manifest cannot be read (the
    coco-single files cannot be named)."""
    scored, paths, problems = Path(scored), [], []
    for mode in outputs.modes_for(BACKEND):
        if mode.run is not outputs.run_coco:
            paths.append(scored / mode.name / "pose3d.json")
            continue
        manifest = coco_set.MANIFEST
        try:
            ids = [str(r["image_id"]) for r in read_json(manifest)["images"]]
        except DoctorError as e:
            problems.append({"file": str(manifest), "error": str(e)})
        except (KeyError, TypeError):
            problems.append({"file": str(manifest), "error": f"{manifest}: not a coco image manifest"})
        else:
            paths += [scored / mode.name / i / "pose3d.json" for i in ids]
    return paths, problems


def check_files(paths, problems=()) -> tuple[dict, int]:
    """(report, exit code): every file checked, unreadable ones named (`problems` are entries that already failed); exit
    2 if any was unreadable, else 0. No file at all gives an empty report and exit 0."""
    files, code = [dict(p) for p in problems], 2 if problems else 0
    for path in paths:
        try:
            doc = read_json(path)
            if not isinstance(doc, dict) or not isinstance(doc.get("frames"), list):
                raise DoctorError(f"{path}: not a pose3d file (no frames list)")
        except DoctorError as e:
            files.append({"file": str(path), "error": str(e)})
            code = 2
            continue
        files.append({"file": str(path), **check_doc(doc)})
    ok = [f for f in files if "error" not in f]
    pf, full, pts, measured, within = (sum(f[k] for f in ok) for k in (
        "person_frames", "with_all_six", "points", "points_with_ankle", "points_within_bound"))
    summary = {"files": len(ok), "unreadable": len(files) - len(ok), "person_frames": pf, "with_all_six": full,
               "coverage": _ratio(full, pf), "points": pts, "points_without_ankle": pts - measured,
               "within_bound": _ratio(within, measured)}
    return {"check": "foot points (TICKET-043)", "gated": False, "bound_m": BOUND_M, "low_conf_below": LOW_CONF,
            "files": files, "summary": summary}, code


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m part2.foot_check",
                                 description="Foot-point coverage and segment consistency of pose3d.json files; "
                                             "reported, never gated.")
    ap.add_argument("--scored", metavar="DIR",
                    help="check every file of the gpu scored sets under DIR (one per gpu mode of part2.outputs.MODES, "
                         "coco-single per image); default PART2_SCORED_DIR, else fixtures/output/scored, as for make "
                         "check-2; used when no FILE is named, and added to the FILEs when given")
    ap.add_argument("files", nargs="*", help="pose3d.json files; with none, and no --scored, the scored dir is checked")
    a = ap.parse_args(argv)
    paths, problems = scored_files(scored_dir(ROOT, a.scored)) if a.scored or not a.files else ([], [])
    report, code = check_files([*paths, *a.files], problems)
    print(json.dumps(report, indent=2))
    return code


if __name__ == "__main__":
    sys.exit(main())
