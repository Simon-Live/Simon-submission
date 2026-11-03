"""The fact table of a student's takes of one movement, computed with no model (docs/specs/history.md "Facts").

`build(takes)` reads each take's stored `analysis.json` (Part 5's published contract: `faults[].measure`, `side`,
`at_s`, `follower_t_s`, `text_timed`, `cue`, `magnitude_deg`; `score.timeline[].t_s`, `compared`, `misses[].cue`) and
answers `simon.history.facts.v1`. The same table backs the guard's checks and the fallback report.

Like with like (TICKET-206): takes are compared only with takes of the same section and mode. A take whose section or mode
is unknown (a record made before they were kept) is listed but never enters a status, a best or a score line. A fault is
`fixed` only when a later take of the same group compared the moment where it showed and did not have it; otherwise it
is `unverified` and nobody says it is gone.
"""

from __future__ import annotations

import functools
import json
from pathlib import Path
import re
from typing import Any

from part7 import config, history_store, shown_score

FORMAT = "simon.history.facts.v1"
# TICKET-214: "improved" and "fixed" need MIN_GROUP_TAKES takes of one group, and the last two must both sit below the first
# by more than the noise band of the fault's unit. A fault with neither unit is only ever present or absent.
NOISE_BAND = {"deg": 3.0, "m": 0.03}  # degrees (`magnitude_deg`); metres (`lateral_m`, foot_out on one side)
MIN_GROUP_TAKES = 3
# Part 5 changed the meaning of simon.score.v1 (ADR-0013, Part 5 commit 05312b7: the mean of the windows) on 2026-10-30 without a
# version bump, so a v1 take made before that day and one made on or after it are two scales, never one line.
# The day is read from the pinned Part 5's `score_changes_without_a_version` (history-fields.json 1.1.0); this is the fallback.
RESCALE_FALLBACK_DAY = "2026-10-30"
RESCALE_VERSION = "simon.score.v1"
_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SUMMARY_LABEL = "Worked out from your stored takes, without the model."
MAX_TRENDS = 5
WINDOW_SLACK_S = 0.05  # a moment on a compared window's edge still counts as compared


def _rescale_day_from(doc: Any) -> str | None:
    """The newest `when` of a `score_changes_without_a_version` entry that names RESCALE_VERSION, or None."""
    entries = doc.get("score_changes_without_a_version") if isinstance(doc, dict) else None
    days = [e["when"] for e in entries or [] if isinstance(e, dict) and isinstance(e.get("when"), str) and _DAY.match(e["when"])
            and RESCALE_VERSION in str(e.get("what"))]
    return max(days) if days else None


@functools.cache
def rescale_day() -> str:
    """The day the meaning of simon.score.v1 changed: Part 5's own list when the pinned checkout has it, else RESCALE_FALLBACK_DAY."""
    return _rescale_day_from(_read(config.part_dir(5) / "contracts" / "history-fields.json")) or RESCALE_FALLBACK_DAY


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _read(path: Path) -> dict[str, Any]:
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _faults(analysis: dict[str, Any]) -> list[dict[str, Any]]:
    """One fault per (measure, side): the largest, in the order Part 5 listed them."""
    best: dict[tuple[str, str], dict[str, Any]] = {}
    for raw in analysis.get("faults") or []:
        if not isinstance(raw, dict) or not isinstance(raw.get("measure"), str):
            continue
        side = raw.get("side") if isinstance(raw.get("side"), str) else "center"
        item = {
            "measure": raw["measure"], "side": side, "at_s": _number(raw.get("at_s")),
            "span": [x for x in (raw.get("follower_t_s") or []) if _number(x) is not None] or None,
            "text_timed": raw.get("text_timed") if isinstance(raw.get("text_timed"), str) else None,
            "cue": raw.get("cue") if isinstance(raw.get("cue"), str) else None,
            "magnitude": _number(raw.get("magnitude_deg")), "lateral_m": _number(raw.get("lateral_m")),
            "joint": raw.get("joint") if isinstance(raw.get("joint"), str) else None,
            "body_part": raw.get("body_part") if isinstance(raw.get("body_part"), str) else None,
        }
        item["unit"], item["size"] = ("deg", abs(item["magnitude"])) if item["magnitude"] is not None else (
            ("m", abs(item["lateral_m"])) if item["lateral_m"] is not None else (None, None))
        key = (item["measure"], side)
        if key not in best or (item["size"] or 0) > (best[key]["size"] or 0):
            best[key] = item
    return list(best.values())


def _cues(analysis: dict[str, Any]) -> list[str]:
    score = analysis.get("score") if isinstance(analysis.get("score"), dict) else {}
    seen: list[str] = []
    for window in score.get("timeline") or []:
        for miss in (window.get("misses") or []) if isinstance(window, dict) else []:
            cue = miss.get("cue") if isinstance(miss, dict) else None
            if isinstance(cue, str) and cue and cue not in seen:
                seen.append(cue)
    return seen


def _windows(analysis: dict[str, Any]) -> list[list[float]]:
    """The follower-time spans Part 5 actually compared (`score.timeline[].t_s` where `compared` is not false)."""
    score = analysis.get("score") if isinstance(analysis.get("score"), dict) else {}
    found = []
    for window in score.get("timeline") or []:
        span = window.get("t_s") if isinstance(window, dict) and window.get("compared") is not False else None
        if isinstance(span, list) and len(span) == 2 and all(_number(x) is not None for x in span):
            found.append([float(span[0]), float(span[1])])
    return found


def _near_misses(analysis: dict[str, Any]) -> list[dict[str, Any]]:
    """`measure`, `side` and, when Part 5 wrote it (1.12.0), `margin_deg` of each candidate it considered and dropped
    (`diagnostics.near_misses.items`, from 1.8.0)."""
    diag = analysis.get("diagnostics") if isinstance(analysis.get("diagnostics"), dict) else {}
    held = diag.get("near_misses") if isinstance(diag.get("near_misses"), dict) else {}
    out = []
    for i in held.get("items") or []:
        if not isinstance(i, dict) or not isinstance(i.get("measure"), str):
            continue
        item: dict[str, Any] = {"measure": i["measure"], "side": i["side"] if isinstance(i.get("side"), str) else "center"}
        if _number(i.get("margin_deg")) is not None:
            item["margin_deg"] = _number(i.get("margin_deg"))
        out.append(item)
    return out


def near_margins(near: list[dict[str, Any]]) -> dict[tuple[str, str], float | None]:
    """`(measure, side) -> margin_deg` of the near misses a take lists: the largest margin, None when Part 5 gave none
    (a take before 1.12.0). A candidate with a negative margin (short of its threshold) is left out: it was never close
    in this sense. Part 5 writes only margins of 0 or more, so this only guards a future change."""
    out: dict[tuple[str, str], float | None] = {}
    for item in near:
        margin = item.get("margin_deg")
        if margin is not None and margin < 0:
            continue
        key = (item["measure"], item["side"])
        old = out.get(key)
        out[key] = margin if old is None else (old if margin is None else max(old, margin))
    return out


def _rep_numbers(analysis: dict[str, Any]) -> list[int]:
    """The reps (numbered from 1) Part 5 gave data for: `faults[].rep_sizes[].rep` and `score.per_rep[].rep` (1.12.0). Empty for
    an older document or one not compared rep by rep. `faults[].reps` alone does not count: a claim about a rep needs a size or a score."""
    score = analysis.get("score") if isinstance(analysis.get("score"), dict) else {}
    found: set[int] = set()
    sources = [e for f in analysis.get("faults") or [] if isinstance(f, dict) and isinstance(f.get("rep_sizes"), list) for e in f["rep_sizes"]]
    sources += score.get("per_rep") if isinstance(score.get("per_rep"), list) else []
    for entry in sources:
        rep = entry.get("rep") if isinstance(entry, dict) else None
        if isinstance(rep, int) and not isinstance(rep, bool) and rep >= 0:
            found.add(rep + 1)
    return sorted(found)


def _no_person(analysis: dict[str, Any]) -> bool:
    """Part 7's own `no_person` / `no_usable_measures` result: source part7, score 0, grade F, no profile (part7/chain.py)."""
    score = analysis.get("score") if isinstance(analysis.get("score"), dict) else {}
    return (analysis.get("source") == "part7" and score.get("value") == 0 and score.get("grade") == "F"
            and analysis.get("profile") is None)


def _uncapped(analysis: dict[str, Any]) -> dict[str, Any] | None:
    """`{value, grade, fault_cap}` when Part 5's fault cap lowered the score (`score.uncapped`, from schema 1.10.0)."""
    score = analysis.get("score") if isinstance(analysis.get("score"), dict) else {}
    held = score.get("uncapped") if isinstance(score.get("uncapped"), dict) else {}
    value, cap = _number(held.get("value")), _number(score.get("fault_cap"))
    if value is None or cap is None:
        return None
    return {"value": int(value), "grade": held.get("grade") if isinstance(held.get("grade"), str) else None, "fault_cap": int(cap)}


def _obj(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _name_list(value: Any) -> list[str]:
    return [v for v in value if isinstance(v, str)] if isinstance(value, list) else []


def _status_ok(analysis: dict[str, Any]) -> bool:
    """Part 5 compared the movement properly: `status.code == "ok"`. Any other status says nothing about an absent fault."""
    status = analysis.get("status") if isinstance(analysis.get("status"), dict) else {}
    return status.get("code") == "ok"


def _take_row(take: dict[str, Any], analysis: dict[str, Any]) -> dict[str, Any]:
    return {"near_misses": _near_misses(analysis), "rep_numbers": _rep_numbers(analysis), "no_person": _no_person(analysis), "uncapped": _uncapped(analysis),
        "reference": take.get("reference") or "teacher", "take": take["take"], "job_id": take.get("job_id"), "private": bool(take.get("private")), "at": take.get("at"), "score": take.get("score"), "grade": take.get("grade"),
        "duration_s": take.get("duration_s") if history_store.positive(take.get("duration_s")) else history_store.timeline_end(analysis),
        "section_key": take.get("section_key"), "mode": take.get("mode"), "score_version": take.get("score_version"),
        "faults": _faults(analysis), "cues": _cues(analysis), "windows": _windows(analysis), "status_ok": _status_ok(analysis),
        "warned": bool(analysis.get("warnings")), "excluded": _name_list(_obj(_obj(analysis.get("diagnostics")).get("visibility")).get("excluded")),
        "feet_compared": _name_list(_obj(_obj(analysis.get("diagnostics")).get("feet")).get("compared")),
        "score_scale": scale_of({"score_version": take.get("score_version"), "at": take.get("at")}),
        "shown": shown_score.of_analysis(analysis, take.get("light")),  # one-letter.md: what the page shows; the digest keeps score and grade
    }


def group_of(row: dict[str, Any]) -> tuple[str, str, str] | None:
    """`(section, mode, reference)` of a take, or None when section or mode is unknown. A switch of reference starts a new
    group, so a score against the teacher and a score against the student's own rep never read as improved or fixed (ADR-0019)."""
    section, mode = row.get("section_key"), row.get("mode")
    return (section, mode, row.get("reference") or "teacher") if isinstance(section, str) and isinstance(mode, str) else None


def same_group(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return group_of(a) is not None and group_of(a) == group_of(b)


def scale_of(row: dict[str, Any]) -> str | None:
    """The score version, with `@before-rescale` added to a simon.score.v1 take made before the rescale day (its two scales).
    None when the version is unknown. A take with no date is taken as the newer scale."""
    version = row.get("score_version")
    if not isinstance(version, str) or not version:
        return None
    at = row.get("at")
    old = isinstance(at, str) and at[:10] < rescale_day() and version.split(":")[0] == RESCALE_VERSION
    return f"{version}@before-rescale" if old else version


def same_scale(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """Two scores are one line only for the same section, mode and score scale (version, and the v1 rescale day)."""
    scale = scale_of(a)
    return same_group(a, b) and scale is not None and scale == scale_of(b)


FOOT_MEASURES = ("foot_rotation", "ankle_inversion")  # compared only with a feet file (analysis 1.6.0, diagnostics.feet.compared)


def _measure_seen(row: dict[str, Any], measure: str, side: str) -> bool:
    """Part 5's `absent_means.measure`: a measure is fine only if it is not in `diagnostics.visibility.excluded` and, for a
    foot measure, is in `diagnostics.feet.compared`. Both lists name a sided measure as `<side>_<measure>`."""
    name = measure if side in ("center", "") else f"{side}_{measure}"
    if name in (row.get("excluded") or []):
        return False
    return measure not in FOOT_MEASURES or name in (row.get("feet_compared") or [])


def covers(row: dict[str, Any], at_s: float | None, measure: str | None = None, side: str = "center") -> bool:
    """True when the take compared the moment `at_s` (any window when no moment is given), so an absent fault there is fine.

    Part 5's rule for "absent means compared and fine" (contracts/history-fields.json `absent_means`): `status.code` is `ok`,
    the take has no `warnings`, and, when `measure` is given, it is not excluded for visibility and (foot measures) it is in
    `diagnostics.feet.compared`. Otherwise it was not measured."""
    windows = row.get("windows") or []
    if not row.get("status_ok", True) or row.get("warned"):
        return False
    if measure is not None and not _measure_seen(row, measure, side):
        return False
    if at_s is None:
        return bool(windows)
    return any(lo - WINDOW_SLACK_S <= at_s <= hi + WINDOW_SLACK_S for lo, hi in windows)


def fault_of(row: dict[str, Any], measure: str, side: str) -> dict[str, Any] | None:
    return next((f for f in row["faults"] if f["measure"] == measure and f["side"] == side), None)


def states(rows: list[dict[str, Any]], measure: str, side: str) -> list[tuple[dict[str, Any], str]]:
    """`(row, state)` from the first take that has the fault on: `p` present, `a` absent in a take that compared the
    moment, `u` absent in a take that did not (so nothing can be said). Rows are one group, oldest first."""
    out: list[tuple[dict[str, Any], str]] = []
    moment: float | None = None
    started = False
    for row in rows:
        fault = fault_of(row, measure, side)
        if fault is not None:
            started, moment = True, fault["at_s"]
            out.append((row, "p"))
        elif started:
            out.append((row, "a" if covers(row, moment, measure, side) else "u"))
    return out


def _size_in(row: dict[str, Any], measure: str, side: str, unit: str, moment: float | None) -> float | None:
    """How big the fault is in a take: its size, 0 when the take compared the moment and it is gone, None when unknown."""
    fault = fault_of(row, measure, side)
    if fault is not None:
        return fault["size"] if fault["unit"] == unit else None
    return 0.0 if covers(row, moment, measure, side) else None


def _fell(rows: list[dict[str, Any]], found: list[dict[str, Any]], measure: str, side: str) -> str:
    """`no` (no drop beyond the noise), `few` (a drop the takes so far cannot confirm) or `yes` (the last two takes both
    sit below the first by more than the noise band, in a group of at least MIN_GROUP_TAKES takes)."""
    unit = found[0]["unit"]
    if unit is None or any(f["unit"] != unit for f in found):
        return "no"
    band = NOISE_BAND[unit]
    moment = next((f["at_s"] for f in reversed(found) if f["at_s"] is not None), None)
    first = found[0]["size"]
    last_two = [_size_in(r, measure, side, unit, moment) for r in rows[-2:]]
    if last_two[-1] is None or first - last_two[-1] <= band:
        return "no"
    confirmed = len(rows) >= MIN_GROUP_TAKES and all(v is not None and first - v > band for v in last_two)
    return "yes" if confirmed else "few"


def _status(found: list[dict[str, Any]], marks: list[str], rows: list[dict[str, Any]], measure: str, side: str) -> str:
    """`new`, `persistent`, `improved`, `came_back`, `fixed`, `too_few` or `unverified` for one measure on one group's takes."""
    if marks[-1] == "p":
        if "a" in marks:
            return "came_back"
        if len(found) == 1:
            return "new"
        return {"yes": "improved", "few": "too_few"}.get(_fell(rows, found, measure, side), "persistent")
    after = marks[len(marks) - 1 - marks[::-1].index("p"):]
    if "a" not in after or found[0]["unit"] is None:
        return "unverified"  # a fault with no size is only present or absent; nobody calls it fixed
    return "fixed" if _fell(rows, found, measure, side) == "yes" else "too_few"


def measures(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The measure table of one group's takes (oldest first). The last take is `latest`.

    A `fixed` measure whose latest take lists the same measure and side in `diagnostics.near_misses` carries
    `still_close` (the take, the moment it last showed and, from Part 5 1.12.0, `margin_deg`): fixed, but still close to the line.
    A near miss whose `margin_deg` is negative does not count; one with no margin counts, as before."""
    seen: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        for fault in row["faults"]:
            seen.setdefault((fault["measure"], fault["side"]), []).append(
                {"take": row["take"], "at_s": fault["at_s"], "magnitude": fault["magnitude"], "unit": fault["unit"], "size": fault["size"]})
    out = []
    for (measure, side), found in seen.items():
        status = _status(found, [m for _, m in states(rows, measure, side)], rows, measure, side)
        item = {"measure": measure, "side": side, "present_in": [s["take"] for s in found], "status": status,
                "first": found[0], "last": found[-1]}
        close = near_margins(rows[-1].get("near_misses", []))
        if status == "fixed" and (measure, side) in close:
            margin = close[(measure, side)]
            item["still_close"] = {"take": rows[-1]["take"], "at_s": found[-1]["at_s"], **({"margin_deg": margin} if margin is not None else {})}
        out.append(item)
    return out


def build(takes: list[dict[str, Any]], entry_id: str | None = None) -> dict[str, Any]:
    """`table(takes)` plus `series`, the lines, plateaus and early signs of `history_series` (TICKET-218)."""
    from part7 import history_series  # local: history_series imports this module and reads `table`
    return {**table(takes, entry_id), "series": history_series.build(takes, entry_id)}


def table(takes: list[dict[str, Any]], entry_id: str | None = None) -> dict[str, Any]:
    """The fact table for `takes` (oldest first, as `history_store.takes` returns them).

    `group` is the section and mode of the latest take, the only takes `measures`, `best` and the score line use;
    each row says `in_group`. A latest take of unknown section or mode gives no group and no measures.
    """
    rows = [_take_row(t, _read(t["analysis"])) for t in takes]
    latest = rows[-1] if rows else None
    ref = next((r for r in reversed(rows) if not r["no_person"]), None)  # a take with no person found never sets the group
    group = group_of(ref) if ref else None
    for row in rows:
        row["in_group"] = group is not None and group_of(row) == group and not row["no_person"]
    members = [r for r in rows if r["in_group"]]
    scored = [r for r in members if _number(r["score"]) is not None and same_scale(r, ref)]
    best = max(scored, key=lambda r: (shown_score.rank_of(r), -r["take"]), default=None)  # one-letter.md L3: the shown measure
    entry = entry_id if entry_id is not None else (takes[0].get("entry_id") if takes else None)
    return {
        "format": FORMAT, "entry_id": entry, "takes": rows, "measures": measures(members),
        "group": {"section": group[0], "mode": group[1]} if group else None,
        "best": best["take"] if best else None,  # take numbers, as lc-history-meta's guard reads `latest`
        "latest": latest["take"] if latest else None,
    }


# ----- the summary and trends the fallback report shows ---------------------------------------------------
def _name(measure: str, side: str) -> str:
    words = measure.replace("_", " ")
    return words if side in ("center", "") else f"{side} {words}"


def _trend_text(item: dict[str, Any]) -> str:
    name, first, last = _name(item["measure"], item["side"]), item["first"], item["last"]
    at = f" at {last['at_s']:g} s" if last["at_s"] is not None else ""
    if item["status"] == "new":
        return f"{name} shows in take {last['take']}{at}, not before."
    if item["status"] == "fixed":
        close = item.get("still_close")
        if close:
            return f"{name} showed in take {last['take']} and is gone, but take {close['take']} came close to it again."
        return f"{name} showed in take {last['take']} and is not in the latest take."
    if item["status"] == "came_back":
        return f"{name} showed in take {first['take']}, was gone in a take that compared it, and is back in take {last['take']}{at}."
    word = "is smaller in" if item["status"] == "improved" else "is still in"
    return f"{name} {word} take {last['take']}{at}; it first showed in take {first['take']}."


def fallback_summary(facts: dict[str, Any]) -> dict[str, Any]:
    """The labelled fact-table summary: first and latest score of the comparable takes, the best take."""
    latest = next((r for r in reversed(facts["takes"]) if r.get("in_group")), None) or next(
        (r for r in facts["takes"] if r["take"] == facts["latest"]), facts["takes"][-1])
    rows = [r for r in facts["takes"] if r.get("in_group") and same_scale(r, latest) and _number(r["score"]) is not None] or [latest]
    first, last = rows[0], rows[-1]
    best = next((r for r in rows if r["take"] == facts["best"]), None)
    if first is last:
        text = f"Take {last['take']} scored {last['score']}."
    else:
        text = f"Take {first['take']} scored {first['score']} and take {last['take']} scored {last['score']}."
    if best and best["take"] not in (first["take"], last["take"]):
        text += f" The best was take {best['take']}, {best['score']}."
    return {"text": text, "cites": [{"take": first["take"]}, {"take": last["take"]}] if first is not last else [{"take": last["take"]}],
            "source": "fact_table", "label": SUMMARY_LABEL}


def fallback_trends(facts: dict[str, Any]) -> list[dict[str, Any]]:
    """Up to five trends straight from the table, persistent first, then came back, new, improved and fixed.
    An `unverified` measure is not a trend: nobody can say it is gone or still there."""
    order = {"persistent": 0, "came_back": 1, "new": 2, "improved": 3, "fixed": 4}
    items = sorted((m for m in facts["measures"] if m["status"] in order), key=lambda m: order[m["status"]])[:MAX_TRENDS]
    trends = []
    for item in items:
        cite: dict[str, Any] = {"take": item["last"]["take"]}
        if item["last"]["at_s"] is not None:
            cite["at_s"] = item["last"]["at_s"]
        close = item.get("still_close")
        if close:
            cite = {"take": close["take"], **({"at_s": close["at_s"]} if close["at_s"] is not None else {})}
        trends.append({"kind": item["status"], "measure": item["measure"], "side": item["side"],
                       "text": _trend_text(item), "cites": [cite], "source": "fact_table", **({"still_close": True} if close else {})})
    return trends
