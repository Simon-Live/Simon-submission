"""History faithfulness eval harness (TICKET-220, docs/specs/history-eval.md).

Golden cases (tests/part7/fixtures/history_golden/*.json, synthetic unless a case says `origin: real`) each hold a fact
table, the facts a good answer must keep and canned model answers. One run packs the case with `history_prompt.pack`,
asks through `history_api.ask` (a scripted fake of the Meta transport unless live mode is on), checks the answer with
`history_guard.check` and scores what the guard kept. Metric functions are pure: they take the answer, `kept`,
`rejected` and the case's `expect` block and never call a model.

Run: `uv run python -m tests.part7.history_eval [--out FILE] [--ab]`. Live mode (`--live`) makes paid calls, goes through
history_api's ledger with feature "eval" and refuses unless SIMON7_HISTORY_EVAL_LIVE=1. No spend cap is on by default;
`SIMON7_HISTORY_EVAL_CAP_USD` (history_api.feature_cap) bounds the feature when set.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any, Callable

from part7 import history_api, history_guard, history_longpack, history_prompt

FIXTURES = Path(__file__).parent / "fixtures" / "history_golden"
FEATURE = "eval"
LIVE_ENV = "SIMON7_HISTORY_EVAL_LIVE"
RUNS = 3
COVER_STATUSES = ("persistent", "new", "came_back")
RULES = tuple(range(1, 10))
FULL_VERSION = "eval.full_analysis"
Packer = Callable[[dict[str, Any]], dict[str, Any]]


# ----- cases ------------------------------------------------------------------------------------------
def load_cases(directory: Path | str = FIXTURES) -> list[dict[str, Any]]:
    """Every case file of the folder, sorted by id."""
    cases = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(Path(directory).glob("*.json"))]
    return sorted(cases, key=lambda c: c["id"])


def _key(measure: Any, side: Any) -> str:
    return f"{measure}|{side}"


# ----- metrics (pure) ---------------------------------------------------------------------------------
def answer_items(answer: Any) -> list[str]:
    """The names (`trends[0]`, `focus`) of the items an answer holds, the names `rejected` uses."""
    doc = history_guard.parse_answer(answer) or {}
    names = []
    if isinstance(doc.get("summary"), dict):
        names.append("summary")
    for key in ("trends", "observations"):
        names += [f"{key}[{i}]" for i in range(len(doc.get(key)) if isinstance(doc.get(key), list) else 0)]
    names += [k for k in ("focus", "teacher_link") if doc.get(k) is not None]
    return names


def guard_stats(answer: Any, rejected: list[dict[str, Any]]) -> dict[str, Any]:
    """`{items, by_rule}`: how many items the answer held and how many each rule rejected (rule 0 = over a limit)."""
    names = set(answer_items(answer))
    by_rule: dict[str, int] = {}
    for row in rejected:
        if row.get("item") in names:
            rule = str(row.get("rule") or 0)
            by_rule[rule] = by_rule.get(rule, 0) + 1
    return {"items": len(names), "by_rule": by_rule}


def pass_rates(stats: list[dict[str, Any]]) -> dict[str, float | None]:
    """Share of items each rule let through, over many answers; `all` is the share the guard kept. None with no items."""
    items = sum(s["items"] for s in stats)
    if not items:
        return {**{str(r): None for r in RULES}, "all": None}
    rates: dict[str, float | None] = {
        str(r): round((items-sum(s["by_rule"].get(str(r), 0) for s in stats)) / items, 4) for r in RULES}
    rates["all"] = round((items-sum(sum(s["by_rule"].values()) for s in stats)) / items, 4)
    return rates


def coverage(kept: dict[str, Any], facts: dict[str, Any]) -> dict[str, int]:
    """Persistent, new and came_back measures of the table that a kept trend of the same kind names."""
    wanted = [m for m in facts.get("measures") or [] if m.get("status") in COVER_STATUSES]
    said = {(t.get("kind"), t.get("measure"), t.get("side")) for t in kept.get("trends") or []}
    hit = sum((m["status"], m["measure"], m["side"]) in said for m in wanted)
    return {"hit": hit, "total": len(wanted)}


def focus_correct(kept: dict[str, Any], expect: dict[str, Any]) -> bool | None:
    """The kept focus has the expected measure, side and cue; None when the case expects no focus."""
    want = expect.get("focus")
    if not want:
        return None
    got = kept.get("focus") or {}
    return all(got.get(k) == want.get(k) for k in ("measure", "side", "cue"))


def update_test(kept: dict[str, Any], expect: dict[str, Any]) -> bool | None:
    """Every fault fixed and then back is a kept `came_back` trend and no kept trend calls it `improved`."""
    wanted = expect.get("came_back") or []
    if not wanted:
        return None
    trends = kept.get("trends") or []
    for item in wanted:
        kinds = {t.get("kind") for t in trends if (t.get("measure"), t.get("side")) == (item["measure"], item["side"])}
        if "came_back" not in kinds or "improved" in kinds:
            return False
    return True


def cited_takes(kept: dict[str, Any]) -> set[int]:
    """Every take number a kept item cites (an observation cites its own `take`)."""
    found: set[int] = set()
    for key in ("summary", "focus", "teacher_link"):
        found |= {c["take"] for c in (kept.get(key) or {}).get("cites") or []}
    for trend in kept.get("trends") or []:
        found |= {c["take"] for c in trend.get("cites") or []}
    found |= {o["take"] for o in kept.get("observations") or []}
    return found


def middle_cited(kept: dict[str, Any], expect: dict[str, Any]) -> bool | None:
    """A kept trend about the expected measure and side cites the middle take."""
    want = expect.get("middle")
    if not want:
        return None
    return any((t.get("measure"), t.get("side")) == (want["measure"], want["side"])
               and want["take"] in {c["take"] for c in t.get("cites") or []} for t in kept.get("trends") or [])


def distractor_cited(items: dict[str, Any], distractors: list[int]) -> list[int] | None:
    """The distractor take numbers a set of items cites (empty is a pass); None when the case has no distractors."""
    if not distractors:
        return None
    return sorted(cited_takes(items) & set(distractors))


def raw_cited(answer: Any, distractors: list[int]) -> list[int] | None:
    """The distractor takes the model's own answer cites, before the guard (a model-faithfulness reading)."""
    if not distractors:
        return None
    doc = history_guard.parse_answer(answer) or {}
    found: set[int] = set()
    for key in ("summary", "focus", "teacher_link"):
        item = doc.get(key)
        found |= {c.get("take") for c in (item.get("cites") if isinstance(item, dict) else None) or [] if isinstance(c, dict)}
    for item in doc.get("trends") or []:
        found |= {c.get("take") for c in item.get("cites") or [] if isinstance(c, dict)}
    found |= {o.get("take") for o in doc.get("observations") or [] if isinstance(o, dict)}
    return sorted(found & set(distractors))


def abstained(kept: dict[str, Any], expect: dict[str, Any]) -> bool | None:
    """An unanswerable case keeps no trend, focus, teacher link or observation (the fact-table summary may stay)."""
    if not expect.get("abstain"):
        return None
    return not (kept.get("trends") or kept.get("focus") or kept.get("teacher_link") or kept.get("observations"))


def item_keys(kept: dict[str, Any]) -> set[tuple[Any, ...]]:
    """Identity of each kept item, so runs can be compared."""
    keys: set[tuple[Any, ...]] = {("trend", t["kind"], t["measure"], t["side"]) for t in kept.get("trends") or []}
    focus = kept.get("focus")
    if focus:
        keys.add(("focus", focus["measure"], focus["side"], focus["cue"]))
    link = kept.get("teacher_link")
    if link:
        keys.add(("teacher_link", link["cue_index"]))
    keys |= {("observation", o["take"], o["at_s"]) for o in kept.get("observations") or []}
    return keys


def jaccard(a: set[Any], b: set[Any]) -> float:
    return 1.0 if not a and not b else len(a & b) / len(a | b)


def stability(kept_runs: list[dict[str, Any]]) -> float | None:
    """Mean pairwise Jaccard overlap of the kept items of several runs of the same pack; None with fewer than two."""
    sets = [item_keys(k) for k in kept_runs]
    pairs = [jaccard(sets[i], sets[j]) for i in range(len(sets)) for j in range(i + 1, len(sets))]
    return round(sum(pairs) / len(pairs), 4) if pairs else None


# ----- one run ----------------------------------------------------------------------------------------
class ScriptedTransport:
    """The Meta transport of history_api (upload, delete, count, respond) answering from a list; no network, no cost."""

    def __init__(self, answers: list[Any]):
        self.answers = list(answers)
        self.bodies: list[dict[str, Any]] = []

    def upload(self, path: str) -> str:  # text-only cases never upload
        raise history_api.HistoryError("the eval sends no clips")

    def delete(self, file_id: str) -> None:
        return None

    def count(self, body: dict[str, Any]) -> int:
        self.bodies.append(body)
        return 0

    def respond(self, body: dict[str, Any]) -> Any:
        answer = self.answers.pop(0)
        text = answer if isinstance(answer, str) else json.dumps(answer)
        return {"status": "completed", "usage": {"input_tokens": 0, "output_tokens": 0},
                "output": [{"type": "message", "content": [{"type": "output_text", "text": text}]}]}


def _add_distractors(packed: dict[str, Any], case: dict[str, Any]) -> None:
    """Append the case's distractor digests, labelled as another movement's takes, after everything else.

    A distractor is not in the fact table, so the guard's rule 1 also drops a citation of it."""
    for other in case.get("distractors") or []:
        label = other.get("label", "another movement")
        packed["content"].append({"type": "text", "text": (
            f"Take {other['take']} digest (JSON), from a different movement ({label}), not this student's take of this "
            f"movement: {json.dumps(other['digest'], sort_keys=True, separators=(',', ':'))}")})


def digest_packer(case: dict[str, Any]) -> dict[str, Any]:
    """The request as the product packs it for a report (the 7-field digest), plus the case's distractor digests."""
    facts = case["facts"]
    rows = [{"take": t["take"], "job_id": t.get("job_id"), "duration_s": t["duration_s"], "score": t["score"],
             "private": False, "clip": None} for t in facts["takes"]]
    packed = history_prompt.pack(case["entry_id"], facts, rows, narration=case.get("narration"), video_consent=False)
    _add_distractors(packed, case)
    packed["feature"] = FEATURE
    return packed


def synthetic_analysis(take: dict[str, Any]) -> dict[str, Any]:
    """A SYNTHETIC `analysis.json` for one fixture take, in the shape Part 5 stores: faults with the second, span, size and
    reps, and a score with one compared window per `windows` entry. Nothing here was measured; it only restates the table."""
    faults = [{"measure": f["measure"], "side": f["side"], "at_s": f["at_s"], "follower_t_s": f["span"],
               "magnitude_deg": f["magnitude"], "joint": f.get("joint"), "cue": f.get("cue"), "reps": [0, 1, 2]}
              for f in take["faults"]]
    timeline = [{"t_s": w, "compared": True, "value": take["score"],
                 "misses": [{"measure": f["measure"], "side": f["side"], "at_s": f["at_s"], "points": 5.0}
                            for f in take["faults"] if w[0] <= f["at_s"] <= w[1]]} for w in take["windows"]]
    return {"faults": faults, "score": {"value": take["score"], "grade": take["grade"], "version": take["score_version"],
                                        "timeline": timeline}}


def full_analysis_packer(case: dict[str, Any]) -> dict[str, Any]:
    """The long-context request (TICKET-221): `history_longpack.build` over the synthesized allowlisted analyses, with the
    report instructions as the question. The same schema, guard and canned answers as the digest arm."""
    facts = case["facts"]
    with tempfile.TemporaryDirectory(prefix="history-eval-analysis-") as scratch:
        rows = []
        for t in facts["takes"]:
            path = Path(scratch) / f"take{t['take']}.json"
            path.write_text(json.dumps(synthetic_analysis(t)), encoding="utf-8")
            rows.append({"take": t["take"], "job_id": t.get("job_id"), "at": t["at"], "duration_s": t["duration_s"],
                         "section_key": t["section_key"], "mode": t["mode"], "private": False, "analysis": str(path)})
        packed = history_longpack.build(
            [{"entry_id": case["entry_id"], "rows": rows, "facts": facts, "narration": case.get("narration")}],
            user_id="eval-user", scope=case["entry_id"], question=[history_prompt.INSTRUCTIONS], schema=history_prompt.SCHEMA,
            schema_name=history_prompt.SCHEMA_NAME, feature=FEATURE, prompt_version=FULL_VERSION)
    _add_distractors(packed, case)
    return packed


PACKERS: dict[str, Packer] = {"digest": digest_packer, "full_analysis": full_analysis_packer}


def run_once(case: dict[str, Any], packer: Packer, transport: Any, state: Path | None) -> dict[str, Any]:
    """One ask and one guard pass: `{answer, kept, rejected, usage}` or `{error}`."""
    packed = packer(case)
    try:
        text, usage = history_api.ask(packed, transport=transport, state=state)
        answer = history_guard.parse_answer(text)
        kept, rejected = history_guard.check(answer, packed["facts"], case.get("narration"), history_guard.DEFAULT_WORDS,
                                             clip_takes=packed.get("clip_takes", ()))
    except history_api.HistoryError as exc:
        return {"error": exc.reason, "usage": exc.usage or {}}
    return {"answer": answer, "kept": kept, "rejected": rejected, "usage": usage}


def score_case(case: dict[str, Any], runs: list[dict[str, Any]]) -> dict[str, Any]:
    """Every metric for one case from its runs (the first run scores the single-answer metrics)."""
    good = [r for r in runs if "kept" in r]
    out: dict[str, Any] = {"id": case["id"], "origin": case.get("origin", "synthetic"), "runs": len(runs),
                           "errors": [r["error"] for r in runs if "error" in r]}
    if not good:
        return out
    first, expect, facts = good[0], case["expect"], case["facts"]
    distractors = [d["take"] for d in case.get("distractors") or []]
    out["guard"] = guard_stats(first["answer"], first["rejected"])
    out["rejected"] = first["rejected"]
    out["coverage"] = coverage(first["kept"], facts)
    out["focus"] = focus_correct(first["kept"], expect)
    out["update"] = update_test(first["kept"], expect)
    out["middle"] = middle_cited(first["kept"], expect)
    out["distractor"] = distractor_cited(first["kept"], distractors)
    out["distractor_raw"] = raw_cited(first["answer"], distractors)
    out["abstain"] = abstained(first["kept"], expect)
    out["stability"] = stability([r["kept"] for r in good])
    out["usd"] = round(sum(float(r["usage"].get("usd") or 0) for r in runs), 6)
    return out


def _rate(values: list[bool | None]) -> dict[str, Any]:
    use = [v for v in values if v is not None]
    return {"passed": sum(use), "total": len(use), "rate": round(sum(use) / len(use), 4) if use else None}


def aggregate(results: list[dict[str, Any]]) -> dict[str, Any]:
    """The run's numbers: guard pass rate per rule, coverage, the pass rate of each case-level test, mean stability."""
    scored = [r for r in results if "guard" in r]
    hit, total = sum(r["coverage"]["hit"] for r in scored), sum(r["coverage"]["total"] for r in scored)
    stable = [r["stability"] for r in scored if r["stability"] is not None]
    return {
        "cases": len(results), "scored": len(scored), "errors": sum(len(r["errors"]) for r in results),
        "guard_pass_rate": pass_rates([r["guard"] for r in scored]),
        "coverage": {"hit": hit, "total": total, "rate": round(hit / total, 4) if total else None},
        "focus": _rate([r["focus"] for r in scored]), "update": _rate([r["update"] for r in scored]),
        "middle": _rate([r["middle"] for r in scored]),
        "distractor_never_cited": _rate([None if r["distractor"] is None else not r["distractor"] for r in scored]),
        "abstention": _rate([r["abstain"] for r in scored]),
        "stability": round(sum(stable) / len(stable), 4) if stable else None,
    }


# ----- the run ----------------------------------------------------------------------------------------
def live_allowed(env: dict[str, str] | None = None) -> bool:
    return (os.environ if env is None else env).get(LIVE_ENV) == "1"


def evaluate(cases: list[dict[str, Any]], *, packer: Packer = digest_packer, live: bool = False, runs: int = RUNS,
             state: Path | None = None) -> dict[str, Any]:
    """Run every case `runs` times. Canned mode answers from each case's `answers`; live mode asks the model.

    `state` holds the spend ledger (a throwaway folder in canned mode). A set eval cap stops the run as soon as the
    ledger passes it."""
    if live and not live_allowed():
        raise PermissionError(f"live eval makes paid calls: set {LIVE_ENV}=1 to allow it")
    results, stopped = [], None
    with tempfile.TemporaryDirectory(prefix="history-eval-") as scratch:
        ledger_state = state if live else Path(scratch)
        cap = history_api.feature_cap(FEATURE, "total")
        for case in cases:
            answers = case.get("answers") or [{}]
            transport = None if live else ScriptedTransport([answers[i % len(answers)] for i in range(runs)])
            run_list = []
            for _ in range(runs):
                if cap is not None and history_api.spent_by_feature(history_api.ledger_path(ledger_state)).get(FEATURE, 0) >= cap:
                    stopped = f"stopped before case {case['id']}: the eval cap of ${cap:.2f} is reached"
                    break
                run_list.append(run_once(case, packer, transport, ledger_state))
            if stopped:
                break
            results.append(score_case(case, run_list))
        spend = round(sum(r.get("usd", 0.0) for r in results), 6)
    return {"mode": "live" if live else "canned", "results": results, "metrics": aggregate(results), "spend_usd": spend,
            "stopped": stopped}


def ab(cases: list[dict[str, Any]], packers: dict[str, Packer] | None = None, **kw: Any) -> dict[str, Any]:
    """The same cases under each packer (digest and full analysis by default), metrics side by side."""
    return {name: evaluate(cases, packer=packer, **kw)["metrics"] for name, packer in (packers or PACKERS).items()}


def commit_of(root: Path | None = None) -> str:
    try:
        done = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root or Path(__file__).resolve().parents[2],
                              capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    return done.stdout.strip() or "unknown"


def write_report(run: dict[str, Any], out: Path | str | None = None, root: Path | None = None) -> Path:
    """`progress/history-eval-<date>.json`: commit, prompt version, model, spend and the metrics."""
    root = root or Path(__file__).resolve().parents[2]
    path = Path(out) if out else root / "progress" / f"history-eval-{datetime.now(timezone.utc):%Y-%m-%d}.json"
    doc = {"commit": commit_of(root), "prompt_version": history_prompt.PROMPT_VERSION, "model": history_api.MODEL,
           "date": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), **run}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="history_eval", description=__doc__.splitlines()[0])
    parser.add_argument("--cases", default=str(FIXTURES))
    parser.add_argument("--out", default=None, help="report file (default progress/history-eval-<date>.json)")
    parser.add_argument("--live", action="store_true", help=f"paid calls; needs {LIVE_ENV}=1")
    parser.add_argument("--ab", action="store_true", help="digest against full analysis")
    args = parser.parse_args(argv)
    cases = load_cases(args.cases)
    try:
        run = evaluate(cases, live=args.live)
    except PermissionError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    if args.ab:
        run["ab"] = {"digest": run["metrics"], **ab(cases, {"full_analysis": full_analysis_packer}, live=args.live)}
    path = write_report(run, args.out)
    print(json.dumps({"mode": run["mode"], "spend_usd": run["spend_usd"], "stopped": run["stopped"], **run["metrics"]},
                     indent=2, sort_keys=True))
    print(f"report: {path}")
    return 1 if run["metrics"]["errors"] or run["stopped"] else 0


if __name__ == "__main__":
    sys.exit(main())
