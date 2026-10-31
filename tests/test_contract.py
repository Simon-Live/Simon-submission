"""Downstream contract (CONTRACT.md): the four published schemas, the Part 3 consumer copy, the
`contract` command, NaN and infinity, backward compatibility and `make check-2-contract`."""
import copy
import hashlib
import json
import re
import shlex
import subprocess
import sys
from pathlib import Path

import pytest
from test_canonical import _body3d
from test_multi3d import _two_person_body3d

from part2 import cli, contract, schema
from part2.canonical import convert
from part2.joints import CANONICAL
from part2.multi3d import write_pose_streams
from part2.schema import validate_pose3d, validate_tracks

ROOT = Path(__file__).resolve().parent.parent
POSE3D = sorted((ROOT / "fixtures" / "output").rglob("pose3d*.json"))
TRACKS = sorted((ROOT / "fixtures" / "output").rglob("tracks.json"))
COMMITTED = contract.committed_files(ROOT)
NAN, INF = float("nan"), float("inf")


def _ids(paths):
    return [str(p.relative_to(ROOT)) for p in paths]


def _pose():
    return convert(_body3d([0, 10]))[0]


def _camera():
    return copy.deepcopy(convert(_body3d([0, 10]))[1])  # convert shares K with test_canonical's module-level K


def _tracks():
    person = {"id": 0, "bbox": [1.0, 2.0, 3.0, 4.0], "mask_rle": {"size": [4, 5], "counts": "abc"}, "confidence": 0.9}
    return {"frames": [{"frame": 0, "people": [person]}, {"frame": 1, "people": []}]}


def _frames():
    return {"source": "clip.mp4", "t0_pts_ms": 0.0, "frames": [
        {"frame": 0, "t_ms": 0.0, "file": "000000.jpg"}, {"frame": 1, "t_ms": 100.0, "file": "000001.jpg"}]}


DOCS = {"pose3d": _pose, "tracks": _tracks, "camera": _camera, "frames": _frames}


# --- AC-C01: schemas ----------------------------------------------------------------------------

@pytest.mark.parametrize("kind", contract.KINDS)
def test_each_schema_is_draft_2020_12_with_id_title_and_version(kind):
    s = json.loads((ROOT / "contracts" / f"{kind}.schema.json").read_text())
    assert s["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert s["$id"].endswith(f"/{kind}.schema.json") and s["title"]
    assert s["x-simon-version"] == f"part2.{kind}/2026-10-28"
    assert contract.version(kind) == s["x-simon-version"]


def test_a_committed_file_exists_for_every_kind_that_has_one():
    assert {kind for _, kind in COMMITTED} == set(contract.KINDS)
    assert len(POSE3D) >= 3 and len(TRACKS) >= 2


@pytest.mark.parametrize("path, kind", COMMITTED, ids=_ids([p for p, _ in COMMITTED]))
def test_committed_file_validates_against_its_schema(path, kind):
    contract.validate(json.loads(path.read_text()), kind)


@pytest.mark.parametrize("kind", contract.KINDS)
def test_the_synthetic_documents_validate(kind):
    contract.validate(DOCS[kind](), kind)


def _set(path, value):
    def apply(doc):
        node = doc
        for step in path[:-1]:
            node = node[step]
        node[path[-1]] = value
    return apply


def _pop(path):
    def apply(doc):
        node = doc
        for step in path[:-1]:
            node = node[step]
        del node[path[-1]]
    return apply


NOSE = ["frames", 0, "people", 0, "joints", "nose"]
TRACK = ["frames", 0, "people", 0]
MUTATIONS = [  # (kind, what, mutation, the path the error must name)
    ("pose3d", "missing t_ms", _pop(["frames", 0, "t_ms"]), "pose3d.frames[0].t_ms"),
    ("pose3d", "missing joints", _pop(["frames", 0, "people", 0, "joints"]), "people[0].joints"),
    ("pose3d", "wrong type frame", _set(["frames", 0, "frame"], "0"), "pose3d.frames[0].frame"),
    ("pose3d", "wrong type x", _set(NOSE + ["x"], "1"), "joints.nose.x"),
    ("pose3d", "NaN conf", _set(NOSE + ["conf"], NAN), "joints.nose.conf"),
    ("pose3d", "infinite y", _set(NOSE + ["y"], INF), "joints.nose.y"),
    ("pose3d", "conf above 1", _set(NOSE + ["conf"], 1.5), "joints.nose.conf"),
    ("pose3d", "mirrored as text", _set(["mirrored"], "yes"), "pose3d.mirrored"),
    ("pose3d", "t0_pts_ms as text", _set(["t0_pts_ms"], "0"), "pose3d.t0_pts_ms"),
    ("pose3d", "provenance as a list", _set(["provenance"], []), "pose3d.provenance"),
    ("pose3d", "NaN in an extra key", _set(["extra"], {"a": [1, NAN]}), "pose3d.extra.a[1]"),
    ("tracks", "missing bbox", _pop(TRACK + ["bbox"]), "tracks.frames[0].people[0].bbox"),
    ("tracks", "wrong type bbox", _set(TRACK + ["bbox"], "1 2 3 4"), "people[0].bbox"),
    ("tracks", "negative width", _set(TRACK + ["bbox"], [1, 2, -3, 4]), "bbox[2]"),
    ("tracks", "NaN bbox", _set(TRACK + ["bbox"], [NAN, 2, 3, 4]), "bbox[0]"),
    ("tracks", "infinite confidence", _set(TRACK + ["confidence"], INF), "confidence"),
    ("tracks", "empty counts", _set(TRACK + ["mask_rle", "counts"], ""), "counts"),
    ("tracks", "zero mask size", _set(TRACK + ["mask_rle", "size"], [0, 5]), "size[0]"),
    ("tracks", "NaN t0_pts_ms", _set(["t0_pts_ms"], NAN), "tracks.t0_pts_ms"),
    ("camera", "missing K", _pop(["K"]), "camera.K"),
    ("camera", "short K row", _set(["K", 0], [1, 2]), "camera.K[0]"),
    ("camera", "NaN t", _set(["frames", 0, "people", 0, "t", 1], NAN), "camera.frames[0].people[0].t[1]"),
    ("camera", "zero image size", _set(["image_size"], [0, 720]), "camera.image_size[0]"),
    ("frames", "missing file", _pop(["frames", 0, "file"]), "frames.frames[0].file"),
    ("frames", "t_ms as text", _set(["frames", 1, "t_ms"], "100"), "frames.frames[1].t_ms"),
    ("frames", "NaN t_ms", _set(["frames", 1, "t_ms"], NAN), "frames.frames[1].t_ms"),
    ("frames", "NaN t0_pts_ms", _set(["t0_pts_ms"], INF), "frames.t0_pts_ms"),
]


@pytest.mark.parametrize("kind, what, mutate, where", MUTATIONS, ids=[f"{m[0]}-{m[1]}" for m in MUTATIONS])
def test_a_mutated_copy_fails_with_the_path_named(kind, what, mutate, where):
    doc = DOCS[kind]()
    mutate(doc)
    with pytest.raises(contract.ContractError) as e:
        contract.validate(doc, kind)
    assert where in str(e.value) and e.value.path in str(e.value) and e.value.msg


@pytest.mark.parametrize("doc, message", [
    ([], "pose3d: expected object"), ({}, r"pose3d\.frames: required"), ({"frames": 3}, r"pose3d\.frames: expected array"),
    ({"frames": [3]}, r"pose3d\.frames\[0\]: expected object"), (None, "pose3d: expected object"),
])
def test_a_document_of_the_wrong_shape_is_a_contract_error(doc, message):
    with pytest.raises(contract.ContractError, match=message):
        contract.validate(doc, "pose3d")


def test_unknown_kind_names_the_choices():
    with pytest.raises(contract.ContractError, match="pose3d, tracks, camera, frames"):
        contract.validate({}, "skeleton")


def test_sequence_rules_for_every_kind_with_frames():
    for kind in ("tracks", "frames", "camera"):
        doc = DOCS[kind]()
        doc["frames"][1]["frame"] = 0
        with pytest.raises(contract.ContractError, match="strictly increasing"):
            contract.validate(doc, kind)
    doc = _tracks()
    doc["frames"][0]["people"].append(copy.deepcopy(doc["frames"][0]["people"][0]))
    with pytest.raises(contract.ContractError, match="duplicate id"):
        contract.validate(doc, "tracks")


def test_edge_cases_the_spec_allows():
    empty = {"frames": []}
    contract.validate(empty, "pose3d")  # empty frames are valid for the schema (doctor says Part 3 rejects it)
    string_id = _pose()
    string_id["frames"][0]["people"][0]["id"] = "dancer-a"
    contract.validate(string_id, "pose3d")
    nobody = _pose()
    nobody["frames"][1]["people"] = []
    contract.validate(nobody, "pose3d")


def test_contract_error_carries_path_and_message():
    e = contract.ContractError("pose3d.frames[2].t_ms", "required")
    assert (e.path, e.msg, str(e)) == ("pose3d.frames[2].t_ms", "required", "pose3d.frames[2].t_ms: required")
    assert isinstance(e, ValueError) and schema.ContractError is contract.ContractError


# --- AC-C02: the Part 3 consumer copy -----------------------------------------------------------

@pytest.mark.parametrize("path", POSE3D, ids=_ids(POSE3D))
def test_committed_pose3d_satisfies_both_validators_and_the_part3_copy(path):
    doc = json.loads(path.read_text())
    validate_pose3d(doc)
    contract.validate_part3(doc)


@pytest.mark.parametrize("path", POSE3D, ids=_ids(POSE3D))
def test_committed_pose3d_writes_joints_in_canonical_order(path):
    doc = json.loads(path.read_text())
    assert all(list(p["joints"]) == CANONICAL for f in doc["frames"] for p in f["people"])


@pytest.mark.parametrize("path", TRACKS, ids=_ids(TRACKS))
def test_committed_tracks_satisfy_part2_validator(path):
    validate_tracks(json.loads(path.read_text()))  # Part 3 reads no tracks.json, so no consumer schema


def test_copy_of_part3_schema_moved_and_matches_its_source_record():
    source = json.loads(contract.PART3_SOURCE.read_text())
    assert contract.PART3_SCHEMA == ROOT / "contracts" / "consumers" / "part3-pose3d.schema.json"
    assert hashlib.sha256(contract.PART3_SCHEMA.read_bytes()).hexdigest() == source["sha256"]
    assert source["path"] == "contracts/pose3d.schema.json" and len(source["commit"]) == 40  # the path in Part 3's repo
    assert contract.load_schema()["x-simon-version"] == "part2.pose3d/2026-10-28"
    assert contract.load_schema()["x-direction"] == "input"


def test_pose3d_schema_in_contracts_is_part2s_own_not_part3s():
    own = json.loads((ROOT / "contracts" / "pose3d.schema.json").read_text())
    assert own["x-direction"] == "output" and own != contract.load_schema()
    assert {"mirrored", "fps", "t0_pts_ms", "provenance"} <= set(own["properties"])


def test_single_mode_producer_output_satisfies_part3():
    pose3d, _ = convert(_body3d([0, 10, 20]))
    contract.validate_part3(pose3d)
    contract.validate(pose3d, "pose3d")


def test_multi_mode_combined_and_per_person_files_satisfy_part3(tmp_path):
    write_pose_streams(_two_person_body3d(), tmp_path)
    files = sorted(tmp_path.glob("pose3d*.json"))
    assert len(files) == 3
    for f in files:
        contract.validate_part3(json.loads(f.read_text()))
        contract.validate(json.loads(f.read_text()), "pose3d")


def test_optional_hints_are_accepted():
    doc = {**_pose(), "mirrored": True, "fps": 15, "extra": "ignored"}
    contract.validate_part3(doc)
    contract.validate(doc, "pose3d")
    validate_pose3d(doc)


@pytest.mark.parametrize("mutate, where", [
    (lambda d: d.update(mirrored="yes"), "pose3d.mirrored"),
    (lambda d: d.update(fps=0), "pose3d.fps"),
    (lambda d: d["frames"][0].pop("t_ms"), "pose3d.frames[0].t_ms"),
    (lambda d: d["frames"][0]["people"][0]["joints"].pop("nose"), "joints.nose"),
    (lambda d: d["frames"][0]["people"][0]["joints"].update(neck={"x": 0, "y": 0, "z": 0, "conf": 1}), "neck"),
    (lambda d: d["frames"][0]["people"][0]["joints"]["nose"].update(conf=1.5), "joints.nose.conf"),
    (lambda d: d["frames"][0]["people"][0].update(id=True), "people[0].id"),
    (lambda d: d["frames"][0].update(frame=1.5), "pose3d.frames[0].frame"),
    (lambda d: d["frames"][1].update(frame=0), "strictly increasing"),
    (lambda d: d["frames"][0]["people"].append(copy.deepcopy(d["frames"][0]["people"][0])), "duplicate id"),
])
def test_part3_rejections_name_the_field(mutate, where):
    doc = _pose()
    mutate(doc)
    with pytest.raises(contract.ContractError, match=where.replace("[", r"\[").replace("]", r"\]")):
        contract.validate_part3(doc)


def test_known_gap_part2_validator_allows_a_duplicate_id_that_part3_rejects():
    """The one producer bug only the contract validators catch (CONTRACT.md, Differences)."""
    dup = _pose()
    dup["frames"][0]["people"].append(copy.deepcopy(dup["frames"][0]["people"][0]))
    validate_pose3d(dup)
    for check in (contract.validate_part3, lambda d: contract.validate(d, "pose3d")):
        with pytest.raises(contract.ContractError, match="duplicate id"):
            check(dup)


# --- the schema-subset checker -------------------------------------------------------------------

def test_unknown_schema_keyword_fails_loudly():
    with pytest.raises(contract.ContractError, match="not supported"):
        contract.check_schema([], {"type": "array", "uniqueItems": True})
    with pytest.raises(contract.ContractError, match="not supported"):
        contract.check_schema(1, {"anyOf": [{"type": "integer", "multipleOf": 2}]})


@pytest.mark.parametrize("doc, schema_, ok", [
    ([1, 2], {"type": "array", "minItems": 2}, True), ([1], {"type": "array", "minItems": 2}, False),
    ([1, 2, 3], {"type": "array", "maxItems": 2}, False),
    ("ab", {"type": "string", "minLength": 2}, True), ("a", {"type": "string", "minLength": 2}, False),
    ("2026-10-28", {"type": "string", "pattern": "^[0-9-]+$"}, True), ("x", {"type": "string", "pattern": "^[0-9]+$"}, False),
    ("s", {"anyOf": [{"type": "string"}, {"type": "integer"}]}, True), (1.5, {"anyOf": [{"type": "string"}, {"type": "integer"}]}, False),
    ([1, -1], {"type": "array", "prefixItems": [{"type": "number"}, {"type": "number", "minimum": 0}]}, False),
    ([1, 1, "x"], {"type": "array", "prefixItems": [{"type": "number"}], "items": {"type": "number"}}, False),
    (None, {"type": ["string", "null"]}, True), (True, {"type": "integer"}, False), (3.0, {"type": "integer"}, True),
    (NAN, {"type": "number"}, False), (INF, {"type": "number"}, False), (10 ** 400, {"type": "number"}, False),
])
def test_checker_keywords(doc, schema_, ok):
    if ok:
        contract.check_schema(doc, schema_)
    else:
        with pytest.raises(contract.ContractError):
            contract.check_schema(doc, schema_)


# --- AC-C07: NaN and infinity --------------------------------------------------------------------

POSE_FIELDS = [(["frames", 0, "t_ms"], "t_ms"), (NOSE + ["conf"], "conf"), (NOSE + ["x"], "x"), (NOSE + ["z"], "z"),
               (["fps"], "fps"), (["t0_pts_ms"], "t0_pts_ms")]
VALIDATORS = {
    "schema.validate_pose3d": validate_pose3d,
    "contract.validate": lambda d: contract.validate(d, "pose3d"),
    "contract.validate_part3": contract.validate_part3,
}


@pytest.mark.parametrize("name", VALIDATORS)
@pytest.mark.parametrize("bad", [NAN, INF, -INF], ids=["nan", "inf", "-inf"])
@pytest.mark.parametrize("path, field", POSE_FIELDS, ids=[f for _, f in POSE_FIELDS])
def test_nan_or_infinity_in_pose3d_fails_every_validator(name, bad, path, field):
    doc = {**_pose(), "fps": 30, "t0_pts_ms": 0}
    _set(path, bad)(doc)
    with pytest.raises(ValueError):
        VALIDATORS[name](doc)


@pytest.mark.parametrize("bad", [NAN, INF], ids=["nan", "inf"])
@pytest.mark.parametrize("path, field", [(TRACK + ["bbox", 2], "bbox"), (TRACK + ["confidence"], "confidence"), (["t0_pts_ms"], "t0_pts_ms")])
def test_nan_or_infinity_in_tracks_fails_both_validators(bad, path, field):
    doc = {**_tracks(), "t0_pts_ms": 0}
    _set(path, bad)(doc)
    for check in (validate_tracks, lambda d: contract.validate(d, "tracks")):
        with pytest.raises(ValueError):
            check(doc)


def test_a_number_too_large_for_a_double_is_refused_not_a_crash():
    doc = _pose()
    doc["frames"][0]["t_ms"] = 10 ** 400
    for check in (validate_pose3d, lambda d: contract.validate(d, "pose3d"), contract.validate_part3):
        with pytest.raises(contract.ContractError):
            check(doc)


def test_writers_never_emit_nan_or_infinity(tmp_path):
    from part2 import canonical

    body = _body3d([0, 10])
    body["frames"][1]["people"][0]["kp3d_cam"]["nose"][0] = NAN
    body3d_path = tmp_path / "body3d.json"
    body3d_path.write_text(json.dumps(body))  # the unchecked writer upstream of this contract
    with pytest.raises(contract.ContractError):
        canonical.write(body3d_path, tmp_path / "out")
    assert not (tmp_path / "out" / "pose3d.json").exists()
    with pytest.raises(contract.ContractError, match="NaN or infinity"):
        schema.write_json(tmp_path / "camera.json", {"K": [[1.0, NAN]]})
    assert not (tmp_path / "camera.json").exists()


# --- AC-C03: the contract command ---------------------------------------------------------------

def test_contract_json_function_holds_four_schemas_and_the_table():
    doc = contract.contract_json()
    assert [r["name"] for r in doc["schemas"]] == ["pose3d", "tracks", "camera", "frames"]
    assert all(set(r) == {"name", "version", "direction", "file"} and (ROOT / r["file"]).is_file() for r in doc["schemas"])
    assert [r["version"] for r in doc["schemas"]] == [f"part2.{k}/2026-10-28" for k in contract.KINDS]
    assert doc["compatibility"] == json.loads((ROOT / "contracts" / "compatibility.json").read_text())


def test_contract_command_prints_four_schema_rows_and_every_table_row(capsys):
    assert contract.command() == 0
    out = capsys.readouterr().out
    for r in contract.schema_rows():
        assert re.search(rf"^\s+{r['name']}\s+{re.escape(r['version'])}\s+output\s+{re.escape(r['file'])}$", out, re.M)
    for r in contract.compatibility():
        assert any(r["producer_file"] in line and r["consumer"] in line and r["result"] in line for line in out.splitlines())


def test_contract_json_flag_parses_and_holds_the_same_rows(capsys):
    assert contract.command(as_json=True) == 0
    assert json.loads(capsys.readouterr().out) == contract.contract_json()


def _part2(*args):
    return subprocess.run([sys.executable, "-m", "part2", *args], cwd=ROOT, capture_output=True)


@pytest.mark.parametrize("kind", contract.KINDS)
def test_schema_flag_prints_the_file_byte_for_byte(kind):
    r = _part2("contract", "--schema", kind)
    assert r.returncode == 0 and r.stdout == (ROOT / "contracts" / f"{kind}.schema.json").read_bytes()


def test_unknown_schema_exits_2_naming_the_choices():
    r = _part2("contract", "--schema", "skeleton")
    assert r.returncode == 2 and r.stdout == b""
    assert r.stderr.decode().strip() == "contract: no schema 'skeleton'; schemas: pose3d, tracks, camera, frames"


def test_python_m_part2_contract_json_matches_the_function():
    r = _part2("contract", "--json")
    assert r.returncode == 0 and json.loads(r.stdout) == contract.contract_json()


def _md_table(heading):
    lines = (ROOT / "CONTRACT.md").read_text().split(f"## {heading}\n", 1)[1].split("\n## ", 1)[0].splitlines()
    rows = [[c.strip() for c in line.strip().strip("|").split("|")] for line in lines if line.startswith("|")]
    return rows[0], rows[2:]


def test_contract_md_table_is_the_compatibility_file():
    header, rows = _md_table("Compatibility table")
    assert header == ["Producer file", "Version", "Consumer", "Result", "Option", "Evidence"]
    assert rows == [[r["producer_file"], r["version"], r["consumer"], r["result"], r["option"], r["evidence"]]
                    for r in contract.compatibility()]


def _md_section_intro(heading):
    """The text of the `## heading` section of CONTRACT.md before its first `### ` subsection."""
    text = (ROOT / "CONTRACT.md").read_text().split(f"## {heading}\n", 1)[1].split("\n## ", 1)[0]
    return text.split("\n### ", 1)[0]


def test_j07_contract_md_names_the_part7_call():
    """AC-J07 (docs/specs/journey-followup.md): the section "How Part 7 runs a take" names the one command Part 7 runs,
    `--mirrored` and the Part 3 follow-on with `--view part5`. The command is filled in and parsed by the real argument
    parser, so a renamed or removed option fails here instead of leaving the documentation wrong."""
    section = _md_section_intro("How Part 7 runs a take")
    line = re.search(r"^(part2 run .*)$", section, re.M).group(1)
    assert line == ("part2 run --mode single --input <take.webm|take.mp4|take.mov> --out <dir> --fps 10 "
                    "--backend gpu [--mirrored]")
    filled = re.sub(r"<[^>]*>", "x", line)  # the placeholders are values the caller fills in
    for mirrored in (False, True):  # [--mirrored] is optional
        argv = shlex.split(re.sub(r"\[(--[a-z-]+)\]", r"\1" if mirrored else "", filled))
        assert argv[0] == "part2"
        args = cli._build_parser().parse_args(argv[1:])  # an unknown or missing option is a SystemExit
        assert (args.command, args.mode, args.fps, args.backend, args.mirrored) == ("run", "single", 10.0, "gpu", mirrored)
        assert (args.input, args.out) == (Path("x"), Path("x"))
    # the options table explains exactly the options of the command, and --mirrored is one of them
    table_options = set(re.findall(r"^\| `(--[a-z-]+)", section, re.M))
    assert table_options == set(re.findall(r"--[a-z-]+", line)) and "--mirrored" in table_options
    # the follow-on: Part 3 on the pose3d.json the command wrote into <dir>, with --view part5
    follow_on = next(s for s in re.split(r"(?<=\.)\s", " ".join(section.split())) if "--view part5" in s)
    assert "Part 3" in follow_on and "`<dir>/pose3d.json`" in follow_on and "for Part 5" in follow_on


def test_the_table_has_the_rows_the_spec_names():
    rows = {(r["producer_file"], r["consumer"]): r for r in contract.compatibility()}
    assert rows[("pose3d.json, several people", "Part 3")]["result"] == "works with option"
    assert rows[("pose3d.json", "Part 6")]["result"] == "works with its generic reader only"
    part1 = next(r for r in contract.compatibility() if r["consumer"].startswith("Part 1"))
    assert "t0_pts_ms" in part1["option"] and "t_ms" in part1["option"] and part1["result"] == "works with option"
    assert {r["consumer"] for r in contract.compatibility()} >= {"Part 3", "Part 4", "Part 5", "Part 6", "Part 7"}


def _one_line(text):
    return " ".join(text.split())


def test_contract_says_how_extra_joints_behave_in_a_mirrored_file():
    """TICKET-043 (J2 review R1): a mirrored file's `extra_joints` carry the labels of `joints`, Part 3 leaves them
    alone, so a reader that mirrors the joints swaps the feet's left_/right_ names and negates x. Said in the
    `mirrored` section and in the Extra joints rules, and a compatibility row for Part 5 reading the feet directly."""
    text = (ROOT / "CONTRACT.md").read_text()
    mirrored = _one_line(text.split("### `mirrored`", 1)[1].split("\n### ", 1)[0])
    rules = [_one_line(line) for line in text.split("### Extra joints (optional)", 1)[1].split("\n### ", 1)[0].splitlines()
             if line.startswith("| Mirrored file |")]
    assert len(rules) == 1
    for said in (mirrored, rules[0]):
        for part in ("same labels as `joints`", "Part 3", "does not touch `extra_joints`",
                     "swap the `left_` and `right_` names", "negate x"):
            assert part in said, part
    assert "`left_heel` becomes `right_heel`" in mirrored
    direct = [r for r in contract.compatibility() if r["consumer"].startswith("Part 5 (feet")]
    assert len(direct) == 1 and direct[0]["producer_file"] == "pose3d.json with `extra_joints`"
    assert direct[0]["result"] == "works with option" and direct[0]["version"] == "part2.pose3d/2026-10-28"
    for part in ("canonical frame", "`mirrored: true`", "swap the `left_` and `right_` names", "negate x",
                 "Part 3 does not touch `extra_joints`"):
        assert part in direct[0]["option"], part
    assert "via Part 3" in {r["result"] for r in contract.compatibility() if r["consumer"] == "Part 5"}  # the old row stays
    _, md_rows = _md_table("Compatibility table")
    assert any(row[2] == direct[0]["consumer"] and row[4] == direct[0]["option"] for row in md_rows)


@pytest.mark.parametrize("path", ["CONTRACT.md", "contracts/compatibility.json",
                                  "docs/design/specs/integration-contract.md", "docs/specs/integration-contract.md"])
def test_the_foot_point_wording_has_no_em_dash_en_dash_or_spaced_hyphen(path):
    if path.startswith("docs/specs/") and not (ROOT / path).exists():
        pytest.skip("the maintainers' working spec is not published; its published copy is under docs/design/")
    for line in (ROOT / path).read_text().splitlines():
        if "extra_joints" in line or "mirrored" in line:
            assert "—" not in line and "–" not in line and " - " not in line, line


# --- AC-C09 and AC-C-NFR-01: additive only ------------------------------------------------------

def test_additive_fields_keep_part3s_rows_for_part2_at_7e11a7f():
    doc = json.loads((ROOT / "fixtures" / "output" / "single" / "pose3d.json").read_text())
    contract.validate_part3(doc)
    enriched = {**doc, "mirrored": True, "t0_pts_ms": 1.5, "provenance": {"backend": "gpu", "tracker": None}}
    contract.validate_part3(enriched)
    contract.validate(enriched, "pose3d")
    assert {k: v for k, v in enriched.items() if k not in ("mirrored", "t0_pts_ms", "provenance")} == doc


def _required(node, found=None):
    found = {} if found is None else found
    if isinstance(node, dict):
        if "required" in node:
            found[tuple(node["required"])] = None
        for v in node.values():
            _required(v, found)
    elif isinstance(node, list):
        for v in node:
            _required(v, found)
    return set(found)


EXPECTED_REQUIRED = {  # the README shapes; a new required field breaks Part 3's reader (ASM-010)
    "pose3d": {("frames",), ("frame", "t_ms", "people"), ("id", "joints"), ("x", "y", "z", "conf"), tuple(CANONICAL)},
    "tracks": {("frames",), ("frame", "people"), ("id", "bbox", "mask_rle", "confidence"), ("size", "counts")},
    "camera": {("camera_frame", "K", "image_size", "frames"), ("frame", "people"), ("id", "R", "t")},
    "frames": {("frames",), ("frame", "t_ms", "file")},
}


@pytest.mark.parametrize("kind", contract.KINDS)
def test_no_schema_adds_a_required_field(kind):
    found = _required(contract.own_schema(kind)) - {("name", "source", "weights_sha256")}  # inside provenance only
    assert found == EXPECTED_REQUIRED[kind]


# --- AC-C10: make check-2-contract --------------------------------------------------------------

def test_check_outputs_passes_on_the_committed_files():
    report = contract.check_outputs()
    assert report["failures"] == [] and report["pass"] is True
    assert report["files"] == report["valid"] == len(COMMITTED) + len(contract.KINDS) + 2


def test_check_outputs_names_every_failing_file(tmp_path):
    out = tmp_path / "fixtures" / "output" / "x"
    out.mkdir(parents=True)
    (out / "pose3d.json").write_text(json.dumps(_pose()))
    bad = _pose()
    bad["frames"][0]["people"][0]["joints"]["nose"]["conf"] = NAN
    (out / "pose3d_person_1.json").write_text(json.dumps(bad))  # NaN is not valid JSON, but Python writes it
    (out / "tracks.json").write_text(json.dumps({"frames": [{"frame": 0, "people": [{"id": 0}]}]}))
    report = contract.check_outputs(tmp_path)
    assert report["pass"] is False and report["files"] - report["valid"] == len(report["failures"]) == 2
    named = {f["file"]: f["error"] for f in report["failures"]}
    assert "joints.nose.conf" in named["fixtures/output/x/pose3d_person_1.json"]
    assert "bbox" in named["fixtures/output/x/tracks.json"]


def test_check_outputs_fails_when_nothing_is_committed(tmp_path):
    assert contract.check_outputs(tmp_path)["pass"] is False


def test_check_command_prints_metrics_json_and_exits_0(capsys):
    assert contract.main(["check"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert set(report) == {"files", "valid", "failures", "pass"} and report["pass"] is True


def test_validate_subcommand_checks_both_validators(capsys):
    assert contract.main(["validate", str(POSE3D[0])]) == 0
    assert "valid for Part 2 and Part 3" in capsys.readouterr().out


def test_makefile_has_the_contract_targets():
    make = (ROOT / "Makefile").read_text()
    assert re.search(r"^check-2-contract:\n\t.*part2\.contract check", make, re.M)
    assert "contracts/consumers/part3-pose3d.schema.json" in make and re.search(r"^\.PHONY:.*check-2-contract", make, re.M)


# --- sync (make contract-sync, contract-check) --------------------------------------------------

def _sync_setup(tmp_path, monkeypatch):
    schema_, source = tmp_path / "s.json", tmp_path / "src.json"
    schema_.write_bytes(b"{}")
    source.write_text(json.dumps({"repo": "o/r", "path": "p", "branch": "main", "commit": "a" * 40, "sha256": "x"}))
    monkeypatch.setattr(contract, "PART3_SCHEMA", schema_)
    monkeypatch.setattr(contract, "PART3_SOURCE", source)
    return schema_, source


def test_sync_unchanged_exits_0_and_writes_nothing(tmp_path, monkeypatch):
    schema_, source = _sync_setup(tmp_path, monkeypatch)
    before = source.read_text()
    assert contract.sync(fetcher=lambda s: (b"{}", "b" * 40)) == 0
    assert source.read_text() == before


def test_sync_changed_exits_1_and_refreshes(tmp_path, monkeypatch):
    schema_, source = _sync_setup(tmp_path, monkeypatch)
    assert contract.sync(check_only=True, fetcher=lambda s: (b'{"a": 1}', "b" * 40)) == 1
    assert schema_.read_bytes() == b"{}"
    assert contract.sync(fetcher=lambda s: (b'{"a": 1}', "b" * 40)) == 1
    rec = json.loads(source.read_text())
    assert schema_.read_bytes() == b'{"a": 1}'
    assert rec["commit"] == "b" * 40 and rec["sha256"] == hashlib.sha256(b'{"a": 1}').hexdigest()
