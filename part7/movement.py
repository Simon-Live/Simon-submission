"""Movement selection rule and candidate validation (ADR-0004, TICKET-012)."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from part7 import config

EXCLUDED_MOVEMENTS: tuple[str, ...] = (
    "squat",
    "seated stretch",
    "cat-cow",
    "step-touch",
    "forward lunge",
    "lunge",
    "jumping jack",
    "side step",
    "arm wave",
    "hip twist",
    "dumbbell deadlift",
    "seated reverse fly",
    "dance",
    # TICKET-086: Part 5 uses it as its real multi-rep development fixture (part5/real.py REPS_SOURCE,
    # fixtures/input/real/lateral-raise), so a part is configured for it and the check-7 grep fires.
    "lateral raise",
)

PART5_MEASURES: tuple[str, ...] = (
    "elbow_flexion",
    "knee_flexion",
    "upper_arm_out",
    "upper_arm_forward",
    "forearm_out",
    "thigh_out",
    "thigh_forward",
    "foot_out",
    "trunk_lean_forward",
    "trunk_lean_side",
    "shoulder_tilt",
    "head_forward",
    "knee_valgus",
)

MIN_PEAK_TO_PEAK_DEG: float = 30.0
MAX_DURATION_S: float = 20.0
MIN_REPS: int = 2
MIN_REP_DURATION_S: float = 1.0

CANDIDATES: list[dict[str, Any]] = [
    {
        "id": "lateral-raise",
        "name": "Lateral raise",
        "search_term": "dumbbell lateral raise",
        "measures": ["upper_arm_out"],
    },
    {
        "id": "front-raise",
        "name": "Front raise",
        "search_term": "dumbbell front raise",
        "measures": ["upper_arm_forward"],
    },
    {
        "id": "overhead-press",
        "name": "Overhead press",
        "search_term": "standing overhead press",
        "measures": ["elbow_flexion", "upper_arm_out"],
    },
    {
        "id": "knee-raise",
        "name": "Standing knee raise",
        "search_term": "standing knee raise",
        "measures": ["thigh_forward", "knee_flexion"],
    },
]

VALID_SELECTED_VERDICTS = {"selected", "accepted", "pass"}
VALID_REJECTED_VERDICTS = {"rejected", "fail"}
VALID_SKIPPED_VERDICTS = {"not_evaluated", "skipped"}


def _normalize(text: str) -> str:
    return " ".join(text.strip().lower().replace("-", " ").replace("_", " ").split())


def excluded_list_sha() -> str:
    """Return the SHA-256 hex digest of the canonical exclusion list."""
    payload = "\n".join(EXCLUDED_MOVEMENTS).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def is_excluded(movement_name_or_id: str) -> bool:
    """Return True if the given movement name or id is in EXCLUDED_MOVEMENTS."""
    norm = _normalize(movement_name_or_id)
    if not norm:
        return True
    for item in EXCLUDED_MOVEMENTS:
        ex_norm = _normalize(item)
        if norm == ex_norm or ex_norm in norm.split() or ex_norm in norm:
            return True
    return False


def get_candidate(candidate_id: str) -> dict[str, Any] | None:
    """Look up a candidate definition by its id."""
    for cand in CANDIDATES:
        if cand["id"] == candidate_id:
            return dict(cand)
    return None


def validate_rule(rule: Any, selected_id: str | None = None) -> list[str]:
    """Validate the `movement.rule` list of candidate verdicts against ADR-0004."""
    errors: list[str] = []
    if not isinstance(rule, list) or not rule:
        return ["movement.rule must be a non-empty list"]

    expected_ids = [c["id"] for c in CANDIDATES]
    actual_ids = [r.get("candidate") if isinstance(r, dict) else None for r in rule]
    if actual_ids != expected_ids:
        errors.append(
            f"movement.rule candidates {actual_ids} must match CANDIDATES order {expected_ids}"
        )

    selected_indices: list[int] = []
    for idx, entry in enumerate(rule):
        if not isinstance(entry, dict):
            errors.append(f"movement.rule[{idx}] must be an object")
            continue
        cand_id = entry.get("candidate")
        verdict = entry.get("verdict")
        reason = entry.get("reason")
        if not isinstance(cand_id, str) or not cand_id.strip():
            errors.append(f"movement.rule[{idx}].candidate must be a non-empty string")
        if not isinstance(verdict, str) or not verdict.strip():
            errors.append(f"movement.rule[{idx}].verdict must be a non-empty string")
        if not isinstance(reason, str) or not reason.strip():
            errors.append(f"movement.rule[{idx}].reason must be a non-empty string")
        if isinstance(verdict, str):
            if verdict in VALID_SELECTED_VERDICTS:
                selected_indices.append(idx)
            elif verdict not in (VALID_REJECTED_VERDICTS | VALID_SKIPPED_VERDICTS):
                errors.append(f"movement.rule[{idx}].verdict '{verdict}' is not a valid verdict")

    if len(selected_indices) != 1:
        errors.append(
            f"movement.rule must have exactly 1 selected candidate, found {len(selected_indices)}"
        )
    else:
        sel_idx = selected_indices[0]
        sel_cand = rule[sel_idx].get("candidate")
        if selected_id is not None and sel_cand != selected_id:
            errors.append(
                f"movement.rule selected candidate '{sel_cand}' does not match movement.id '{selected_id}'"
            )
        for idx in range(sel_idx):
            v = rule[idx].get("verdict") if isinstance(rule[idx], dict) else None
            if v not in VALID_REJECTED_VERDICTS:
                errors.append(
                    f"movement.rule[{idx}] prior to selected candidate must be rejected, got '{v}'"
                )
        for idx in range(sel_idx + 1, len(rule)):
            v = rule[idx].get("verdict") if isinstance(rule[idx], dict) else None
            if v not in VALID_SKIPPED_VERDICTS:
                errors.append(
                    f"movement.rule[{idx}] after selected candidate must be not_evaluated/skipped, got '{v}'"
                )

    return errors


def validate_movement(movement: Any) -> list[str]:
    """Validate a manifest `movement` block against the ADR-0004 movement rule."""
    errors: list[str] = []
    if not isinstance(movement, dict):
        return ["movement must be a JSON object"]

    mov_id = movement.get("id")
    mov_name = movement.get("name")
    rule = movement.get("rule")

    if not isinstance(mov_id, str) or not mov_id.strip():
        errors.append("movement.id must be a non-empty string")
    elif is_excluded(mov_id):
        errors.append(f"movement.id '{mov_id}' is in EXCLUDED_MOVEMENTS")

    if not isinstance(mov_name, str) or not mov_name.strip():
        errors.append("movement.name must be a non-empty string")
    elif is_excluded(mov_name):
        errors.append(f"movement.name '{mov_name}' is in EXCLUDED_MOVEMENTS")

    cand = get_candidate(mov_id) if isinstance(mov_id, str) else None
    if cand is not None:
        measures = cand.get("measures", [])
        if not measures or not all(m in PART5_MEASURES for m in measures):
            errors.append(f"candidate '{mov_id}' measures {measures} are not valid Part 5 measures")

    errors.extend(validate_rule(rule, selected_id=mov_id if isinstance(mov_id, str) else None))
    return errors


# TICKET-086: prose is not tuning. Only code, rules and configuration can overfit a part to the movement.
DOC_SUFFIXES = (".md", ".mdx", ".rst", ".txt", ".adoc")
DOC_DIRS = ("docs", "doc")


def is_doc_path(path: str) -> bool:
    """True for prose (design docs, ADRs, notes); false for code, rules, config and runtime fixtures."""
    parts = path.split("/")
    return path.lower().endswith(DOC_SUFFIXES) or any(p in DOC_DIRS for p in parts[:-1])


def grep_clones_split(
    movement_id: str,
    movement_name: str,
    parts_root: Path | None = None,
) -> tuple[list[str], list[str]]:
    """Grep every part module for the movement's id or name: (code and config hits, doc mentions)."""
    root = parts_root if parts_root is not None else config.modules_dir()
    if not root.exists():
        return [], []
    hits: list[str] = []
    docs: list[str] = []
    terms = []
    for term in (movement_id, movement_name):
        if term and term not in terms:
            terms.append(term)
    for clone_dir in sorted(root.iterdir()):
        if not clone_dir.is_dir() or not (clone_dir / ".git").exists():
            continue
        for term in terms:
            res = subprocess.run(
                ["git", "-C", str(clone_dir), "grep", "-i", "-n", "-F", term],
                capture_output=True,
                text=True,
                check=False,
            )
            if res.returncode == 0 and res.stdout.strip():
                for line in res.stdout.strip().splitlines():
                    target = docs if is_doc_path(line.split(":", 1)[0]) else hits
                    target.append(f"{clone_dir.name}:{line}")
    return hits, docs


def grep_clones_for_movement(
    movement_id: str,
    movement_name: str,
    parts_root: Path | None = None,
) -> list[str]:
    """The gated hits: the movement id or name in a part's code, rules or configuration."""
    return grep_clones_split(movement_id, movement_name, parts_root=parts_root)[0]


def check_movement(
    manifest_file: Path | None = None,
    parts_root: Path | None = None,
) -> dict[str, Any]:
    """Load the manifest and return the movement check summary used by check-7."""
    mpath = manifest_file if manifest_file is not None else config.manifest_path()
    data = json.loads(mpath.read_text(encoding="utf-8"))
    mov = data.get("movement", {})
    errors = validate_movement(mov)
    mov_id = str(mov.get("id", ""))
    mov_name = str(mov.get("name", ""))
    grep_hits, doc_mentions = grep_clones_split(mov_id, mov_name, parts_root=parts_root)
    return {
        "id": mov_id,
        "name": mov_name,
        "rule_ok": len(errors) == 0,
        "errors": errors,
        "excluded_list_sha": excluded_list_sha(),
        "grep_hits": grep_hits,
        "doc_mentions": doc_mentions,
    }
