"""How far `score.credit` points move when the same follower take is retimed (TICKET-078, N1 of the delta review).

    python3 scripts/make_score_credit_retime_noise.py [--sets exercise dance] [--speeds 0.75 0.5 0.33 1.5] [--mode retime|stretch] [--list]

Takes the good-light, clean seed 5 takes numbered 00 to 08 of the given sets (default: the 27 exercise takes, the ones
`tests/retimed.py` retimes), plays each `speed` times as fast at 30 fps (`retimed.retime`, so 0.5 takes twice the seconds), and
runs the original and the retimed clip through the whole pipeline against the same example, with the score. Per speed, and
for all the slower speeds together, it prints, over the pairs whose comparison basis (the whole take, or rep by rep) is the
same before and after:

- how many pairs have the same `max_points`,
- in how many pairs the retimed take earned more points than the original and in how many fewer, and the largest rise and the
  largest fall, in points and as a percent of the original's points.

The points are counted on the example's clock, so they do not scale with the follower's clock; what is left is not the
clock's. A retimed take's points are not the original's, in either direction, and the falls were not traced further
(`--mode stretch`, below, falls too; the pipeline resamples every follower to the example's frame rate either way). This is
the measurement behind AC-CR-03 in docs/specs/score-credit.md. Nothing is written but a temporary directory, and only seed 5 is read.

`--mode stretch` retimes the other way: it keeps the follower file's own frames and scales their timestamps (each `t` divided
by the speed, so 0.5 doubles every timestamp). That is the probe of the first review of this block
(progress/review-20261102-score-credit.md, B2). On a tree that counts points on the follower's clock (7181813) it gives that
review's 9889 of 10120 points for `exercise_front_good_00_correct` at half speed (`--speeds 0.5 --list`).
"""
import argparse
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from part5.pipeline import run  # noqa: E402
from part5.score_report import score_block  # noqa: E402
from retimed import picked_takes, retime  # noqa: E402

DEFAULT_SPEEDS = (0.75, 0.5, 0.33, 1.5)


def stretch(src, dst, speed, fps):
    """Write the clip at `src` to `dst` played `speed` times as fast by moving its timestamps only: every frame is kept and
    each `t` is divided by `speed`, with `fps` and `duration_s` to match; no frame is added. `fps` is unused (the
    signature is `retimed.retime`'s, so either can be a mode)."""
    doc = json.loads(Path(src).read_text())
    for frame in doc["frames"]:
        frame["t"] = round(frame["t"] / speed, 6)
    doc.update(fps=doc["fps"] * speed, duration_s=round(doc["duration_s"] / speed, 6))
    Path(dst).write_text(json.dumps(doc))
    return len(doc["frames"])


MODES = {"retime": retime, "stretch": stretch}


def credit_of(expected, follower_path, take_id):
    """`(score.credit, score.basis)` of one follower clip against the example."""
    score = run({"path": str(ROOT / expected)}, {"path": str(follower_path), "take_id": take_id},
                score=score_block).analysis["score"]
    return score["credit"], score["basis"]


def measure(takes, speeds, tmp, mode="retime"):
    """`{speed: [row]}`, a row being one take's original and retimed credit and the two comparison bases; the clip is
    retimed the way `MODES[mode]` does."""
    rows = {speed: [] for speed in speeds}
    for take in takes:
        base, base_basis = credit_of(take["expected"], ROOT / take["follower"], take["take_id"])
        for speed in speeds:
            clip = Path(tmp) / f"{take['take_id']}.{speed}.json"
            MODES[mode](ROOT / take["follower"], clip, speed, 30)
            now, now_basis = credit_of(take["expected"], clip, take["take_id"])
            rows[speed].append({"take_id": take["take_id"], "base": base, "now": now, "bases": (base_basis, now_basis)})
    return rows


def summary(rows):
    """The numbers of some rows: pairs, pairs of one basis, equal max_points, and the largest rise and fall of the points
    (in points, and as a percent of the original's points) among the pairs whose comparison basis did not change."""
    same = [r for r in rows if r["bases"][0] == r["bases"][1] and r["base"] and r["now"]]
    change = [r["now"]["points"] - r["base"]["points"] for r in same]
    percent = [100 * c / r["base"]["points"] for c, r in zip(change, same)]
    return {"pairs": len(rows), "same_basis": len(same),
            "same_max_points": sum(r["now"]["max_points"] == r["base"]["max_points"] for r in same),
            "more": sum(c > 0 for c in change), "less": sum(c < 0 for c in change),
            "rise": max([c for c in change if c > 0], default=0), "fall": max([-c for c in change if c < 0], default=0),
            "rise_percent": max([c for c in percent if c > 0], default=0.0),
            "fall_percent": max([-c for c in percent if c < 0], default=0.0)}


def line(label, s):
    return (f"{label}: pairs {s['pairs']}, same basis {s['same_basis']}, same max_points {s['same_max_points']}, "
            f"retimed earned more in {s['more']} (at most {s['rise']} points, {s['rise_percent']:.2f} percent of the points) "
            f"and fewer in {s['less']} (at most {s['fall']} points, {s['fall_percent']:.1f} percent)")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--sets", nargs="+", default=["exercise"])
    ap.add_argument("--speeds", nargs="+", type=float, default=list(DEFAULT_SPEEDS))
    ap.add_argument("--mode", choices=sorted(MODES), default="retime",
                    help="retime: write new frames at 30 fps (default); stretch: keep the file's frames and scale their timestamps")
    ap.add_argument("--list", action="store_true", help="also print every pair")
    args = ap.parse_args(argv)
    try:
        takes = picked_takes(sets=args.sets)
    except ValueError as err:
        raise SystemExit(f"make_score_credit_retime_noise: {err}")
    with tempfile.TemporaryDirectory(prefix="credit-retime-noise-") as tmp:
        rows = measure(takes, args.speeds, tmp, args.mode)
    print(f"sets {','.join(args.sets)}: {len(takes)} takes")
    if args.mode != "retime":
        print(f"mode {args.mode}")
    for speed, found in rows.items():
        print(line(f"speed {speed}", summary(found)))
        for r in found if args.list else ():
            b, n = r["base"], r["now"]
            print(f"  {r['take_id']} {r['bases'][0]}>{r['bases'][1]}: points {b and b['points']}>{n and n['points']}, "
                  f"max {b and b['max_points']}>{n and n['max_points']}, percent {b and b['percent']}>{n and n['percent']}")
    slower = [r for speed, found in rows.items() if speed < 1 for r in found]
    if slower:
        print(line("slower than the original (all speeds under 1)", summary(slower)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
