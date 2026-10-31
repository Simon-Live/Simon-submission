"""python -m part2.foot_check [--scored DIR] [FILE ...]: a measured, ungated check of pose3d.json's foot points (TICKET-043).

Spec: docs/specs/integration-contract.md (AC-C16). `make check-feet` runs it with --scored over the committed scored
outputs of the gpu backend, the one that writes foot points: --scored DIR names every file of those sets under DIR
(scored_files), so a file that is missing is reported as unreadable instead of left out. Prints one JSON report:

  files[]: per file
    person_frames, with_all_six     person-frames, and those whose `extra_joints` holds all six points
    coverage                        with_all_six / person_frames (0.0 for a file without foot points)
    points                          foot points present (an entry with finite x, y, z; a null or missing one is not)
    low_conf                        fraction of present points with conf below LOW_CONF (the writer's conf for a
                                    point projected outside the image is 0.3)
    points_within_bound,            present points within BOUND_M of their own ankle, as a count and a fraction,
    within_bound, max_ankle_m       and the largest point to ankle distance (m)
    people{id}.segments{a-b}        per person over frames: n, mean_m and cv (std / mean, None below two frames) of
                                    ankle to heel, ankle to big toe and big toe to small toe, each side; the id is
                                    written as JSON, so 0 and "0" are two people
  summary: person_frames, with_all_six, coverage, points and within_bound over every readable file.

BOUND_M = 0.35: an adult foot measures under about 0.30 m from the back of the heel to the tip of the big toe and the
ankle joint sits between the two, so on a plausible foot no point is farther than that from its own ankle; the rest
is margin for the model's error. A point beyond it says the foot is implausible, not that the file is invalid.

Reported, never gated: exit 0 whatever the numbers, and also for no file at all (an empty report). Exit 2 when a named
file cannot be read, is not JSON or has no frames list; that file's entry names the error and the other files are still
reported. The README gate (make check-2) never reads this.
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np

from part2.doctor import DoctorError, people_in, read_json
from part2.joints import EXTRA, EXTRA_ANKLE
from part2.schema import is_number

ROOT = Path(__file__).resolve().parent.parent
COCO_MANIFEST = ROOT / "fixtures" / "input" / "coco" / "images" / "images.json"  # its image_ids name coco-single's dirs
SCORED_MODES = ("single", "class", "class-local-open")  # the gpu scored sets with one pose3d.json each
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
    n = full = present = low = within = 0
    max_d = 0.0
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
                within += d <= BOUND_M
                max_d = max(max_d, d)
        segs = lengths.setdefault(json.dumps(p.get("id")), {f"{a}-{b}": [] for a, b in SEGMENTS})  # 0 is not "0"
        for a, b in SEGMENTS:
            pa, pb = point(p, a), point(p, b)
            if pa is not None and pb is not None:
                segs[f"{a}-{b}"].append(float(np.linalg.norm(pa[0] - pb[0])))
    return {"person_frames": n, "with_all_six": full, "coverage": _ratio(full, n), "points": present,
            "low_conf": _ratio(low, present), "points_within_bound": within, "within_bound": _ratio(within, present),
            "max_ankle_m": round(max_d, 4) if present else None,
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
    SCORED_MODES and one per image of coco-single named by the committed manifest, so a missing file is reported as
    unreadable. problems: [{file, error}] when the manifest cannot be read (the coco-single files cannot be named)."""
    scored = Path(scored)
    paths = [scored / mode / "pose3d.json" for mode in SCORED_MODES]
    try:
        paths += [scored / "coco-single" / str(r["image_id"]) / "pose3d.json" for r in read_json(COCO_MANIFEST)["images"]]
    except DoctorError as e:
        return paths, [{"file": str(COCO_MANIFEST), "error": str(e)}]
    except (KeyError, TypeError):
        return paths, [{"file": str(COCO_MANIFEST), "error": f"{COCO_MANIFEST}: not a coco image manifest"}]
    return paths, []


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
    pf, full, pts, within = (sum(f[k] for f in ok) for k in ("person_frames", "with_all_six", "points",
                                                             "points_within_bound"))
    summary = {"files": len(ok), "unreadable": len(files) - len(ok), "person_frames": pf, "with_all_six": full,
               "coverage": _ratio(full, pf), "points": pts, "within_bound": _ratio(within, pts)}
    return {"check": "foot points (TICKET-043)", "gated": False, "bound_m": BOUND_M, "low_conf_below": LOW_CONF,
            "files": files, "summary": summary}, code


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m part2.foot_check",
                                 description="Foot-point coverage and segment consistency of pose3d.json files; "
                                             "reported, never gated.")
    ap.add_argument("--scored", metavar="DIR", help="also check every file of the gpu scored sets under DIR: single, "
                                                    "class, class-local-open and coco-single/<image_id>")
    ap.add_argument("files", nargs="*", help="pose3d.json files; with none at all the report is empty")
    a = ap.parse_args(argv)
    paths, problems = scored_files(a.scored) if a.scored else ([], [])
    report, code = check_files([*paths, *a.files], problems)
    print(json.dumps(report, indent=2))
    return code


if __name__ == "__main__":
    sys.exit(main())
