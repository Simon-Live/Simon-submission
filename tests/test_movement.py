"""Tests for `part7.movement` and the ADR-0004 movement rule (TICKET-012, AC-V1)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from part7 import config, movement


def test_excluded_movements_exact_tuple() -> None:
    expected = (
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
        "lateral raise",
    )
    assert movement.EXCLUDED_MOVEMENTS == expected
    sha = movement.excluded_list_sha()
    assert len(sha) == 64
    for ex in expected:
        assert movement.is_excluded(ex), f"{ex} must be excluded"
        assert movement.is_excluded(ex.upper()), f"{ex.upper()} must be excluded"
        assert movement.is_excluded(ex.replace(" ", "-")), f"{ex} hyphenated must be excluded"

    assert movement.is_excluded("barbell squat")
    assert movement.is_excluded("reverse lunge")
    assert movement.is_excluded("dance routine")
    # TICKET-086: Part 5's own development fixture, so it can never be the held-out movement
    assert movement.is_excluded("lateral-raise")
    assert movement.is_excluded("Lateral raise")
    assert not movement.is_excluded("front-raise")
    assert not movement.is_excluded("overhead-press")
    assert not movement.is_excluded("knee-raise")


def test_candidates_order_and_measures() -> None:
    assert [c["id"] for c in movement.CANDIDATES] == [
        "lateral-raise",
        "front-raise",
        "overhead-press",
        "knee-raise",
    ]
    for cand in movement.CANDIDATES:
        # lateral-raise stays in the ordered rule as a rejected candidate (TICKET-086)
        assert movement.is_excluded(cand["id"]) == (cand["id"] == "lateral-raise")
        assert movement.is_excluded(cand["name"]) == (cand["id"] == "lateral-raise")
        assert cand["measures"]
        for m in cand["measures"]:
            assert m in movement.PART5_MEASURES


def test_manifest_movement_rule_valid() -> None:
    mpath = config.manifest_path()
    assert mpath.exists(), "videos/manifest.json must exist"
    data = json.loads(mpath.read_text(encoding="utf-8"))
    assert data.get("schema") == "part7.videos/1"
    mov = data.get("movement")
    errors = movement.validate_movement(mov)
    assert errors == [], f"Unexpected movement validation errors: {errors}"
    assert mov["id"] == "knee-raise"
    assert mov["name"] == "Standing knee raise"
    assert len(mov["rule"]) == len(movement.CANDIDATES)
    assert [r["verdict"] for r in mov["rule"]] == ["rejected", "rejected", "rejected", "selected"]


def test_validate_movement_rejects_invalid_cases() -> None:
    # Excluded movement id
    bad_excluded = {
        "id": "squat",
        "name": "Squat",
        "rule": [
            {"candidate": "lateral-raise", "verdict": "selected", "reason": "ok"},
            {"candidate": "front-raise", "verdict": "not_evaluated", "reason": "skip"},
            {"candidate": "overhead-press", "verdict": "not_evaluated", "reason": "skip"},
            {"candidate": "knee-raise", "verdict": "not_evaluated", "reason": "skip"},
        ],
    }
    errs = movement.validate_movement(bad_excluded)
    assert any("EXCLUDED_MOVEMENTS" in e for e in errs)

    # Second candidate selected without rejecting first candidate
    bad_order = {
        "id": "front-raise",
        "name": "Front raise",
        "rule": [
            {"candidate": "lateral-raise", "verdict": "not_evaluated", "reason": "skipped early"},
            {"candidate": "front-raise", "verdict": "selected", "reason": "ok"},
            {"candidate": "overhead-press", "verdict": "not_evaluated", "reason": "skip"},
            {"candidate": "knee-raise", "verdict": "not_evaluated", "reason": "skip"},
        ],
    }
    errs_order = movement.validate_movement(bad_order)
    assert any("prior to selected candidate must be rejected" in e for e in errs_order)

    # Valid fallback to second candidate when first is rejected
    valid_second = {
        "id": "front-raise",
        "name": "Front raise",
        "rule": [
            {"candidate": "lateral-raise", "verdict": "rejected", "reason": "no clips"},
            {"candidate": "front-raise", "verdict": "selected", "reason": "ok"},
            {"candidate": "overhead-press", "verdict": "not_evaluated", "reason": "skip"},
            {"candidate": "knee-raise", "verdict": "not_evaluated", "reason": "skip"},
        ],
    }
    assert movement.validate_movement(valid_second) == []


def test_grep_clones_for_movement(tmp_path: Path) -> None:
    parts_root = tmp_path / "parts"
    clean_clone = parts_root / "1@deadbeef1234"
    clean_clone.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=clean_clone, check=True)
    (clean_clone / "README.md").write_text("squat and lunge fixtures\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=clean_clone, check=True)
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "init"],
        cwd=clean_clone,
        check=True,
    )

    summary_clean = movement.check_movement(parts_root=parts_root)
    assert summary_clean["rule_ok"] is True
    assert summary_clean["grep_hits"] == []

    dirty_clone = parts_root / "5@cafebabe5678"
    dirty_clone.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=dirty_clone, check=True)
    (dirty_clone / "rules.py").write_text("CONFIGURED = ['knee-raise']\n", encoding="utf-8")
    subprocess.run(["git", "add", "rules.py"], cwd=dirty_clone, check=True)
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "init"],
        cwd=dirty_clone,
        check=True,
    )

    summary_dirty = movement.check_movement(parts_root=parts_root)
    assert summary_dirty["grep_hits"]
    assert any("5@cafebabe5678:rules.py:1:" in h for h in summary_dirty["grep_hits"])
