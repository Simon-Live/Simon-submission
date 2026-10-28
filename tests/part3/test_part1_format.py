"""Part 1's versioned keyframes.json (moalborati/simon-part-1-keyframes 775aa1e).

data/part1-775aa1e-keyframes.example.json is Part 1's contracts/keyframes.example.json at 775aa1e,
byte for byte, taken from a read-only clone. From that commit Part 1 writes
"format": "simon.keyframes/part1"; older files carry no format and are read the same way.
"""
import copy
import json
from pathlib import Path

from part3 import cli, doctor
from part3.views import part4

HERE = Path(__file__).resolve().parent
EXAMPLE = HERE / "data" / "part1-775aa1e-keyframes.example.json"
ROOT = HERE.parents[1]


def _doctor(path, *extra):
    return doctor.main([str(path), *extra, "--json"])


def test_the_example_carries_part1s_format():
    assert json.loads(EXAMPLE.read_text())["format"] == "simon.keyframes/part1"


def test_doctor_names_the_versioned_file_part1_keyframes(capsys):
    code = _doctor(EXAMPLE)
    report = json.loads(capsys.readouterr().out)
    assert code == 0 and report["kind"] == "keyframes-part1" and report["valid"] is True


def test_doctor_reads_the_same_file_without_format_as_before(tmp_path, capsys):
    doc = json.loads(EXAMPLE.read_text())
    doc.pop("format")
    path = tmp_path / "keyframes.json"
    path.write_text(json.dumps(doc))
    code = _doctor(path)
    report = json.loads(capsys.readouterr().out)
    assert code == 0 and report["kind"] == "keyframes-part1"


def test_with_and_without_format_give_the_same_part4_keys():
    doc = json.loads(EXAMPLE.read_text())
    bare = copy.deepcopy(doc)
    bare.pop("format")
    skeleton = cli.process(json.loads((ROOT / "fixtures/input/part2-single/pose3d.json").read_text()))
    a = part4.render(skeleton, keyframes=doc)["keyframes"]
    b = part4.render(skeleton, keyframes=bare)["keyframes"]
    assert [(k["index"], k["name"]) for k in a] == [(k["index"], k["name"]) for k in b] and a
