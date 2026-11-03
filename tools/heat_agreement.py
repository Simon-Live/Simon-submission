"""AC-2 of TICKET-274, as revised by the coordinator ruling of 2026-11-02 (rule fixed in docs/specs/heat.md first).

Usage: uv run python tools/heat_agreement.py <jobs_root> <job_id> [<job_id> ...]   (add --json for one JSON document)

At each Part 5 fault time (`at_s`, follower clock) the hottest region of the nearest valid heat frame (within
heat.NEAREST_S) must sit on the limb of one of the fault's joints. Faults in the last TAIL_S of the take
(`follower.json` `duration_s`) are excluded, because DTW clamps there (the rule AC-2 was measured under on 2026-11-02;
part7/heat.py has since replaced the fixed tail with the aligned-part rule). A job agrees when every remaining fault
matches; a job with none left does not agree and is listed, not skipped. AC-2 passes at 4 or more of 5.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from part7 import heat  # noqa: E402

PASS_AT = 4
TAIL_S = 0.5  # the fixed tail of the 2026-11-02 AC-2 run, kept so that run can be reproduced


def limb(name: str) -> str:
    """`left_leg`, `right_arm`, `torso` or `head` for a region or joint name (unchanged from the first run)."""
    side, _, rest = name.partition("_")
    if name in heat.HEAD_LABELS or name == "head":
        return "head"
    if side in ("left", "right"):
        if rest in ("hip", "knee", "ankle", "thigh", "shin", "foot"):
            return f"{side}_leg"
        if rest in ("elbow", "wrist", "upper_arm", "forearm", "hand"):
            return f"{side}_arm"
    return "torso"


def _read(path: Path) -> dict:
    return json.loads(path.read_text()) if path.is_file() else {}


def check(jobs_root: Path, job_id: str) -> dict:
    folder = jobs_root / job_id / "work" / "follower"
    found = heat.files(jobs_root, job_id)
    meta = json.loads(found[0].with_name(heat.META).read_text()) if found else None
    analysis = _read(folder / "analysis.json")
    faults = [f for f in (analysis.get("faults") or []) if isinstance(f.get("at_s"), (int, float))]
    duration = _read(folder / "follower.json").get("duration_s")
    out = {"job": job_id, "heat": bool(meta), "faults": len(faults), "duration_s": duration}
    if not meta:
        return {**out, "agrees": False, "why": "no heat", "rows": []}
    end = duration or max(f["t_ms"] for f in meta["frames"]) / 1000.0
    rows = []
    for k, f in enumerate(faults):
        row = {"fault": k, "measure": f.get("measure"), "at_s": f["at_s"], "joints": f.get("joints", []),
               "fault_limbs": sorted({limb(j) for j in f.get("joints", [])})}
        if f["at_s"] > end - TAIL_S:
            rows.append({**row, "excluded": "tail"})
            continue
        i = heat.nearest_valid(meta, float(f["at_s"]))
        region = meta["frames"][i]["region"] if i is not None else None
        rows.append({**row, "excluded": None, "region": region, "limb": limb(region) if region else None,
                     "match": bool(region) and limb(region) in row["fault_limbs"]})
    scored = [r for r in rows if not r["excluded"]]
    opens = heat.open_moment(meta, analysis)
    lead = next((r for r in rows if r["fault"] == 0), None)
    return {**out, "end_s": round(end, 3), "scored": len(scored), "excluded": len(rows) - len(scored),
            "matched": sum(r["match"] for r in scored), "agrees": bool(scored) and all(r["match"] for r in scored),
            "why": None if scored else ("no Part 5 fault" if not faults else "every fault in the tail"),
            "lead_fault_match": lead.get("match") if lead else None, "opens": opens, "rows": rows}


def main(argv: list[str]) -> int:
    args = [a for a in argv if a != "--json"]
    jobs = [check(Path(args[0]), j) for j in args[1:]]
    agree = sum(j["agrees"] for j in jobs)
    summary = {"agree": agree, "of": len(jobs), "passes": agree >= PASS_AT,
               "faults_matched": sum(j.get("matched", 0) for j in jobs), "faults_scored": sum(j.get("scored", 0) for j in jobs),
               "faults_excluded_tail": sum(j.get("excluded", 0) for j in jobs)}
    if "--json" in argv:
        print(json.dumps({"jobs": jobs, **summary}, indent=1))
    else:
        for j in jobs:
            print({k: v for k, v in j.items() if k != "rows"})
        print(f"{agree} of {len(jobs)} agree; faults {summary['faults_matched']} of {summary['faults_scored']} match, {summary['faults_excluded_tail']} in the tail")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
