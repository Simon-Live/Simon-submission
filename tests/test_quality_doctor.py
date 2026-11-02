"""TICKET-079, AC-Q10: `part5 doctor <analysis.json> --for part7` notes the `quality` block (ADR-0021): its level, its reasons
and, for `major`, the cap of 59 that is reported and not applied. A document without the block is noted as not assessed."""
import copy
import json
from pathlib import Path

from part5 import cli

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = json.loads((ROOT / "fixtures/output/analysis.example.json").read_text())
SIGNALS = {"unseen_joint_share": None, "missing_joint_share": 0.0, "missing_frame_share": 0.0, "hidden_measure_share": None,
           "position_jitter_mm": 12.3, "heading_offset_deg": 1.2}   # the last from 1.14.0 (TICKET-086)
WORDS = "Joint positions shook by about 50 mm from one frame to the next, most at the left wrist."
REASON = {"code": "position_jitter", "words": WORDS, "value": 50.0, "threshold": 42.0, "joint": "left_wrist"}
BLOCKS = {
    "ok": {"version": "simon.quality.v1", "level": "ok", "reasons": [], "signals": SIGNALS, "score_cap": None},
    "degraded": {"version": "simon.quality.v1", "level": "degraded", "reasons": [{**REASON, "value": 25.0, "threshold": 21.0}],
                 "signals": SIGNALS, "score_cap": None},
    "major": {"version": "simon.quality.v1", "level": "major", "reasons": [REASON], "signals": SIGNALS, "score_cap": 59},
}


def doctor(tmp_path, capsys, quality="absent"):
    doc = copy.deepcopy(EXAMPLE)
    doc.pop("quality", None)
    if quality != "absent":
        doc["quality"] = quality
    path = tmp_path / "analysis.json"
    path.write_text(json.dumps(doc))
    code = cli.main(["doctor", str(path), "--for", "part7"])
    return code, capsys.readouterr().out


def test_a_document_without_the_block_is_noted_as_not_assessed(tmp_path, capsys):
    code, out = doctor(tmp_path, capsys)
    assert code == 0
    assert "no quality block: how well the camera saw the take was not assessed" in out and "not as ok" in out


def test_ok_is_noted_and_adds_no_reason(tmp_path, capsys):
    code, out = doctor(tmp_path, capsys, BLOCKS["ok"])
    assert code == 0 and "quality ok: no signal reached a limit (quality is reported only)" in out
    assert "quality reason" not in out and "no quality block" not in out


def test_degraded_is_noted_with_its_reason_and_no_cap(tmp_path, capsys):
    code, out = doctor(tmp_path, capsys, BLOCKS["degraded"])
    assert code == 0
    assert "quality degraded: show the reasons and treat the result with care (quality is reported only, no cap)" in out
    assert f"quality reason position_jitter: {WORDS}" in out
    assert "score_cap" not in out


def test_major_is_noted_with_the_cap_reported_and_not_applied_and_the_score_it_leaves_alone(tmp_path, capsys):
    code, out = doctor(tmp_path, capsys, BLOCKS["major"])
    assert code == 0
    value = EXAMPLE["score"]["value"]
    assert f"quality major: score_cap 59 is reported and not applied (score.value is {value}); apply it yourself" in out
    assert f"quality reason position_jitter: {WORDS}" in out


def test_a_block_that_contradicts_itself_is_rejected_for_part7(tmp_path, capsys):
    code, out = doctor(tmp_path, capsys, {**BLOCKS["major"], "score_cap": None})
    assert code == 1 and "score_cap" in out


def test_the_notes_come_through_json_too(tmp_path, capsys):
    doc = copy.deepcopy(EXAMPLE)
    doc["quality"] = BLOCKS["major"]
    path = tmp_path / "analysis.json"
    path.write_text(json.dumps(doc))
    assert cli.main(["doctor", str(path), "--for", "part7", "--json"]) == 0
    notes = json.loads(capsys.readouterr().out)["notes"]
    assert any(n.startswith("quality major: score_cap 59 is reported and not applied") for n in notes)
