"""Where a body mask comes in and goes out (TICKET-084, docs/specs/body-mask.md AC-BM-01, AC-BM-07 to AC-BM-09, AC-BM-13):
`part5 analyse --mask` and its --help, the `mask` field of POST api/analyse, the schema, `docs/schemas.md`'s example and the
`doctor --for part7` note."""
import json
import re
from pathlib import Path

import jsonschema
import pytest

from part5 import api, cli, doctor
from part5.mask import CHAINS, PRESETS, parse_mask

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = json.loads((ROOT / "contracts/analysis.schema.json").read_text())
VALIDATOR = jsonschema.Draft202012Validator(SCHEMA)
TAKE = "exercise_front_good_07_knee_caving-left"
EXPECTED = ROOT / "fixtures/input/expected/exercise/animation.json"
FOLLOWER = ROOT / f"fixtures/input/followers/exercise/{TAKE}/skeleton.json"


def analyse_cli(tmp_path, *extra):
    out = tmp_path / "analysis.json"
    code = cli.main(["analyse", "--expected", str(EXPECTED), "--follower", str(FOLLOWER), "--out", str(out), *extra])
    return code, (json.loads(out.read_text()) if out.exists() else None)


# ---------------------------------------------------------------- the command line (AC-BM-01, AC-BM-08)
def test_analyse_help_lists_mask_with_the_names_it_takes(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["analyse", "--help"])
    help_text = " ".join(capsys.readouterr().out.split())
    assert exc.value.code == 0 and "--mask NAMES" in help_text
    assert all(name in help_text for name in (*PRESETS, *CHAINS)) and "body_mask" in help_text


def test_cli_mask_writes_the_block_and_says_the_line(tmp_path, capsys):
    code, doc = analyse_cli(tmp_path, "--mask", "seated")
    out = capsys.readouterr().out
    assert code == 0 and doc["body_mask"] == parse_mask("seated").block() and doc["schema_version"] == "1.14.0"
    assert doc["faults"] == [] and "Legs not scored, by your setting." in out
    assert list(doc)[:4] == ["format", "schema_version", "profile", "body_mask"] and not list(VALIDATOR.iter_errors(doc))


def test_cli_without_mask_writes_no_block(tmp_path, capsys):
    code, doc = analyse_cli(tmp_path)
    assert code == 0 and "body_mask" not in doc and "by your setting" not in capsys.readouterr().out
    assert [(f["measure"], f["side"]) for f in doc["faults"]] == [("knee_valgus", "left")]


@pytest.mark.parametrize("value", ["left_hand", "", "full_body,left_leg"])
def test_cli_bad_mask_exits_2_naming_it_and_writes_nothing(tmp_path, capsys, value):
    with pytest.raises(SystemExit) as exc:
        analyse_cli(tmp_path, "--mask", value)
    err = capsys.readouterr().err
    assert exc.value.code == 2 and "argument --mask: mask: " in err and not (tmp_path / "analysis.json").exists()


# ---------------------------------------------------------------- the API field (AC-BM-09)
def post(payload):
    status, _, out = api.handle("POST", "/api/analyse", json.dumps(payload).encode(), base_path="/")
    return status, json.loads(out)


def request(**extra):
    return {"expected": {"sample": "exercise"}, "follower": {"sample": TAKE}, **extra}


@pytest.mark.parametrize("value,declared", [("seated", ["seated"]), (["left_leg", "right_arm"], ["left_leg", "right_arm"]),
                                            ("left_leg, left_arm", ["left_leg", "left_arm"])])
def test_api_mask_field_masks_and_says_so(value, declared):
    status, body = post(request(mask=value))
    block = body["analysis"]["body_mask"]
    assert status == 200 and block["declared"] == declared and block["source"] == "api"
    assert body["analysis"]["faults"] == [] and not list(VALIDATOR.iter_errors(body["analysis"]))


@pytest.mark.parametrize("payload", [request(), request(mask=None)])
def test_api_mask_field_omitted_or_null_masks_nothing(payload):
    status, body = post(payload)
    assert status == 200 and "body_mask" not in body["analysis"] and body["analysis"]["faults"]


@pytest.mark.parametrize("value,needle", [("left_hand", "unknown name 'left_hand'"), ([], "name a preset"),
                                          (5, "give a preset or chain name"), (["seated", 1], "give a preset"),
                                          ("full_body,seated", "full_body masks nothing")])
def test_api_mask_field_refuses_a_bad_value_with_400_naming_the_field(value, needle):
    status, body = post({**request(mask=value), "follower": {"sample": "no-such-take"}})   # refused before any file
    assert status == 400 and body["error"]["field"] == "mask" and needle in body["error"]["message"]


# ---------------------------------------------------------------- the schema and the docs (AC-BM-07)
def test_the_schema_refuses_a_block_without_its_keys_or_with_an_unknown_chain():
    doc = json.loads((ROOT / "fixtures/output/analysis.no-faults.example.json").read_text())
    good = dict(doc, body_mask=parse_mask("seated").block())
    assert not list(VALIDATOR.iter_errors(good))
    for block in ({k: v for k, v in good["body_mask"].items() if k != "text"},
                  dict(good["body_mask"], not_scored_chains=["left_shin"]), dict(good["body_mask"], source="profile")):
        assert list(VALIDATOR.iter_errors(dict(doc, body_mask=block)))


def test_the_example_in_docs_schemas_md_is_what_seated_writes():
    text = (ROOT / "docs/schemas.md").read_text()
    section = text[text.index("## Body mask (`body_mask`, from 1.14.0)"):]
    example = re.search(r"```json\n\"body_mask\": (\{.*?\})\n```", section, re.S).group(1)
    assert json.loads(example) == parse_mask("seated").block()
    assert "not with wheelchair users or amputees" in section


# ---------------------------------------------------------------- doctor --for part7 (AC-BM-13)
def test_doctor_notes_the_mask_for_part7(tmp_path, capsys):
    code, _ = analyse_cli(tmp_path, "--mask", "left_arm,seated")
    report = doctor.inspect_file(tmp_path / "analysis.json", "part7")
    note = next(n for n in report.notes if n.startswith("body mask"))
    assert code == 0 and report.exit_code == 0
    assert note.startswith("body mask left_arm, seated (body_mask): not scored left_arm, left_forearm, left_leg, right_leg")
    assert '"Left arm and legs not scored, by your setting."' in note and "same mask" in note


def test_doctor_has_no_mask_note_without_a_mask(tmp_path, capsys):
    analyse_cli(tmp_path)
    assert not [n for n in doctor.inspect_file(tmp_path / "analysis.json", "part7").notes if n.startswith("body mask")]
