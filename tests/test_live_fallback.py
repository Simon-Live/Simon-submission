"""Live mode end to end, with the network refused (docs/specs/journey-followup.md AC-P01, AC-P05, ADR-0008).

`tests/conftest.py` refuses every connect outside the loopback, so `part5 analyse --live` with a (fake) key file
goes as far as the real HTTP client and no further: each fault's call fails, falls back to its template line and
says why, and the ledger records the call it made. Nothing leaves the machine and no real key is read.
"""
import json
from pathlib import Path

import pytest

from part5 import cli
from part5.phrasing import muse_spark

ROOT = Path(__file__).resolve().parent.parent
LABELS = json.loads((ROOT / "fixtures/input/followers/labels.json").read_text())
TAKE = next(t for t in LABELS["takes"] if t["take_id"].startswith("exercise_front_good_08"))   # two faults
EXPECTED, FOLLOWER = ROOT / TAKE["expected"], ROOT / TAKE["follower"]
SENTINEL = "sentinel-key-do-not-leak"
REFUSED = "muse-spark: request failed (URLError)"


@pytest.fixture
def key_and_ledger(monkeypatch, tmp_path):
    key = tmp_path / "key"
    key.write_text(SENTINEL + "\n")
    ledger = tmp_path / "ledger.jsonl"
    monkeypatch.setenv("PART5_BASETEN_KEY_FILE", str(key))
    monkeypatch.setenv("PART5_BASETEN_USAGE_FILE", str(ledger))
    muse_spark._calls.clear()
    return ledger


def analyse_live(tmp_path, *extra):
    out = tmp_path / "analysis.json"
    code = cli.main(["analyse", "--expected", str(EXPECTED), "--follower", str(FOLLOWER), "--out", str(out), *extra])
    return code, out


def test_ac_p01_live_with_the_network_refused_records_the_fallback_reason_per_fault(key_and_ledger, tmp_path):
    code, out = analyse_live(tmp_path, "--live")
    assert code == 0
    text = out.read_text()
    doc = json.loads(text)
    record = doc["phrasing"]
    assert (record["requested"], record["selected_by"], record["backend"]) == ("muse-spark", "live", "template")
    assert record["fallback_reason"] == REFUSED
    assert len(doc["faults"]) == len(record["faults"]) >= 2
    for fault, entry in zip(doc["faults"], record["faults"]):
        assert entry == {"backend": "template", "model": None, "fallback_reason": REFUSED, "lang": "en",
                         "text": entry["text"]}
        assert fault["coaching"] == fault["text_timed"]   # the template's timed line, not a model's
    assert SENTINEL not in text


def test_ac_p05_each_call_that_was_made_appends_one_ledger_line_without_the_key(key_and_ledger, tmp_path):
    code, out = analyse_live(tmp_path, "--live")
    faults = len(json.loads(out.read_text())["faults"])
    lines = key_and_ledger.read_text().splitlines()
    assert code == 0 and len(lines) == faults
    assert SENTINEL not in key_and_ledger.read_text()
    assert {json.loads(line)["http_status"] for line in lines} == {None}   # no answer ever came back


def test_ac_p01_an_explicit_template_wins_over_live_and_makes_no_call(key_and_ledger, tmp_path):
    code, out = analyse_live(tmp_path, "--live", "--phrasing", "template")
    record = json.loads(out.read_text())["phrasing"]
    assert code == 0 and (record["requested"], record["selected_by"]) == ("template", "flag")
    assert not key_and_ledger.exists()


def test_ac_p01_live_without_a_key_file_falls_back_with_no_key_and_makes_no_call(monkeypatch, tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    monkeypatch.setenv("PART5_BASETEN_USAGE_FILE", str(ledger))
    code, out = analyse_live(tmp_path, "--live")
    record = json.loads(out.read_text())["phrasing"]
    assert code == 0 and record["selected_by"] == "live" and record["fallback_reason"] == "no key"
    assert {e["fallback_reason"] for e in record["faults"]} == {"no key"} and not ledger.exists()
