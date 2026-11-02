"""TICKET-079, AC-Q12: `make report-quality` (part5/quality_report.py) reports the levels per slice, refuses a used held-out seed,
reads Part 7's two takes as their own slice and gates nothing (ADR-0021, docs/specs/quality.md).

The held-out set on disk is not read here (the report is told there is none); a used seed is refused before its takes are read."""
import hashlib
import json
from pathlib import Path

import pytest

from part5 import output, quality, quality_report

ROOT = Path(__file__).resolve().parent.parent
PART7 = ROOT / "fixtures/input/real/part7-check-20261102T021153Z"


@pytest.fixture(scope="module")
def report(tmp_path_factory):
    absent = tmp_path_factory.mktemp("no-heldout")
    return quality_report.build_report(heldout_dir=absent)


def test_seed_5_is_reported_per_light_condition_and_angle(report):
    entry = report["sets"]["seed 5"]
    assert entry["seed"] == 5 and entry["takes"] == 156 + 104   # the committed takes and the regenerated dropout copies
    assert set(entry["conditions"]) == {"good/clean", "good/dropout", "low/clean", "low/dropout"}
    assert set(entry["slices"]) == {f"{c}/{a}" for c in ("good/clean", "low/clean") for a in ("front", "45", "side")} | \
        {f"{c}/{a}" for c in ("good/dropout", "low/dropout") for a in ("45", "side")}


def test_clean_good_light_takes_are_all_ok_and_low_light_takes_are_all_degraded(report):
    c = report["sets"]["seed 5"]["conditions"]
    assert (c["good/clean"]["takes"], c["good/clean"]["ok"]) == (78, 78)
    assert (c["low/clean"]["takes"], c["low/clean"]["degraded"], c["low/clean"]["ok"], c["low/clean"]["major"]) == (78, 78, 0, 0)
    assert report["sets"]["seed 5"]["clean_good_light_not_ok"] == []


def test_the_dropout_copies_take_their_lights_level(report):
    c = report["sets"]["seed 5"]["conditions"]
    assert (c["good/dropout"]["takes"], c["good/dropout"]["ok"]) == (26, 26) or c["good/dropout"]["ok"] == c["good/dropout"]["takes"]
    assert c["low/dropout"]["degraded"] == c["low/dropout"]["takes"]


def test_every_slice_counts_add_up_and_reasons_are_codes(report):
    for entry in report["sets"]["seed 5"]["slices"].values():
        assert entry["ok"] + entry["degraded"] + entry["major"] == entry["takes"]
        assert set(entry["reasons"]) <= {"position_jitter"}   # the clean seed 5 takes carry no conf
        assert entry["position_jitter_mm"]["min"] <= entry["position_jitter_mm"]["median"] <= entry["position_jitter_mm"]["max"]


def test_the_report_names_the_limits_and_the_file_they_came_from(report):
    assert report["thresholds_sha256"] == hashlib.sha256(quality.THRESHOLDS_PATH.read_bytes()).hexdigest()
    assert report["limits"]["position_jitter_mm"] == {"degraded": 21.0, "major": 42.0}
    assert report["format"] == "simon.part5.quality.report.v1" and "never gated" in report["note"]


def test_part7s_two_takes_are_their_own_slice_with_the_file_alone_read(report):
    p7 = report["part7"]
    assert set(p7["takes"]) == {"dark", "clean"} and p7["example"] is None
    for name, entry in p7["takes"].items():
        assert entry["sha256"] == hashlib.sha256((PART7 / name / "follower.json").read_bytes()).hexdigest()
        assert entry["alone"]["version"] == "simon.quality.v1" and "with_example" not in entry
        assert list(entry["alone"]["signals"]) == list(output.QUALITY_SIGNALS)


def test_the_real_lateral_raise_is_reported_with_whether_its_trainer_says_what_it_sees(report):
    real = report["real_lateral_raise"]
    assert real["expected_has_conf"] is False and set(real["takes"]) == {"pexels-40297504", "pexels-8836968"}
    for entry in real["takes"].values():
        assert entry["quality"]["version"] == "simon.quality.v1" and isinstance(entry["warnings"], list)


def test_provenance_records_the_same_hashes_the_report_reads(report):
    text = (PART7 / "PROVENANCE.md").read_text()
    for name, entry in report["part7"]["takes"].items():
        assert entry["sha256"] in text, name


def test_a_used_held_out_seed_is_refused_before_its_takes_are_read(tmp_path):
    (tmp_path / "labels.json").write_text(json.dumps({"seed": 29, "takes": [{"take_id": "never-read"}]}))
    with pytest.raises(quality_report.ReportError, match="has used"):
        quality_report.heldout_labels(tmp_path)
    assert quality_report.main(["--heldout", str(tmp_path)]) == 2


@pytest.mark.parametrize("seed", quality_report.USED_HELDOUT)
def test_every_used_seed_is_refused(tmp_path, seed):
    (tmp_path / "labels.json").write_text(json.dumps({"seed": seed, "takes": []}))
    with pytest.raises(quality_report.ReportError):
        quality_report.heldout_labels(tmp_path)


def test_the_held_out_seed_on_disk_is_not_a_used_one():
    """The report may read it: seed 73 is the one `make check-5` reads for detection but quality never read."""
    assert json.loads((ROOT / "fixtures/input/heldout/labels.json").read_text())["seed"] not in quality_report.USED_HELDOUT


def test_a_set_that_is_not_seed_5_is_refused_as_the_tuning_set():
    with pytest.raises(quality_report.ReportError):
        quality_report.build_report(tuning_dir=ROOT / "fixtures/input/heldout")


def test_main_writes_the_json_and_prints_the_table_and_exits_zero(tmp_path, capsys, monkeypatch, report):
    monkeypatch.setattr(quality_report, "build_report", lambda *args, **kw: report)   # the report fixture is the same run
    out = tmp_path / "report.json"
    assert quality_report.main(["--heldout", str(tmp_path / "none"), "--json-out", str(out)]) == 0
    printed = capsys.readouterr().out
    assert "by light and condition" in printed and "good/clean" in printed and "low/clean" in printed
    assert "Part 7's takes" in printed and "clean good-light takes above ok: 0" in printed
    assert json.loads(out.read_text())["sets"]["seed 5"]["conditions"]["low/clean"]["degraded"] == 78


def test_the_report_does_not_run_in_check_5():
    """make check-5 never imports the report, so its stdout cannot move."""
    import subprocess
    import sys
    shown = subprocess.run([sys.executable, "-c", "import part5.check, sys; print('part5.quality_report' in sys.modules)"],
                           capture_output=True, text=True, cwd=ROOT)
    assert shown.stdout.strip() == "False", shown.stderr
