"""Retimed copies of the seed 5 exercise takes: the fast and the low-frame-rate pairs of the body floor (recheck N2).

A test helper, not a test and not data: it writes the retimed clips into a directory the caller gives it, so nothing but
this generator is committed. The pairs are the 27 good-light, clean seed 5 exercise takes numbered 00 to 08 (three
angles; two correct, seven with one or two planted faults, 8 labelled faults per angle, 24 in all) and the exercise
example, each played `speed` times faster and sampled at `fps` (joints linearly interpolated, a missing joint stays
missing). The squat is 3 s at 30 fps (91 frames); the rows are the clip the way a Part 2 skeleton or a quick set gives it:

| row         | what it is                         | example frames |
| 15fps_x1    | normal speed at 15 fps             | 46 |
| 10fps_x1    | normal speed at 10 fps             | 31 |
| 5fps_x1     | normal speed at 5 fps              | 16 |
| 30fps_x1.5  | a 2 s squat at 30 fps              | 61 |
| 30fps_x2    | a 1.5 s squat at 30 fps            | 46 |
| 15fps_x2    | a 1.5 s squat at 15 fps            | 23 |

`tally` runs the pairs through the pipeline and counts, per row, the labelled faults found (`tp` of `labels`), the faults
that match no label (`fp`), the correct takes with a fault (`foc`) and the faulty takes scored A (`faulty_a`). Seed 5
is read through its labels.json, and the helper refuses any other seed.
"""
import json
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
LABELS = ROOT / "fixtures" / "input" / "followers" / "labels.json"
VARIANTS = {"15fps_x1": (1.0, 15), "10fps_x1": (1.0, 10), "5fps_x1": (1.0, 5),
            "30fps_x1.5": (1.5, 30), "30fps_x2": (2.0, 30), "15fps_x2": (2.0, 15)}
LABELLED = 24       # faults planted in the 27 takes, 8 per angle


def retime(src, dst, speed, fps):
    """Write the clip at `src` to `dst` played `speed` times faster and sampled at `fps`; returns its frame count."""
    doc = json.loads(Path(src).read_text())
    frames = doc["frames"]
    t = np.array([f["t"] for f in frames])
    names = list(frames[0]["joints"])
    stack = np.array([[f["joints"][name] if f["joints"].get(name) is not None else [np.nan] * 3 for name in names]
                      for f in frames], float)                                    # frames x joints x 3
    n = int(round((t[-1] - t[0]) / speed * fps)) + 1
    new_t = np.arange(n) / fps
    source_t = t[0] + new_t * speed
    sampled = np.stack([[np.interp(source_t, t, stack[:, j, k]) for k in range(3)] for j in range(len(names))])  # j x 3 x n
    out = [{"index": i, "t": round(float(new_t[i]), 6), "interpolated": False,
            "joints": {name: [float(v) for v in sampled[j, :, i]] for j, name in enumerate(names)}}
           for i in range(n)]
    doc.update(frames=out, fps=fps, frame_count=n, duration_s=round(float(new_t[-1]), 6))
    Path(dst).write_text(json.dumps(doc))
    return n


def picked_takes(labels=None):
    """The 27 takes retimed: good light, clean, exercise, numbered 00 to 08. Refuses a set that is not seed 5."""
    labels = labels or json.loads(LABELS.read_text())
    if labels.get("seed") != 5:
        raise ValueError(f"retimed takes are built from seed 5 only (got {labels.get('seed')})")
    return [t for t in labels["takes"] if t["lighting"] == "good" and t["variant"] == "clean" and t["set"] == "exercise"
            and int(t["take_id"].split("_")[3]) <= 8]


def write_variants(out_dir, variants=None):
    """Write every row's clips under `out_dir/<row>/` and return the index: one entry per (row, take) with the paths."""
    out_dir, index, takes = Path(out_dir), [], picked_takes()
    for row, (speed, fps) in (variants or VARIANTS).items():
        d = out_dir / row
        d.mkdir(parents=True, exist_ok=True)
        n_exp = retime(ROOT / takes[0]["expected"], d / "expected.json", speed, fps)
        for t in takes:
            retime(ROOT / t["follower"], d / f"{t['take_id']}.json", speed, fps)
            index.append({"variant": row, "take_id": t["take_id"], "faults": t["faults"], "correct": t["correct"],
                          "expected": str(d / "expected.json"), "follower": str(d / f"{t['take_id']}.json"),
                          "n_exp": n_exp})
    return index


def _one(task):
    entry, rules = task
    from part5.evaluate import match_faults
    from part5.pipeline import run
    from part5.score_report import score_block
    analysis = run({"path": entry["expected"]}, {"path": entry["follower"]}, rules, score=score_block).analysis
    found = match_faults(analysis["faults"], entry["faults"])[0]
    return {"variant": entry["variant"], "tp": found, "labels": len(entry["faults"]),
            "fp": len(analysis["faults"]) - found, "correct": entry["correct"], "faults": len(analysis["faults"]),
            "grade": (analysis.get("score") or {}).get("grade")}


def tally(index, rules=None, workers=1):
    """`{row: {tp, labels, fp, foc, faulty_a}}` over the index of `write_variants`, run with `rules` (the shipped ones
    when None). `foc` counts the correct takes with a fault; `faulty_a` the takes with a labelled fault scored A."""
    tasks = [(e, rules) for e in index]
    if workers > 1:
        with ProcessPoolExecutor(workers) as pool:
            results = list(pool.map(_one, tasks, chunksize=4))
    else:
        results = [_one(t) for t in tasks]
    rows = {}
    for r in results:
        row = rows.setdefault(r["variant"], {"tp": 0, "labels": 0, "fp": 0, "foc": 0, "faulty_a": 0})
        row["tp"] += r["tp"]
        row["labels"] += r["labels"]
        row["fp"] += r["fp"]
        row["foc"] += bool(r["correct"] and r["faults"])
        row["faulty_a"] += bool(r["labels"] and r["grade"] == "A")
    return rows
