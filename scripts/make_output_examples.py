"""Write the shipped golden outputs by running the real pipeline on dummy takes, the way `part5 analyse` does.

  fixtures/output/analysis.example.json           a double-fault take (faults listed)
  fixtures/output/analysis.no-faults.example.json a correct take (`faults: []`)
  fixtures/output/analysis.fault-capped.example.json a take that reports a fault and hits the ceiling of simon.score.v2
                                                  (`score.fault_cap` 89, `score.uncapped` the value before it, no
                                                  `capped_by`; ADR-0018, a sample for Part 7)
  fixtures/output/replay.example.json             the replay (`simon.replay.v1`) of the double-fault take

Every golden goes through `part5.contract.golden_run`: the score hook included, so a golden carries the score,
its timeline, the tempo and the insights real output carries, and the `template` phrasing forced, so a golden
never calls a model whatever SIMON5_LIVE or META_LIVE say. `make check-5-contract` rebuilds them through the same
function and fails on a byte of difference.

Deterministic for a given pipeline: rerunning with unchanged code rewrites identical files.
Run: `make output-examples` (uv run python; it needs numpy via the project env).
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from part5.contract import REPLAY_SOURCE, golden_run  # noqa: E402
from part5.output import write_analysis                # noqa: E402
from part5.replay import write_replay                  # noqa: E402
from part5.score import ships_v2                       # noqa: E402

OUT = ROOT / "fixtures" / "output"
EXAMPLES = [("exercise_front_good_08", "analysis.example.json"),
            ("exercise_front_good_00", "analysis.no-faults.example.json")]
V2_SAMPLE = "analysis.fault-capped.example.json"   # a simon.score.v2 sample: written only while the rules ship v2
# a dance take analysed without its foot files: it reports one arm fault (a light one in one rep), and its mean
# of windows is above 89 before the ceiling of simon.score.v2 (ADR-0018) lowers it
EXAMPLES.append(("dance_side_good_11", V2_SAMPLE))
REPLAY_FILE = "replay.example.json"


def take_of(labels, prefix):
    return next(t for t in labels["takes"] if t["take_id"].startswith(prefix))


def main(out=OUT):
    out = Path(out)
    labels = json.loads((ROOT / "fixtures/input/followers/labels.json").read_text())
    for prefix, filename in EXAMPLES:
        if filename == V2_SAMPLE and not ships_v2():   # after `make score-fallback` (ADR-0018) there is no ceiling to show
            continue
        take = take_of(labels, prefix)
        result = golden_run({"path": take["expected"], "set": take["set"], "movement": take["movement"]},
                            {"path": take["follower"], "take_id": take["take_id"]})
        doc = write_analysis(out / filename, result.analysis)
        print(f"wrote {filename}: {len(doc['faults'])} fault(s), score {doc['score']['value']} "
              f"({doc['score']['grade']}) for {take['take_id']}")
        if filename == REPLAY_SOURCE:
            replay = write_replay(out / REPLAY_FILE, result)
            print(f"wrote {REPLAY_FILE}: {len(replay['expected'])} expected and {len(replay['follower'])} "
                  f"follower frames for {take['take_id']}")


if __name__ == "__main__":
    main()
