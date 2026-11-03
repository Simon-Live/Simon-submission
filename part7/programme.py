"""A measure-only home programme: the entry's declared primary measure (docs/specs/progress-sheet.md, TICKET-283).

The person who recorded an entry (its owner in the identity store) may declare which joint angle the programme follows,
one of `rehab_measure.ALL_NAMES`. It lives in `<state>/programmes/<entry_id>.json` as `{primary_measure, at}`; the
owner's id is never written there. Every take of a programme entry is tracked on the progress sheet, whatever mode the
person picked, and a rehab-mode take of any entry is tracked too.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from part7 import history_store, labels, rehab_measure

MSG_MEASURE = "Pick one of the listed joint angles."

# The words the sheet uses for each measure; measured words only, nothing about how it should look.
LABELS = {
    "left_knee_flexion": "left knee bend", "right_knee_flexion": "right knee bend",
    "left_elbow_flexion": "left elbow bend", "right_elbow_flexion": "right elbow bend",
    "left_thigh_forward": "left thigh raised forward", "right_thigh_forward": "right thigh raised forward",
    "left_thigh_out": "left thigh out to the side", "right_thigh_out": "right thigh out to the side",
    "left_upper_arm_out": "left arm out to the side", "right_upper_arm_out": "right arm out to the side",
    "left_upper_arm_forward": "left arm raised forward", "right_upper_arm_forward": "right arm raised forward",
    "trunk_lean_forward": "trunk lean forward",
}
assert set(LABELS) == set(rehab_measure.ALL_NAMES)


def _path(state: Path | str, entry_id: str) -> Path:
    return Path(state) / "programmes" / f"{entry_id}.json"


def get(state: Path | str, entry_id: Any) -> dict[str, Any] | None:
    """`{entry_id, primary_measure, label, at}` of a programme entry, or None."""
    if not isinstance(entry_id, str) or not labels.ENTRY_ID_RE.match(entry_id):
        return None
    doc = history_store.read_json(_path(state, entry_id))
    measure = doc.get("primary_measure") if isinstance(doc, dict) else None
    if measure not in LABELS:
        return None
    return {"entry_id": entry_id, "primary_measure": measure, "label": LABELS[measure], "at": doc.get("at")}


def declared(state: Path | str, entry_id: Any) -> str | None:
    found = get(state, entry_id)
    return found["primary_measure"] if found else None


def save(state: Path | str, entry_id: str, measure: Any) -> dict[str, Any]:
    """Declare (or change) the measure; ValueError with `MSG_MEASURE` for one that is not listed. The caller checks ownership."""
    if measure not in LABELS or not labels.ENTRY_ID_RE.match(entry_id):
        raise ValueError(MSG_MEASURE)
    at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    history_store.write_json(_path(state, entry_id), {"primary_measure": measure, "at": at})
    return get(state, entry_id)  # type: ignore[return-value]


def remove(state: Path | str, entry_id: str) -> bool:
    path = _path(state, entry_id)
    if not labels.ENTRY_ID_RE.match(entry_id) or not path.is_file():
        return False
    path.unlink(missing_ok=True)
    return True


def tracked(take_mode: Any, state: Path | str, entry_id: str) -> bool:
    """True when a take belongs on the progress sheet: a rehab-mode take, or any take of a programme entry."""
    return take_mode == "rehab" or declared(state, entry_id) is not None
