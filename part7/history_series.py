"""Magnitude series, plateaus, early signs, tempo and side lines of one entry's takes (docs/specs/history-series.md, TICKET-218).

`build(takes)` is pure: it reads each take's stored `analysis.json` through `history_facts` and answers
`simon.history.series.v1`, with no model and no I/O beyond those files. Like with like (TICKET-206): only takes of the
latest take's section, mode and score version enter a line. A private take, and a take of unknown section, mode or score
version, never does. There is no symmetry percentage, no target line and no ready state anywhere in the output.
"""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from part7 import history_facts

FORMAT = "simon.history.series.v1"
MIN_TAKES = 4        # the chart (and plateau, tempo line) is hidden under this many comparable takes
PLATEAU_TAKES = 4    # a plateau looks at the last this many takes of a line
PLATEAU_DAYS = 2     # ... which must fall on at least this many distinct days
SIDE_NOTE_TAKES = 3  # a side note needs one side in at least this many takes
NOISE_DEG = history_facts.NOISE_BAND["deg"]  # one band for "improved", "fixed" and "plateau" (TICKET-214)
NOISE_M = history_facts.NOISE_BAND["m"]      # metres, for faults that carry `lateral_m` and no `magnitude_deg`
MAX_EARLY_SIGNS = 5
TEMPO_SLOW = 1.15    # Part 5's own cue lines (analysis.schema.json score.tempo)
TEMPO_FAST = 0.85
SIDES = ("left", "right")
_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}")

Key = tuple[str, str]


def _obj(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _day(at: Any) -> str | None:
    return at[:10] if isinstance(at, str) and _DAY.match(at) else None


def _sizes(analysis: dict[str, Any]) -> dict[Key, tuple[float, str]]:
    """`(measure, side) -> (size, unit)` of the largest fault: degrees, else metres (`lateral_m`), else unit `none`."""
    out: dict[Key, tuple[float, str]] = {}
    for raw in analysis.get("faults") or []:
        if not isinstance(raw, dict) or not isinstance(raw.get("measure"), str):
            continue
        key = (raw["measure"], raw["side"] if isinstance(raw.get("side"), str) else "center")
        deg, metres = history_facts._number(raw.get("magnitude_deg")), history_facts._number(raw.get("lateral_m"))
        size = (abs(deg), "deg") if deg is not None else (abs(metres), "m") if metres is not None else (0.0, "none")
        if key not in out or size[0] > out[key][0]:
            out[key] = size
    return out


def _near_misses(analysis: dict[str, Any]) -> dict[Key, float | None]:
    """`(measure, side) -> margin_deg` (None before Part 5 1.12.0) of each near miss; one with a negative margin is left out."""
    return history_facts.near_margins(history_facts._near_misses(analysis))


def _tempo(analysis: dict[str, Any], rehab: bool) -> dict[str, Any]:
    """Take-level tempo. A rep with a null `timing_corr` could not be aligned and is left out; a take whose every rep
    is such has no tempo. Rehab never reports a slow tempo as something to fix (Part 5: 'Slower is fine')."""
    ratio = history_facts._number(_obj(_obj(analysis.get("score")).get("tempo")).get("ratio"))
    reps = [r for r in _obj(_obj(analysis.get("diagnostics")).get("guard")).get("reps") or [] if isinstance(r, dict)]
    used = [r for r in reps if history_facts._number(r.get("timing_corr")) is not None]
    if reps and not used:
        ratio = None
    note = None
    if ratio is not None:
        note = "slow" if ratio > TEMPO_SLOW else "fast" if ratio < TEMPO_FAST else None
    if rehab and note == "slow":
        note = None
    return {"ratio": ratio, "note": note, "reps_used": len(used) if reps else None, "reps_total": len(reps) if reps else None}


def _scope(takes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Hostable takes of the latest take's section, mode and score version, oldest first, each with its analysis extras."""
    open_takes = [t for t in takes if not t.get("private")]
    rows = history_facts.table(open_takes)["takes"]
    latest = rows[-1] if rows else None
    scope = []
    for take, row in zip(open_takes, rows):
        if latest is None or not history_facts.same_scale(row, latest):
            continue
        analysis = history_facts._read(Path(take["analysis"]))
        rehab = row["mode"] == "rehab" or analysis.get("profile") == "rehab"
        row.update(sizes=_sizes(analysis), near=_near_misses(analysis), tempo=_tempo(analysis, rehab), day=_day(row["at"]))
        scope.append(row)
    return scope


def _line(rows: list[dict[str, Any]], measure: str, side: str) -> dict[str, Any]:
    """One line: a point per take. `value` is the size when present, 0 when a take that compared the moment lacks it,
    None when nothing can be said (before it first showed, no size, or a take that did not compare that moment)."""
    first = next((f for f in (history_facts.fault_of(r, measure, side) for r in rows) if f), None)
    unit = next((r["sizes"][(measure, side)][1] for r in rows if r["sizes"].get((measure, side), (0, "none"))[1] != "none"), None)
    points, started = [], False
    for row in rows:
        here = (measure, side) in row["sizes"]
        started = started or here
        size, row_unit = row["sizes"].get((measure, side), (None, None))
        if here:
            value = size if unit and row_unit == unit else None
        elif started and first is not None and history_facts.covers(row, first["at_s"], measure, side):
            value = 0.0
        else:
            value = None
        points.append({"take": row["take"], "at": row["at"], "day": row["day"], "present": here, "value": value})
    return {"side": side, "unit": unit, "points": points, "present_in": [p["take"] for p in points if p["present"]]}


def _plateau(measure: str, line: dict[str, Any]) -> dict[str, Any] | None:
    """No change beyond the noise band across the last PLATEAU_TAKES takes, on at least PLATEAU_DAYS distinct days."""
    last = line["points"][-PLATEAU_TAKES:]
    band = NOISE_DEG if line["unit"] == "deg" else NOISE_M if line["unit"] == "m" else None
    if band is None or len(last) < PLATEAU_TAKES or not all(p["present"] and p["value"] is not None for p in last):
        return None
    days = {p["day"] for p in last if p["day"]}
    values = [p["value"] for p in last]
    spread = max(values) - min(values)
    if len(days) < PLATEAU_DAYS or spread > band:
        return None
    takes = [p["take"] for p in last]
    return {"measure": measure, "side": line["side"], "takes": takes, "days": len(days), "unit": line["unit"], "spread": round(spread, 3),
            "band": band, "text": f"{history_facts._name(measure, line['side'])} has stayed about the same across takes {takes[0]} to {takes[-1]}.",
            "cites": [{"take": t} for t in takes]}


def _early_signs(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """A near miss in a take that is a fault in the next comparable take, citing both; latest first."""
    found = []
    for before, after in zip(rows, rows[1:]):
        for (measure, side), margin in sorted(before["near"].items()):
            fault = history_facts.fault_of(after, measure, side)
            if fault is None or history_facts.fault_of(before, measure, side) is not None:
                continue
            cite = {"take": after["take"], **({"at_s": fault["at_s"]} if fault["at_s"] is not None else {})}
            found.append({"measure": measure, "side": side, "near_take": before["take"], "fault_take": after["take"],
                          **({"margin_deg": margin} if margin is not None else {}),
                          "text": f"{history_facts._name(measure, side)} was a close call in take {before['take']} and shows in take {after['take']}.",
                          "cites": [{"take": before["take"]}, cite]})
    return found[::-1][:MAX_EARLY_SIGNS]


def _side_note(measure: str, lines: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Only when exactly one side is in SIDE_NOTE_TAKES or more takes."""
    heavy = [line for line in lines if line["side"] in SIDES and len(line["present_in"]) >= SIDE_NOTE_TAKES]
    if len(heavy) != 1:
        return None
    side, takes = heavy[0]["side"], heavy[0]["present_in"]
    return {"side": side, "text": f"The {side} {measure.replace('_', ' ')} differs more from the example, in {len(takes)} of your takes.",
            "cites": [{"take": t} for t in takes]}


def _measures(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    keys: list[Key] = []
    for row in rows:
        keys += [k for k in row["sizes"] if k not in keys]
    out, plateaus = [], []
    for measure in dict.fromkeys(m for m, _ in keys):
        sides = [s for m, s in keys if m == measure]
        if any(s in SIDES for s in sides):
            sides = list(SIDES) + [s for s in sides if s not in SIDES]  # left and right are always two lines
        lines = [_line(rows, measure, s) for s in sides]
        for line in lines:
            plateau = _plateau(measure, line)
            line["plateau"] = plateau is not None
            if plateau:
                plateaus.append(plateau)
        out.append({"measure": measure, "lines": lines, "side_note": _side_note(measure, lines)})
    return out, plateaus


def build(takes: list[dict[str, Any]], entry_id: str | None = None) -> dict[str, Any]:
    """The series for `takes` (oldest first, as `history_store.takes` returns them). Under MIN_TAKES comparable takes
    `hidden` is true and `measures`, `plateaus` and `tempo.points` are empty; early signs need only two takes."""
    rows = _scope(takes)
    hidden = len(rows) < MIN_TAKES
    measures, plateaus = ([], []) if hidden else _measures(rows)
    entry = entry_id if entry_id is not None else (takes[0].get("entry_id") if takes else None)
    latest = rows[-1] if rows else None
    return {
        "format": FORMAT, "entry_id": entry, "hidden": hidden, "min_takes": MIN_TAKES,
        "group": {"section": latest["section_key"], "mode": latest["mode"]} if latest else None,
        "score_version": latest["score_version"] if latest else None,
        "takes": [r["take"] for r in rows],
        "measures": measures, "plateaus": plateaus, "early_signs": _early_signs(rows),
        "tempo": {"hidden": hidden, "points": [] if hidden else [
            {"take": r["take"], "at": r["at"], "day": r["day"], **r["tempo"]} for r in rows]},
    }
