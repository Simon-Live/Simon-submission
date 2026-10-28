"""The published contract: schemas, compatibility table, `contract` command, CONTRACT.md (AC-C01, C02, C07)."""

import copy
import json
import re
import subprocess
import sys

import pytest

import contractkit
from conftest import ROOT
from part3 import contract, jsonschema_lite, standard
from part3.joints import BONES, JOINTS
from part3.schema import ContractError, validate_pose3d, validate_skeleton

CONTRACT_MD = ROOT / "CONTRACT.md"
SPEC = ROOT / "docs" / "specs" / "integration-contract.md"
GOLDEN_SKELETONS = sorted((ROOT / "fixtures" / "output").rglob("skeleton.json"))
BASE_ID = "https://github.com/moalborati/simon-part-3-skeleton-consistency/contracts/"
EXPECTED_SCHEMAS = {
    "pose3d": "part2.pose3d/2026-10-28", "keyframes-part1": "part1.keyframes/2026-10-28",
    "keyframes-part4": "simon.keyframes.v1", "body-profile": "simon.body_profile/1",
    "skeleton": "simon.skeleton/1", "skeleton-part4": "simon.skeleton.v1",
    "animation-part5": "simon.animation.v1", "people-index": "simon.part3.people/1",
    "follower-labels": "simon.part3.follower_labels/1",
}
RUN_OPTIONS = ["--in", "--out", "--flip", "--body", "--stature", "--config", "--view", "--keyframes",
               "--keyframes-person", "--keyframes-out", "--fps", "--input-fps", "--person", "--all-people"]
EM_DASH, EN_DASH = chr(0x2014), chr(0x2013)


def cli(*args):
    return subprocess.run([sys.executable, *args], cwd=ROOT, capture_output=True, text=True)


def md_block(name):
    text = CONTRACT_MD.read_text()
    start, end = f"<!-- {name}:begin -->\n", f"<!-- {name}:end -->"
    assert start in text and end in text, f"CONTRACT.md has no {name} block"
    return text.split(start, 1)[1].split(end, 1)[0]


def md_section(title):
    text = CONTRACT_MD.read_text()
    match = re.search(rf"^## {re.escape(title)}\n(.*?)(?=^## |\Z)", text, re.S | re.M)
    assert match, f"CONTRACT.md has no section {title!r}"
    return match.group(1)


# --- AC-C01: the contract command --------------------------------------------------------------

def test_contract_lists_every_schema_and_row(capsys):
    """AC-C01: name, version, direction, file, and the compatibility table."""
    assert contract.main([]) == 0
    out = capsys.readouterr().out
    assert set(contract.SCHEMAS) == set(EXPECTED_SCHEMAS)
    for name, info in contract.SCHEMAS.items():
        line = next(ln for ln in out.splitlines() if ln.startswith(name + " "))
        assert info["version"] in line and info["direction"] in line and info["file"] in line
    for row in contract.compatibility():
        assert row["result"] in out and row["evidence"] in out
    assert "Compatibility" in out


def test_contract_columns_are_aligned(capsys):
    contract.main([])
    lines = capsys.readouterr().out.splitlines()
    first = next(i for i, ln in enumerate(lines) if ln.startswith("name "))
    header, rows = lines[first], lines[first + 1:first + 1 + len(contract.SCHEMAS)]
    starts = [header.index(word) for word in ("name", "version", "direction", "file")]
    for row in rows:
        for start in starts[1:]:
            assert row[start - 2:start] == "  " and row[start] != " ", row


def test_contract_json_parses_and_matches_the_registry(capsys):
    assert contract.main(["--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert [s["name"] for s in doc["schemas"]] == list(contract.SCHEMAS)
    assert {s["name"]: s["version"] for s in doc["schemas"]} == EXPECTED_SCHEMAS
    assert doc["compatibility"] == contract.compatibility()


def test_schema_option_prints_the_file_bytes(capsysbinary):
    for name, info in contract.SCHEMAS.items():
        assert contract.main(["--schema", name]) == 0
        assert capsysbinary.readouterr().out == info["path"].read_bytes()


def test_unknown_schema_exits_2_and_lists_the_names(capsys):
    assert contract.main(["--schema", "nope"]) == 2
    err = capsys.readouterr().err
    assert 'unknown schema "nope"' in err and "skeleton" in err and "Traceback" not in err


def test_bad_option_exits_2(capsys):
    assert contract.main(["--frobnicate"]) == 2
    assert "usage" in capsys.readouterr().err


def test_runs_standalone_as_a_module():
    result = cli("-m", "part3.contract", "--json")
    assert result.returncode == 0, result.stderr
    assert {s["name"] for s in json.loads(result.stdout)["schemas"]} == set(EXPECTED_SCHEMAS)
    assert cli("-m", "part3.contract", "--schema", "nope").returncode == 2


def test_runs_through_the_part3_command():
    result = cli("-m", "part3", "contract", "--json")
    if result.returncode == 2 and "invalid choice" in result.stderr:
        pytest.skip("python3 -m part3 contract is wired by the CLI lane (part3/cli.py)")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["compatibility"] == contract.compatibility()


# --- AC-C02: the schemas themselves ------------------------------------------------------------

def test_every_schema_has_its_identity_fields():
    assert {n: i["version"] for n, i in contract.SCHEMAS.items()} == EXPECTED_SCHEMAS
    for name, info in contract.SCHEMAS.items():
        schema = info["schema"]
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema", name
        assert schema["$id"] == BASE_ID + f"{name}.schema.json", name
        assert schema["title"] and schema["description"], name
        assert schema["x-direction"] in ("input", "output", "both"), name
        assert schema["x-producer"] and isinstance(schema["x-consumers"], list) and schema["x-consumers"], name
        assert schema["type"] == "object", name


def test_every_schema_is_valid_draft_2020_12():
    jsonschema = pytest.importorskip("jsonschema")
    for name, info in contract.SCHEMAS.items():
        jsonschema.Draft202012Validator.check_schema(info["schema"])
        assert jsonschema_lite.unsupported_keywords(info["schema"]) == [], name


def test_every_file_part3_writes_carries_its_version_field():
    no_field = {n for n, i in contract.SCHEMAS.items() if not i["version_field"]}
    assert no_field == {"pose3d", "keyframes-part1"}  # their producers (Parts 2 and 1) write no version field
    for name, info in contract.SCHEMAS.items():
        field, schema = info["version_field"], info["schema"]
        if field:
            assert schema["properties"][field] == {"const": info["version"]}, name
            required = field in schema["required"] or {"required": [field]} in schema.get("anyOf", [])
            assert required, f"{name}: {field} is not required"
    labels_schema = contract.SCHEMAS["follower-labels"]["schema"]
    takes = contractkit.follower_labels()["takes"]
    for key in ("format", "schema"):  # the labels accept the version under either key, and need one
        assert jsonschema_lite.validate({key: "simon.part3.follower_labels/1", "takes": takes}, labels_schema) == []
    assert jsonschema_lite.validate({"takes": takes}, labels_schema)


def test_documents_of_every_kind_validate():
    for name, doc in contractkit.every_kind().items():
        schema = contract.SCHEMAS[name]["schema"]
        assert jsonschema_lite.validate(doc, schema) == [], name


def test_golden_files_validate_against_the_schema_and_partys_own_validator():
    assert GOLDEN_SKELETONS
    schema = contract.SCHEMAS["skeleton"]["schema"]
    for path in GOLDEN_SKELETONS:
        doc = json.loads(path.read_text())
        assert jsonschema_lite.validate(doc, schema) == [], path
        validate_skeleton(doc)


def test_newer_native_blocks_validate_and_older_files_do_too():
    schema = contract.SCHEMAS["skeleton"]["schema"]
    new = contractkit.real_skeleton()
    assert "body" in new and "adapters" in new["input"] and jsonschema_lite.validate(new, schema) == []
    old = copy.deepcopy(new)  # a file written before the body block and input.adapters existed
    del old["body"], old["input"]["adapters"]
    assert jsonschema_lite.validate(old, schema) == []
    new["body"] = contractkit.body_block(profile="file:my-body", selected_by="flag", stature_selected_by="env",
                                         scale=1.0882, stature_m=1.85, symmetrized=True)
    new["input"]["adapters"] = ["flat-joints", "derive-t_ms"]
    new["person"].update(rule="requested", requested=0)
    new["resample"] = {"fps": 30, "source_frames": 107, "method": "linear blend then fixed-length rebuild"}
    new["frames"][3]["source"] = {"frames": [2, 3], "weight": 0.25}
    assert jsonschema_lite.validate(new, schema) == []
    new["frames"][3]["source"]["weight"] = 1.5
    assert jsonschema_lite.validate(new, schema)


def test_people_index_entries_are_either_a_file_or_a_skip():
    schema = contract.SCHEMAS["people-index"]["schema"]
    index = contractkit.people_index()
    assert jsonschema_lite.validate(index, schema) == []
    skipped = {"id": 7, "dir": "person-7", "frames_present": 0, "skipped": "the hips coincide in every frame"}
    assert jsonschema_lite.validate({**index, "people": [skipped]}, schema) == []
    both = {**skipped, "file": "person-7/skeleton.json"}
    assert jsonschema_lite.validate({**index, "people": [both]}, schema)
    neither = {"id": 7, "frames_present": 3}
    assert jsonschema_lite.validate({**index, "people": [neither]}, schema)


@pytest.mark.parametrize("name", ["skeleton", "skeleton-part4", "animation-part5"])
def test_stature_selected_by_is_allowed_in_the_body_block(name):
    doc = contractkit.every_kind()[name]
    schema = contract.SCHEMAS[name]["schema"]
    doc["body"] = contractkit.body_block(stature_selected_by="config", scale=1.0882, stature_m=1.85)
    assert jsonschema_lite.validate(doc, schema) == []
    doc["body"]["profile"] = "file:my-body"
    assert jsonschema_lite.validate(doc, schema) == []
    doc["body"]["stature_selected_by"] = "default"  # a stature is only recorded when someone asked for it
    assert any("stature_selected_by" in e for e in jsonschema_lite.validate(doc, schema))
    doc["body"]["stature_selected_by"] = "flag"
    del doc["body"]["scale"]
    assert any("scale" in e for e in jsonschema_lite.validate(doc, schema))


def test_animation_schema_shares_the_native_body_and_the_part4_frame_definitions():
    native = contract.SCHEMAS["skeleton"]["schema"]["$defs"]
    part4 = contract.SCHEMAS["skeleton-part4"]["schema"]["$defs"]
    assert contract.SCHEMAS["animation-part5"]["schema"]["$defs"]["body"] == native["body"]
    assert contract.SCHEMAS["animation-part5"]["schema"]["$defs"]["coordinate_frame"] == part4["coordinate_frame"]


# --- review residual 10: the part4 schema is generated, not copied -----------------------------------

GOLDEN_PART4 = sorted((ROOT / "fixtures" / "conformance" / "golden").glob("view-part4-*/skeleton.json"))


def test_the_committed_part4_schema_is_the_generated_one_byte_for_byte():
    committed = contract.SCHEMAS["skeleton-part4"]["path"].read_bytes()
    assert committed == contract.render_schema(contract.part4_schema()), \
        "regenerate with: python3 -m part3.contract build-schemas"


def test_the_part4_schema_is_the_native_schema_plus_the_overlay():
    native, part4 = contract.SCHEMAS["skeleton"]["schema"], contract.part4_schema()
    for key, definition in native["properties"].items():
        assert part4["properties"][key] == definition, f"properties.{key} differs between skeleton and part4"
    for name, definition in native["$defs"].items():
        assert part4["$defs"][name] == definition, f"$defs.{name} differs between skeleton and part4"
    added = [key for key in part4["properties"] if key not in native["properties"]]
    assert added == ["format", "coordinate_frame", "root_joint", "virtual_joints", "rest_offsets_m", "timeline",
                     "rig", "keyframes"]
    assert part4["required"] == native["required"] + added
    assert part4["x-simon-version"] == "simon.skeleton.v1" and part4["x-version-field"] == "format"
    assert part4["$id"] == BASE_ID + "skeleton-part4.schema.json"
    assert contract.part4_schema() is not part4 and contract.part4_schema() == part4  # a fresh copy every call


def test_the_part4_overlay_follows_the_rig_and_the_joint_list():
    from part3 import rig
    from part3.joints import COORDINATE_FRAME
    schema = contract.part4_schema()
    key = schema["properties"]["keyframes"]["items"]["properties"]
    assert list(key["joints"]["properties"]) == list(JOINTS) and list(key["conf"]["properties"]) == list(JOINTS)
    assert sorted(key["local_rotations"]["required"]) == sorted(rig.ROTATED)
    rest = schema["properties"]["rest_offsets_m"]["properties"]
    assert {joint: entry["properties"]["parent"]["const"] for joint, entry in rest.items()} == rig.HIERARCHY
    assert schema["$defs"]["coordinate_frame"]["properties"] == {k: {"const": v} for k, v in COORDINATE_FRAME.items()}


def test_the_generated_part4_schema_accepts_the_part4_goldens_and_catches_a_wrong_parent_or_quaternion():
    assert GOLDEN_PART4
    schema = contract.part4_schema()
    for path in GOLDEN_PART4:
        doc = json.loads(path.read_text())
        assert jsonschema_lite.validate(doc, schema) == [], path
        doc["rest_offsets_m"]["neck"]["parent"] = "chest"
        doc["keyframes"][0]["local_rotations"]["pelvis"] = "x"
        errors = jsonschema_lite.validate(doc, schema)
        assert any("rest_offsets_m.neck.parent" in e for e in errors)
        assert any("local_rotations.pelvis" in e for e in errors)
        native = contract.SCHEMAS["skeleton"]["schema"]
        assert jsonschema_lite.validate(doc, native) == []  # the native schema cannot see these fields


def test_build_schemas_writes_the_generated_files(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(contract, "CONTRACTS_DIR", tmp_path)
    assert contract.main(["build-schemas"]) == 0
    written = tmp_path / "skeleton-part4.schema.json"
    assert f"wrote {written}" in capsys.readouterr().out
    assert [p.name for p in tmp_path.iterdir()] == [written.name]
    assert written.read_bytes() == contract.SCHEMAS["skeleton-part4"]["path"].read_bytes()


def test_an_unknown_build_command_exits_2(capsys):
    assert contract.main(["build-everything"]) == 2
    assert "invalid choice" in capsys.readouterr().err


def test_build_schemas_reports_a_folder_it_cannot_write(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(contract, "CONTRACTS_DIR", tmp_path / "missing")
    assert contract.main(["build-schemas"]) == 1
    assert capsys.readouterr().err.startswith("build-schemas: ")


POSE3D_BREAKS = {
    "missing joint": lambda d: d["frames"][2]["people"][0]["joints"].pop("left_knee"),
    "extra joint": lambda d: d["frames"][2]["people"][0]["joints"].update(head_top={"x": 0, "y": 0, "z": 0, "conf": 1}),
    "conf above 1": lambda d: d["frames"][1]["people"][0]["joints"]["nose"].update(conf=1.2),
    "t_ms as text": lambda d: d["frames"][0].update(t_ms="0"),
    "frame as float": lambda d: d["frames"][0].update(frame=1.5),
    "frame as bool": lambda d: d["frames"][0].update(frame=True),
    "people not a list": lambda d: d["frames"][0].update(people={}),
    "id is null": lambda d: d["frames"][0]["people"][0].update(id=None),
    "mirrored as text": lambda d: d.update(mirrored="yes"),
    "joint is a list": lambda d: d["frames"][0]["people"][0]["joints"].update(nose=[0, 0, 0, 1]),
    "missing z": lambda d: d["frames"][0]["people"][0]["joints"]["nose"].pop("z"),
    "frames missing": lambda d: d.pop("frames"),
}


@pytest.mark.parametrize("label", sorted(POSE3D_BREAKS))
def test_pose3d_schema_agrees_with_part3s_validator(label):
    schema = contract.SCHEMAS["pose3d"]["schema"]
    doc = contractkit.pose3d_head(4)
    assert jsonschema_lite.validate(doc, schema) == []
    validate_pose3d(doc)
    POSE3D_BREAKS[label](doc)
    assert jsonschema_lite.validate(doc, schema), f"schema accepts: {label}"
    with pytest.raises(ContractError):
        validate_pose3d(doc)


def _drop(path):
    def apply(doc):
        node = doc
        for step in path[:-1]:
            node = node[step]
        node.pop(path[-1])
    return apply


SKELETON_BREAKS = {
    "wrong schema": lambda d: d.update(schema="simon.skeleton/2"),
    "units changed": lambda d: d["units"].update(length="cm"),
    "up_source unknown": lambda d: d["frame"].update(up_source="camera"),
    "joints reordered": lambda d: d["joints"].reverse(),
    "a bone renamed": lambda d: d["bones"][0].update(name="pelvis_left"),
    "a bone length missing": _drop(("bone_lengths_m", "head")),
    "bone length zero": lambda d: d["bone_lengths_m"].update(head=0),
    "person missing": _drop(("person",)),
    "rule unknown": lambda d: d["person"].update(rule="biggest"),
    "mirror setting unknown": lambda d: d["mirror"].update(setting="maybe"),
    "sha256 short": lambda d: d["input"].update(sha256="abc"),
    "two people in a frame": lambda d: d["frames"][0]["people"].append(copy.deepcopy(d["frames"][0]["people"][0])),
    "flips group unknown": lambda d: d["frames"][0]["people"][0].update(flips_repaired=["torso"]),
    "frames missing": _drop(("frames",)),
}


@pytest.mark.parametrize("label", sorted(SKELETON_BREAKS))
def test_skeleton_schema_agrees_with_part3s_validator(label):
    schema = contract.SCHEMAS["skeleton"]["schema"]
    doc = contractkit.real_skeleton()
    doc["frames"] = doc["frames"][:2]
    assert jsonschema_lite.validate(doc, schema) == []
    SKELETON_BREAKS[label](doc)
    assert jsonschema_lite.validate(doc, schema), f"schema accepts: {label}"
    with pytest.raises((ContractError, KeyError)):
        validate_skeleton(doc)


# --- AC-C07: the compatibility table and CONTRACT.md -------------------------------------------

REQUIRED_ROWS = [
    ("Part 2", "pose3d.json", "Part 3", "works", ""),
    ("Part 2", "several people", "Part 3", "works with option", "--person"),
    ("Part 2", "several people", "Part 3", "works with option", "--all-people"),
    ("Part 2", "without t_ms", "Part 3", "works with option", "--input-fps"),
    ("Part 2", "joints as arrays", "Part 3", "works", ""),
    ("Part 1", "keyframes.json", "Part 3", "works with option", "--keyframes"),
    ("Part 4", "keyframes.json", "Part 3", "works", ""),
    ("Part 3", "native", "Part 4", "rejected", "--view part4 --keyframes"),
    ("Part 3", "part4 view", "Part 4", "works", "--body part4-rig"),
    ("Part 3", "native", "Part 5", "rejected", "--view part5"),
    ("Part 3", "part5 view", "Part 5", "works", ""),
    ("Part 3", "part4 view", "Part 5", "works", ""),
    ("Part 3", "command line", "Part 7", "works", ""),
]


@pytest.mark.parametrize("producer,file,consumer,result,option", REQUIRED_ROWS)
def test_compatibility_has_the_required_row(producer, file, consumer, result, option):
    rows = contract.compatibility()
    assert any(r["producer"] == producer and file in r["file"] and r["consumer"].startswith(consumer)
               and r["result"] == result and option in r["option"] for r in rows), \
        f"no row: {producer} {file} -> {consumer} {result} {option}"


def test_every_row_is_complete_and_names_its_fix():
    keys = {"producer", "file", "version", "consumer", "consumer_version", "result", "option", "evidence"}
    for row in contract.compatibility():
        assert set(row) == keys, row
        assert row["result"] in contract.RESULTS
        assert row["evidence"] and row["producer"] and row["consumer"] and row["version"]
        if row["result"] != "works":
            assert row["option"], f"a {row['result']} row names the option: {row}"
        assert not any("|" in str(v) for v in row.values()), "a pipe would break the Markdown table"


def test_neighbour_commits_are_recorded_as_evidence():
    doc = contract.compatibility_document()
    assert doc["neighbours"] == {"part1": "6fac92f", "part2": "7e11a7f", "part4": "9f4c073",
                                 "part5": "c292a15", "part7": "90aa473"}
    evidence = " ".join(r["evidence"] for r in doc["rows"])
    for part, commit in (("Part 1", "6fac92f"), ("Part 2", "7e11a7f"), ("Part 4", "9f4c073"),
                         ("Part 5", "c292a15"), ("Part 7", "90aa473")):
        assert f"{part} {commit}" in evidence


def test_contract_md_renders_the_same_rows_as_the_json():
    """AC-C07: both tables of CONTRACT.md are the rendering of contracts/ (`build-docs` writes them)."""
    text = CONTRACT_MD.read_text()
    assert contract.render_contract_md(text) == text, "regenerate with: python3 -m part3.contract build-docs"
    assert md_block("compatibility-table") == contract.compatibility_markdown()
    assert md_block("schema-table") == contract.schemas_markdown()


def test_build_docs_restores_a_stale_table_and_is_idempotent(tmp_path, monkeypatch, capsys):
    text = CONTRACT_MD.read_text()
    stale = tmp_path / "CONTRACT.md"
    stale.write_text("\n".join(ln for ln in text.splitlines() if not ln.startswith("| `animation-part5`")) + "\n")
    monkeypatch.setattr(contract, "CONTRACT_MD", stale)
    assert contract.main(["build-docs"]) == 0
    assert f"wrote {stale}" in capsys.readouterr().out and stale.read_text() == text
    assert contract.main(["build-docs"]) == 0 and stale.read_text() == text


def test_build_docs_names_a_missing_table_or_file(tmp_path, monkeypatch, capsys):
    bare = tmp_path / "CONTRACT.md"
    bare.write_text("# no tables here\n")
    monkeypatch.setattr(contract, "CONTRACT_MD", bare)
    assert contract.main(["build-docs"]) == 1
    assert "CONTRACT.md has no schema-table block" in capsys.readouterr().err
    monkeypatch.setattr(contract, "CONTRACT_MD", tmp_path / "nope.md")
    assert contract.main(["build-docs"]) == 1
    assert capsys.readouterr().err.startswith("build-docs: ")


def test_contract_md_table_cells_equal_the_json_values():
    lines = [ln for ln in md_block("compatibility-table").splitlines() if ln.startswith("|")]
    header, rows = lines[0], lines[2:]
    assert [c.strip() for c in header.strip("|").split("|")] == [label for _, label in contract.COMPAT_COLUMNS]
    expected = contract.compatibility()
    assert len(rows) == len(expected)
    for line, row in zip(rows, expected):
        cells = [c.strip().strip("`") for c in line.strip().strip("|").split("|")]
        assert cells == [row[key] for key, _ in contract.COMPAT_COLUMNS]


def test_contract_command_prints_the_rows_of_the_json(capsys):
    contract.main([])
    out = capsys.readouterr().out
    for row in contract.compatibility():
        line = next(ln for ln in out.splitlines() if row["file"] in ln and row["consumer"] in ln
                    and row["result"] in ln and row["version"] in ln)
        assert row["producer"] in line and (row["option"] or "-") in line


# --- CONTRACT.md content -----------------------------------------------------------------------

def test_contract_md_has_the_required_sections():
    headings = re.findall(r"^## (.+)$", CONTRACT_MD.read_text(), re.M)
    for title in ("Check a file now", "Files and schemas", "Compatibility", "Coordinate frame and units",
                  "The 17 joints", "The 18 bones", "The command line", "Body profile selection",
                  "Output views", "Version policy", "Open question to Part 4", "How to integrate in five steps"):
        assert title in headings


def test_contract_md_lists_every_schema_file():
    text = CONTRACT_MD.read_text()
    for info in contract.SCHEMAS.values():
        assert info["file"] in text and info["version"] in text


def test_contract_md_states_the_frame_the_joints_and_the_bones():
    frame = md_section("Coordinate frame and units")
    for word in ("hip midpoint", "metres", "degrees", "subject's own left", "`y` is up", "anterior", "world_up"):
        assert word in frame
    joints = md_section("The 17 joints")
    assert [m for m in re.findall(r"`(\w+)`", joints)] == list(JOINTS)
    bones = md_section("The 18 bones")
    lengths = standard.bone_lengths()
    rows = [ln for ln in bones.splitlines() if re.match(r"\| \d+ \|", ln)]
    assert len(rows) == 18
    for line, (name, start, end) in zip(rows, BONES):
        assert [c.strip().strip("`") for c in line.strip("|").split("|")][1:] == \
            [name, start, end, f"{lengths[name]:.4f}"]


def test_contract_md_documents_every_run_option():
    section = md_section("The command line")
    for option in RUN_OPTIONS:
        assert f"| `{option}` |" in section, option
    block = section.split("```")[1]
    for option in RUN_OPTIONS:
        assert option in block, option
    assert "python3 -m part3 contract [--json] [--schema <name>]" in block
    assert "python3 -m part3 doctor <file> [--for part3|part4|part5] [--json]" in block


@pytest.mark.skipif(not SPEC.exists(), reason="the spec is not part of the published tree")
def test_contract_md_options_equal_the_specs_command_line():
    block = SPEC.read_text().split("### Command line\n```\n", 1)[1].split("```", 1)[0]
    spec_options = set(re.findall(r"--[a-z-]+", block.split("python3 -m part3 contract")[0]))
    section = md_section("The command line")
    doc_options = set(re.findall(r"--[a-z-]+", section.split("python3 -m part3 contract")[0]))
    assert doc_options == spec_options


def test_contract_md_states_profile_precedence_in_order():
    section = md_section("Body profile selection")
    positions = [section.index(marker) for marker in
                 ("`--body`", "`PART3_BODY`", "config file", "`body=`", "`simon-standard`")]
    assert positions == sorted(positions)
    for word in ("`--stature`", "`PART3_STATURE`", "body.selected_by", "contracts/body-profile.schema.json"):
        assert word in section


def test_contract_md_states_the_version_policy_and_the_open_question():
    policy = md_section("Version policy")
    assert "only adds fields keeps the version" in policy and "removes or renames a field bumps the version" in policy
    question = md_section("Open question to Part 4")
    for word in ("rig.fit", "`--body part4-rig`", "chest", "head joint", "per-key rest offsets", "1 mm"):
        assert word in question


def test_the_part4_view_row_and_contract_md_state_the_180_degree_condition():
    """Review B2: Part 4 accepts the view only when no joint turns over 180 degrees between neighbouring keys."""
    row = next(r for r in contract.compatibility() if "part4 view" in r["file"] and r["consumer"] == "Part 4")
    assert row["result"] == "works"
    for word in ("180 degrees", "neighbouring keys", "rotation-vector space", "T-pose", "names the joint"):
        assert word in row["evidence"], word
    for section in ("Output views", "Open question to Part 4"):
        text = md_section(section)
        for word in ("180 degrees", "rotation-vector space", "T-pose", "refuses to write"):
            assert word in text, (section, word)
    assert "left_shoulder turns 329.6 degrees between keys 30 and 40" in md_section("Open question to Part 4")


def test_contract_md_points_the_part4_rules_at_doctor_not_at_part3_schema():
    """Review residual 1: `python3 -m part3.schema` checks the native skeleton, not key order, key times or FK."""
    paragraphs = CONTRACT_MD.read_text().split("\n\n")
    paragraph = next(p for p in paragraphs if p.startswith("A schema cannot say everything."))
    assert "python3 -m part3 doctor <skeleton.json> --for part4" in paragraph
    assert "counts as a rejection" in paragraph
    own = paragraph.split("python3 -m part3.schema")[1].split("`doctor` also")[0]
    assert "native skeleton only" in own
    for rule in ("key order", "key times", "forward kinematics"):
        assert rule not in own, rule
    assert "simon.skeleton.v1 (not written by Part 3)" in CONTRACT_MD.read_text()


def test_contract_md_has_five_integration_steps():
    steps = re.findall(r"^(\d)\. ", md_section("How to integrate in five steps"), re.M)
    assert steps == ["1", "2", "3", "4", "5"]


def test_contract_md_example_is_what_doctor_prints(tmp_path, capsys):
    from part3 import doctor
    path = tmp_path / "skeleton.json"
    path.write_text(json.dumps(contractkit.real_skeleton()))
    doctor.main([str(path), "--for", "part5"])
    printed = capsys.readouterr().out.splitlines()[1:]  # the first line holds the temp path
    example = md_section("Check a file now").split("```")[3].strip("\n").splitlines()
    assert example[0] == "$ python3 -m part3 doctor skeleton.json --for part5"
    assert example[2:] == printed


def test_published_text_has_no_dash_characters():
    code = [ROOT / "part3" / "contract.py", ROOT / "part3" / "doctor.py", ROOT / "part3" / "jsonschema_lite.py"]
    prose = [CONTRACT_MD, *(ROOT / "contracts").glob("*.json")]
    for path in [*code, *prose]:
        text = path.read_text()
        assert EM_DASH not in text and EN_DASH not in text, path
    for path in prose:  # code may subtract; prose may not use a spaced hyphen as a dash
        assert " - " not in path.read_text().replace("\n - ", "\n"), f"{path}: a spaced hyphen stands in for a dash"


# --- review round 2, R8: the Part 5 fault-name table says how each side measures ----------------------------------

def test_the_part5_fault_table_pairs_each_kit_type_with_its_measure_on_both_sides():
    from part3 import followers

    section = md_section("Conformance kit and Part 5 fault names")
    rows = {m.group(1): m.group(0) for m in re.finditer(r"^\| `(\w+)` \|.*$", section, re.M) if m.group(1) != "correct"}
    assert set(rows) == set(followers.KINDS)
    for fault, kind in followers.KINDS.items():
        assert f"`{kind.measure}`" in rows[fault], fault  # the measure the kit writes into labels.json
    closest = {"feet_wide": ("foot_out", "thigh_direction"), "elbows_out": ("arms_wider", "upper_arm_direction"),
               "shallow_squat": ("knees_shallow", "knee_flexion")}
    for fault, names in closest.items():  # Part 5's labels.json types and measures (c292a15)
        assert all(f"`{name}`" in rows[fault] for name in names), fault
    assert "none (Part 5 has no knee-valgus type)" in rows["knee_caving"]
    assert "Closest Part 5 `type`" in section


def test_the_part5_fault_table_does_not_claim_part5_reads_the_kit_labels():
    section = md_section("Conformance kit and Part 5 fault names")
    assert "Part 5 can read either name list" not in section
    assert "does not read these labels" in section and "own measures" in section
    assert "a size in one is not a size in the other" in section  # feet_wide is metres, foot_out is degrees
