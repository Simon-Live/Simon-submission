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

from part5.output import write_analysis  # noqa: E402
from part5.pipeline import analyse       # noqa: E402

OUT = ROOT / "fixtures" / "output"
EXAMPLES = [("exercise_front_good_08", "analysis.example.json"),
            ("exercise_front_good_00", "analysis.no-faults.example.json")]


def main():
    labels = json.loads((ROOT / "fixtures/input/followers/labels.json").read_text())
    for prefix, filename in EXAMPLES:
        take = next(t for t in labels["takes"] if t["take_id"].startswith(prefix))
        doc = write_analysis(OUT / filename, analyse(
            {"path": take["expected"], "set": take["set"], "movement": take["movement"]},
            {"path": take["follower"], "take_id": take["take_id"]}))
        print(f"wrote {filename}: {len(doc['faults'])} fault(s) for {take['take_id']}")


if __name__ == "__main__":
    main()
