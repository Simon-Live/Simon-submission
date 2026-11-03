#!/usr/bin/env python3
"""Collect the raw run files that tools/eval_report.py reads (docs/specs/eval-report.md).

  python tools/eval_collect.py check7 --state DIR --out FILE
  python tools/eval_collect.py latency --state DIR --since ISO --out FILE

`check7` keeps, for every `<state>/check/<stamp>/metrics.json`, only the fields the report prints.
`latency` reads the job summary lines of `<state>/part7.log` since a cut-off, joins each with its
`jobs/<id>/job.json` and drops test jobs (judge_view.is_test_id on the entry id; a people job that a test job
used). It copies only ids, kind, status, seconds per stage and the GPU wait; no entry name, upload or note.
Everything here is stdlib and reads no keys.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from part7.judge_view import is_test_id  # noqa: E402

SUMMARY_RE = re.compile(r"^(\S+) \w+ job (\w+) summary: (.*)$")
STAGE_RE = re.compile(r"^(\w+)=([0-9.]+)s(?:\(gpu_wait=([0-9.]+)s\))?$")


def collect_check7(state: Path) -> dict:
    runs = []
    for path in sorted((state / "check").glob("*/metrics.json")):
        try:
            doc = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        takes = [{k: t.get(k) for k in ("clip", "role", "score_app", "score_direct", "score_equal",
                                         "faults_compared", "faults_equal")} for t in doc.get("takes", [])]
        runs.append({
            "run": path.parent.name,
            "part7_commit": doc.get("part7_commit"),
            "pass": doc.get("pass"),
            "gates": doc.get("gates"),
            "tolerance": doc.get("tolerance"),
            "animation_max_joint_diff_m": (doc.get("entry") or {}).get("animation_max_joint_diff_m_vs_direct"),
            "durations_s": doc.get("durations_s"),
            "takes": takes,
        })
    return {"format": "simon.eval.check7_runs/1", "runs": runs}


def parse_summary(line: str) -> dict | None:
    match = SUMMARY_RE.match(line.strip())
    if not match:
        return None
    stamp, job_id, rest = match.groups()
    out = {"id": job_id, "logged_at": stamp, "stages_s": {}, "gpu_wait_s": {}}
    for token in rest.split():
        key, _, value = token.partition("=")
        if key == "kind":
            out["kind"] = value
        elif key == "status":
            out["status"] = value
        elif key == "total":
            out["total_s"] = float(value.rstrip("s"))
        else:
            stage = STAGE_RE.match(token)
            if stage:
                out["stages_s"][stage.group(1)] = float(stage.group(2))
                if stage.group(3):
                    out["gpu_wait_s"][stage.group(1)] = float(stage.group(3))
    return out if "kind" in out and "total_s" in out else None


def collect_latency(state: Path, since: str) -> dict:
    jobs = {}
    for path in (state / "jobs").glob("*/job.json"):
        try:
            doc = json.loads(path.read_text())
            jobs[doc["id"]] = doc
        except (OSError, ValueError, KeyError):
            continue
    test_people = {d.get("people_job") for d in jobs.values() if is_test_id(d.get("entry_id")) and d.get("people_job")}
    kept, excluded = [], {"test": 0, "unknown_job": 0, "before_cutoff": 0}
    for line in (state / "part7.log").read_text(errors="replace").splitlines():
        row = parse_summary(line)
        if row is None:
            continue
        if row["logged_at"] < since:
            excluded["before_cutoff"] += 1
            continue
        doc = jobs.get(row["id"])
        if doc is None:
            excluded["unknown_job"] += 1
        elif is_test_id(doc.get("entry_id")) or row["id"] in test_people:
            excluded["test"] += 1
        else:
            kept.append(row)
    return {"format": "simon.eval.latency_jobs/1", "since": since, "source": "staging part7.log summary lines",
            "excluded": excluded, "jobs": kept}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("what", choices=("check7", "latency"))
    ap.add_argument("--state", type=Path, required=True)
    ap.add_argument("--since", default="")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    if args.what == "latency" and not args.since:
        ap.error("latency needs --since")
    doc = collect_check7(args.state) if args.what == "check7" else collect_latency(args.state, args.since)
    args.out.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
