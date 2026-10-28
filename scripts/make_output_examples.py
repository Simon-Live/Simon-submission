"""Write the two shipped `analysis.json` examples by running the real pipeline on dummy takes.

  fixtures/output/analysis.example.json           a double-fault take (faults listed)
  fixtures/output/analysis.no-faults.example.json a correct take (`faults: []`)

Deterministic for a given pipeline: rerunning with unchanged code rewrites identical files.
Run: `make output-examples` (uv run python; it needs numpy via the project env).
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from part5.align import align          # noqa: E402
from part5.detect import detect        # noqa: E402
from part5.io import load_clip         # noqa: E402
from part5.measures import compute     # noqa: E402
from part5.normalise import normalise  # noqa: E402
from part5.output import build_analysis, write_analysis  # noqa: E402

OUT = ROOT / "fixtures" / "output"
EXAMPLES = [("exercise_front_good_07", "analysis.example.json"),
            ("exercise_front_good_00", "analysis.no-faults.example.json")]


def analyse(take):
    exp = normalise(load_clip(ROOT / take["expected"]))
    fol = normalise(load_clip(ROOT / take["follower"]))
    alignment = align(exp.positions, fol.positions)
    faults = detect(compute(exp.positions), compute(fol.positions), alignment)
    diagnostics = {"alignment_residual": round(float(alignment.residual), 4),
                   "alignment_measures": alignment.measures,
                   "follower_span": [int(alignment.follower_span[0]), int(alignment.follower_span[1])]}
    return build_analysis(
        {"path": take["expected"], "set": take["set"], "movement": take["movement"]},
        {"path": take["follower"], "take_id": take["take_id"]},
        faults, diagnostics=diagnostics)


def main():
    labels = json.loads((ROOT / "fixtures/input/followers/labels.json").read_text())
    for prefix, filename in EXAMPLES:
        take = next(t for t in labels["takes"] if t["take_id"].startswith(prefix))
        doc = write_analysis(OUT / filename, analyse(take))
        print(f"wrote {filename}: {len(doc['faults'])} fault(s) for {take['take_id']}")


if __name__ == "__main__":
    main()
