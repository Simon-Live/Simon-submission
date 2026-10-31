"""Read additive shared quality files; preserve signals as tips when analysis cannot run.

Only Part 5 can determine major/minor impact. These fallback tips are always minor,
even for severe signals: Part 7's pre-existing fallback score and warning stay unchanged.
"""

from __future__ import annotations

from copy import deepcopy
import json
import math
from pathlib import Path
from typing import Any, Iterable

from part7.quality_constants import QUALITY_FORMAT, QUALITY_TIPS


def read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def people_quality(path: Path) -> dict[str, Any]:
    value = read_object(path).get("people_quality")
    return deepcopy(value) if isinstance(value, dict) else {}


def _quality(doc: dict[str, Any], person_id: str | None) -> dict[str, Any]:
    """Prefer the selected person's signal; never leak another person's problems."""
    if person_id is not None:
        mapping = doc.get("people_quality")
        if isinstance(mapping, dict):
            item = mapping.get(person_id)
            return item if isinstance(item, dict) else {}
        people = doc.get("people")
        if isinstance(people, (list, dict)):
            items = people.values() if isinstance(people, dict) else people
            for person in items:
                if isinstance(person, dict) and str(person.get("id")) == person_id:
                    value = person.get("quality")
                    return value if isinstance(value, dict) else {}
            if isinstance(people, dict) and isinstance(people.get(person_id), dict):
                value = people[person_id].get("quality")
                return value if isinstance(value, dict) else {}
            return {}
    value = doc.get("quality")
    return value if isinstance(value, dict) else {}


def _spans(value: Any) -> list[list[float]]:
    if not isinstance(value, list):
        return []
    return [list(span) for span in value if isinstance(span, (list, tuple)) and len(span) == 2
            and all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) for x in span)
            and 0 <= span[0] <= span[1]]


def fallback_quality(paths: Iterable[Path], person_id: str | None = None) -> dict[str, Any] | None:
    """Merge known signal codes, first source wins, stable code order and original clip times."""
    found: dict[str, dict[str, Any]] = {}
    thresholds: dict[str, Any] = {}
    sources: list[str] = []
    for path in paths:
        quality = _quality(read_object(path), person_id)
        if quality.get("format") not in (None, QUALITY_FORMAT):
            continue
        values = quality.get("issues")
        if not isinstance(values, list):
            continue
        for issue in values:
            if not isinstance(issue, dict):
                continue
            code = issue.get("code")
            if not isinstance(code, str) or code not in QUALITY_TIPS or code in found:
                continue
            tip = QUALITY_TIPS[code]
            if code == "joints_uncertain":
                evidence = issue.get("evidence")
                joints = evidence.get("joints") if isinstance(evidence, dict) else None
                names = [x.replace("_", " ") for x in joints if isinstance(x, str)] if isinstance(joints, list) else []
                tip = tip.format(joints=", ".join(names) or "joints")
            spans = _spans(issue.get("spans_s"))
            item = {**deepcopy(issue), "impact": "minor", "rule": None, "affects": [],
                    "text": tip, "tip": tip, "spans_s": spans}
            item.pop("at_s", None)
            if spans:
                item["at_s"] = max(spans, key=lambda s: s[1] - s[0])[0]
            found[code] = item
        if isinstance(quality.get("thresholds"), dict):
            for key, value in quality["thresholds"].items():
                thresholds.setdefault(key, deepcopy(value))
        producer = quality.get("producer")
        if isinstance(producer, str) and producer not in sources:
            sources.append(producer)
    if not found:
        return None
    return {"format": QUALITY_FORMAT, "source": "+".join(sources) or "part2", "thresholds": thresholds,
            "issues": [found[code] for code in sorted(found)]}
