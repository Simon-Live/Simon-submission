"""Write the degraded seed 5 input behind `fixtures/output/analysis.quality-major.example.json` (TICKET-079, ADR-0021).

  fixtures/input/quality/exercise_front_dark_00/skeleton.json

It is the low-light correct take of seed 5 (`exercise_front_low_00_correct`, front view, a squat) with the five face joints (nose,
eyes, ears) and both wrists reported at Part 2's unseen mark, `conf` 0.3, in every frame, and every other joint at `conf` 1.0: a take
whose face and hands the estimator lost. Nothing else changes, so the body, the noise and the timing are the seed 5 take's own. Part 2 writes `conf` 1.0 for a
joint inside the image and exactly 0.3 for one outside it (Part 2 CONTRACT), which is what this does.

The take is a stand-in for a dark clip and claims no more: Part 5 has no light reading, so the quality block names what it measured
(41 percent of the joint readings outside the picture, and the joint jitter of low light) and not a cause. The sample is derived, not
measured: `make output-examples` runs the real pipeline on it.

Deterministic: no random numbers, so rerunning writes identical bytes. Run: `python3 scripts/make_quality_sample.py` (`--check`
exits 1 when the committed file differs).
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "fixtures/input/followers/exercise/exercise_front_low_00_correct/skeleton.json"
OUT = ROOT / "fixtures/input/quality/exercise_front_dark_00/skeleton.json"
LOST = ("nose", "left_eye", "right_eye", "left_ear", "right_ear", "left_wrist", "right_wrist")   # the face and the hands
UNSEEN, SEEN = 0.3, 1.0


def degraded(doc):
    """`doc` (a seed 5 follower) with a `conf` on every frame: the `LOST` joints at the unseen mark, the rest seen."""
    out = json.loads(json.dumps(doc))
    for frame in out["frames"]:
        frame["conf"] = {joint: UNSEEN if joint in LOST else SEEN for joint in out["joints"]}
    return out


def render(doc):
    return json.dumps(doc, separators=(",", ":")) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="exit 1 when the committed file differs from what this writes")
    args = ap.parse_args(argv)
    text = render(degraded(json.loads(SOURCE.read_text())))
    if args.check:
        same = OUT.is_file() and OUT.read_text() == text
        print(f"{OUT.relative_to(ROOT)}: {'unchanged' if same else 'differs'}")
        return 0 if same else 1
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text)
    print(f"wrote {OUT.relative_to(ROOT)}: {len(json.loads(text)['frames'])} frames, {len(LOST)} joints at conf {UNSEEN}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
