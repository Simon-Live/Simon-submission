"""One take, one letter (docs/specs/one-letter.md): the score every server surface shows for a take.

The result headline (web/model/score-labels.js `shownScore`) applies the result's caps in its order (Part 5's quality
cap, part7/quality_cap.py; then Part 7's light cap, part7/light.py), then: a take a warning capped shows `score.value`
and `score.grade`; an uncapped take with Part 5's credit block (`score.credit`, simon.credit.v1) shows the credit's
letter and points; any other take shows `score.value` and `score.grade`. This module makes the same decision, held to
the browser's by tests/part7/fixtures/shown-score-vectors.json. Ranking never reads it: `value` is the capped
`score.value` the boards and the hero pick sort by.
"""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any

from part7 import history_store, light as light_mod, quality_cap

LEVELS = ("easy", "normal", "hard")
MODES = ("percent", "points")
DEFAULT_MODE = "points"  # model/score-credit.js DEFAULT_DISPLAY: points first, at the tolerance Part 5 scored
SCORE_GRADES = ((90, "A"), (80, "B"), (70, "C"), (60, "D"), (0, "F"))
CAPTION_CAPPED = "score out of 100"
CAPTION_PLAIN = "out of 100"
CAPTION_PERCENT = "credit earned"
LIGHT_CAP_CODE = "quality_light_dark"  # the code web/light-result.js gives the light cap on the result
_TONE = {"S": "good", "A": "good", "B": "good", "C": "warn", "D": "warn", "E": "bad", "F": "bad"}
# the keys a list row carries (`public`); `warning` names the caps, the row's `score` and `grade` stay as they were
PUBLIC_KEYS = ("letter", "figures", "caption", "unit", "capped", "warning", "measure")
# what the history report's model reads beside Part 5's value and grade (one-letter.md L7)
PROMPT_KEYS = ("letter", "figures", "unit", "capped")


def _num(v: Any) -> float | int | None:
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) else None


def _round(v: float) -> int:
    """JavaScript's Math.round (half up), so 72.5 is 73 on both sides."""
    return math.floor(v + 0.5)


def _js_text(v: float) -> str:
    """JavaScript's String(v): 37.0 is "37"."""
    return str(int(v)) if isinstance(v, float) and v.is_integer() else str(v)


def group_digits(n: float) -> str:
    """20562 as "20,562" (model/score-credit.js groupDigits)."""
    return f"{_round(n):,}"


def tone_of(letter: Any) -> str:
    return _TONE.get(letter, "warn") if isinstance(letter, str) else "warn"


def _capped(analysis: dict[str, Any], light: Any) -> dict[str, Any]:
    """The score block with the quality cap, then the light cap, as web/quality-cap.js and web/light-result.js apply them."""
    score = dict(analysis["score"])
    cap = quality_cap.cap_of(analysis.get("quality"))
    if cap is not None and score["value"] > cap:
        score.update(value=cap, grade="F", capped_by=[*(score.get("capped_by") or []), quality_cap.CAP_CODE])
    if light_mod.level_of(light) == "major" and score["value"] > light_mod.CAP:
        score.update(value=light_mod.CAP, grade="F", capped_by=[*(score.get("capped_by") or []), LIGHT_CAP_CODE])
    return score


def _level_numbers(x: Any) -> dict[str, Any] | None:
    if not isinstance(x, dict):
        return None
    percent, points, most = _num(x.get("percent")), _num(x.get("points")), _num(x.get("max_points"))
    return None if percent is None or points is None or most is None else {"percent": percent, "points": points, "max_points": most}


def _credit_of(score: dict[str, Any]) -> dict[str, Any] | None:
    credit = score.get("credit")
    return credit if isinstance(credit, dict) and _level_numbers(credit) else None


def _levels_of(credit: dict[str, Any]) -> list[str]:
    own = credit.get("tolerance") if isinstance(credit.get("tolerance"), str) else None
    levels = credit.get("levels") if isinstance(credit.get("levels"), dict) else {}
    have = [k for k in LEVELS if k == own or _level_numbers(levels.get(k))]
    return have or ([own] if own else [])


def _pick(credit: dict[str, Any], display: Any) -> tuple[str, str | None]:
    """model/score-credit.js pickDisplay: an unknown mode is the default, a level the credit lacks is the scored one."""
    d = display if isinstance(display, dict) else {}
    mode = d.get("mode") if d.get("mode") in MODES else DEFAULT_MODE
    levels = _levels_of(credit)
    tolerance = credit.get("tolerance") if isinstance(credit.get("tolerance"), str) else None
    level = d.get("level") if d.get("level") in levels else tolerance or (levels[0] if levels else None)
    return mode, level


def _at(credit: dict[str, Any], level: str | None) -> dict[str, Any]:
    if level and level != credit.get("tolerance"):
        x = _level_numbers((credit.get("levels") or {}).get(level) if isinstance(credit.get("levels"), dict) else None)
        if x:
            return x
    return _level_numbers(credit) or {}


def _grades_of(credit: dict[str, Any]) -> list[tuple[float, str]]:
    raw = credit.get("grades") if isinstance(credit.get("grades"), list) else []
    found = [(g[0], g[1]) for g in raw if isinstance(g, list) and len(g) >= 2 and isinstance(g[1], str) and _num(g[0]) is not None]
    return found or list(SCORE_GRADES)


def _letter_for(percent: float, grades: list[tuple[float, str]]) -> str:
    return next((letter for lo, letter in grades if percent >= lo), grades[-1][1])


def _credit_shown(credit: dict[str, Any], display: Any) -> dict[str, Any]:
    mode, level = _pick(credit, display)
    x = _at(credit, level)
    if isinstance(credit.get("grades"), list):
        letter = _letter_for(x["percent"], _grades_of(credit))
    else:
        letter = credit["grade"] if isinstance(credit.get("grade"), str) else "F"
    # measure: the percent at the level shown, what a rank or a best compares (one-letter.md L3)
    if mode == "points":
        return {"letter": letter, "figures": group_digits(x["points"]), "caption": f"of {group_digits(x['max_points'])}", "unit": "points",
                "measure": x["percent"]}
    return {"letter": letter, "figures": f"{_round(x['percent'])}%", "caption": CAPTION_PERCENT, "unit": "percent", "measure": x["percent"]}


def shown(analysis: Any, light: Any = None, display: Any = None) -> dict[str, Any] | None:
    """The take's one score: `{letter, figures, caption, unit, value, capped, warning, tone}`, or None without a
    numeric `score.value`. `analysis` is Part 5's document or its `score` block; `light` is the job result's `light`;
    `display` the viewer's `{mode, level}` (model/score-credit.js), the default being points at the scored tolerance."""
    if isinstance(analysis, dict) and "score" not in analysis and "value" in analysis:
        analysis = {"score": analysis}
    score = analysis.get("score") if isinstance(analysis, dict) else None
    if not isinstance(score, dict) or _num(score.get("value")) is None:
        return None
    score = _capped(analysis, light)
    raw_caps = score.get("capped_by")
    warning = [c for c in raw_caps if isinstance(c, str)] if isinstance(raw_caps, list) and raw_caps else []
    credit = None if warning else _credit_of(score)
    if credit is not None:
        out = _credit_shown(credit, display)
        return {**out, "value": score["value"], "capped": False, "warning": [], "tone": tone_of(out["letter"])}
    letter = score["grade"] if isinstance(score.get("grade"), str) else "F"
    return {"letter": letter, "figures": _js_text(score["value"]), "caption": CAPTION_CAPPED if warning else CAPTION_PLAIN, "unit": "score",
            "value": score["value"], "capped": bool(warning), "warning": warning, "tone": tone_of(letter), "measure": score["value"]}


def rank_of(row: Any) -> float | None:
    """What a rank or a best compares for a row (one-letter.md L3): its `shown` measure (the credit percent shown, or the
    capped score), else its `score` (a row stored before the measure existed); None without either."""
    if not isinstance(row, dict):
        return None
    s = row.get("shown")
    measure = _num(s.get("measure")) if isinstance(s, dict) else None
    return measure if measure is not None else _num(row.get("score"))


def is_capped(row: Any) -> bool:
    """True when a row's shown score is a warning cap's (never the leader, the hero or a featured pick, one-letter.md L6)."""
    s = row.get("shown") if isinstance(row, dict) else None
    return isinstance(s, dict) and s.get("capped") is True


def for_prompt(s: Any) -> dict[str, Any] | None:
    """The shown score as the history report's model reads it: letter, figures, unit and whether a warning capped it."""
    return {k: s[k] for k in PROMPT_KEYS if k in s} if isinstance(s, dict) else None


def numbers_in(s: Any) -> set[float]:
    """The numbers a shown score puts on the page ("16,239", "of 22,367", "73%"), for the report guards' number rule."""
    if not isinstance(s, dict):
        return set()
    text = " ".join(str(s.get(k) or "") for k in ("figures", "caption")).replace(",", "")
    return {round(float(n), 3) for n in re.findall(r"\d+(?:\.\d+)?", text)}


def public(s: dict[str, Any] | None) -> dict[str, Any] | None:
    """The `shown` block a list row carries (web/model/score-labels.js `shownRow` reads it)."""
    return {k: s[k] for k in PUBLIC_KEYS} if s else None


def of_analysis(analysis: Any, light: Any = None) -> dict[str, Any] | None:
    return public(shown(analysis, light))


def of_path(path: Path | str | None, light: Any = None) -> dict[str, Any] | None:
    """The `shown` block of the analysis at `path`, or None when it is missing or unreadable."""
    return of_analysis(history_store.read_json(Path(path)), light) if path else None


def of_take(take: dict[str, Any]) -> dict[str, Any] | None:
    """The `shown` block of a history row (`history_store.takes` or `pending_take`): its own analysis copy, and the light
    level kept with copies made since this block existed (an older copy has none, so no light cap)."""
    return of_path(take.get("analysis"), take.get("light"))


def of_job(job_dir: Path, job: Any, rel: str = "work/follower/analysis.json") -> dict[str, Any] | None:
    """The `shown` block of a finished job: its analysis and its result's light."""
    result = job.get("result") if isinstance(job, dict) and isinstance(job.get("result"), dict) else {}
    return of_path(Path(job_dir) / rel, result.get("light"))
