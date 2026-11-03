"""tools/model_import_times.py (TICKET-363, docs/specs/model-import.md AC-T4 to AC-T6)."""

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import model_import_times as mit  # noqa: E402


def model(state: Path, mid: str, doc: dict, name: str = "character.json") -> None:
    d = state / "models" / mid
    d.mkdir(parents=True)
    (d / name).write_text(json.dumps(doc))


def local_fixture(state: Path) -> Path:
    for i, secs in enumerate((10.0, 20.0, 30.0, 40.0, 100.0)):
        model(state, f"a{i}", {"timings": {"upload": 1.0, "autorig": secs}})
    model(state, "b0", {"timings": {"conversion": 8.0}}, "status.json")  # a model still without character.json
    model(state, "c0", {"no": "timings"})
    (state / "models" / "d0").mkdir()  # no record at all
    return state


def rows_of(text: str) -> dict[str, list[str]]:
    return {line.split()[0]: line.split() for line in text.splitlines()}


def test_table_has_count_median_and_p90_per_stage(tmp_path):  # AC-T4
    text = mit.report(local_fixture(tmp_path))
    rows = rows_of(text)
    assert text.splitlines()[0].split() == ["stage", "count", "median", "s", "p90", "s", "serverless", "(Modal)"]
    assert rows["autorig"][:4] == ["autorig", "5", "30.0", "100.0"]
    assert rows["upload"][:4] == ["upload", "5", "1.0", "1.0"]
    assert rows["conversion"][:4] == ["conversion", "1", "8.0", "8.0"]
    assert "image3d" not in rows  # a stage no record holds has no row


def test_without_modal_rows_serverless_says_not_measured(tmp_path):  # AC-T5
    text = mit.report(local_fixture(tmp_path))
    assert text.count("not measured") == 3
    assert "$" not in text and "USD" not in text  # no price is ever printed


def test_modal_rows_are_read_only_when_the_record_says_so(tmp_path):  # AC-T5
    local_fixture(tmp_path)
    model(tmp_path, "m1", {"route": "modal", "timings": {"autorig": 4.0}})
    model(tmp_path, "m2", {"route": "modal", "timings": {"autorig": 6.0}})
    text = mit.report(tmp_path)
    auto = next(line for line in text.splitlines() if line.startswith("autorig"))
    assert auto.split()[:4] == ["autorig", "5", "30.0", "100.0"]  # Modal rows do not move the local figures
    assert "median 5.0, p90 6.0 (n=2)" in auto
    assert text.count("not measured") == 2  # upload and conversion have no Modal row


def test_bad_values_are_skipped_and_empty_state_says_so(tmp_path):
    model(tmp_path, "x", {"timings": {"upload": "fast", "autorig": -1, "avatar": True}})
    assert mit.report(tmp_path) == "no model import timings found\n"


def test_main_exits_2_without_a_models_folder(tmp_path, capsys):  # AC-T6
    assert mit.main(["t", str(tmp_path)]) == 2
    local_fixture(tmp_path)
    assert mit.main(["t", str(tmp_path)]) == 0
    assert "autorig" in capsys.readouterr().out
