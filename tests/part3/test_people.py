"""--person, --all-people and the people index (spec integration-contract.md "People"; AC-V01, AC-V02)."""

import copy

import pytest

from part3 import cli, people, person
from part3.schema import ContractError, validate_skeleton

CLEAN = {"env": {}, "config": False}


def crowd(real_doc, ids=("b",), frames=20, absent=None, move=1.5):
    """The real clip's first `frames` frames with extra people (copies moved sideways) added.

    `absent` maps an id to the frame positions where it is missing; person 0 keeps the clip's own id.
    """
    doc = copy.deepcopy(real_doc)
    doc["frames"] = doc["frames"][:frames]
    absent = absent or {}
    for i, frame in enumerate(doc["frames"]):
        keep = [p for p in frame["people"] if i not in absent.get(p["id"], ())]
        for k, pid in enumerate(ids):
            if i in absent.get(pid, ()):
                continue
            other = copy.deepcopy(frame["people"][0])
            other["id"] = pid
            for joint in other["joints"].values():
                joint["x"] += move * (k + 1)
            keep.append(other)
        frame["people"] = keep
    return doc


def coincident_hips(doc, pid):
    """`doc` with the right hip of `pid` moved onto its left hip in every frame."""
    for frame in doc["frames"]:
        for entry in frame["people"]:
            if entry["id"] == pid:
                entry["joints"]["right_hip"] = dict(entry["joints"]["left_hip"])
    return doc


# --- finding the id ---------------------------------------------------------------------------------

def test_ids_are_listed_once_in_first_seen_order(real_doc):
    doc = crowd(real_doc, ids=("z", 5, "a"))
    assert person.ids(doc["frames"]) == [0, "z", 5, "a"]


def test_an_int_id_and_a_string_id_that_print_alike_are_two_people():
    assert person.ids([{"people": [{"id": 7}, {"id": "7"}]}]) == [7, "7"]


def test_find_prefers_the_same_type_then_the_other_spelling():
    assert person.find(7, [7, "7"]) == 7 and person.find("7", [7, "7"]) == "7"
    assert person.find("7", [7]) == 7 and person.find(7, ["7"]) == "7"
    assert person.find("x", [7, "y"]) is None and person.find(True, [1]) is None
    assert person.find(1.5, [1]) is None and person.find("-1", [-1]) is None


# --- AC-V01: --person --------------------------------------------------------------------------------

def test_ac_v01_person_keeps_the_requested_id_and_records_it(real_doc):
    doc = crowd(real_doc)
    default = cli.process(doc, **CLEAN)
    assert default["person"]["id"] == 0 and default["person"]["rule"] == "most_frames"
    assert "requested" not in default["person"]
    other = cli.process(doc, person="b", **CLEAN)
    assert other["person"]["id"] == "b" and other["person"]["rule"] == "requested"
    assert other["person"]["requested"] == "b"
    assert other["person"]["candidates"] == {"0": 20, "b": 20}
    assert list(other["person"])[:3] == ["id", "rule", "requested"]
    assert {p["id"] for f in other["frames"] for p in f["people"]} == {"b"}
    validate_skeleton(other)


def test_ac_v01_person_can_pick_the_id_that_would_not_have_won(real_doc):
    doc = crowd(real_doc, absent={"b": range(0, 5)})
    assert cli.process(doc, **CLEAN)["person"]["id"] == 0
    assert cli.process(doc, person="b", **CLEAN)["person"]["frames_present"] == 15


def test_ac_v01_the_same_person_alone_matches_the_default_run_apart_from_the_rule(real_doc):
    doc = crowd(real_doc)
    alone = cli.process(crowd(real_doc, ids=()), **CLEAN)
    asked = cli.process(doc, person=0, **CLEAN)
    assert asked["frames"] == alone["frames"] and asked["person"]["requested"] == 0


def test_ac_v01_an_absent_id_exits_two_listing_the_ids(real_doc):
    doc = crowd(real_doc, ids=("b", 4))
    with pytest.raises(ContractError) as caught:
        cli.process(doc, person=9, **CLEAN)
    assert str(caught.value) == "--person 9: not in the input (ids: 0, b, 4)"


def test_ac_v01_at_most_twenty_ids_are_listed(real_doc):
    doc = crowd(real_doc, ids=tuple(range(1, 26)), frames=3)
    with pytest.raises(ContractError) as caught:
        cli.process(doc, person=99, **CLEAN)
    message = str(caught.value)
    assert "(ids: 0, 1, 2" in message and "19, ..." in message and "20," not in message
    assert message.endswith("... (26 ids in all))")


def test_ac_v01_person_and_all_people_exclude_each_other(real_doc, tmp_path, capsys):
    source = tmp_path / "in.json"
    import json
    source.write_text(json.dumps(crowd(real_doc)))
    with pytest.raises(SystemExit) as caught:
        cli.main(["run", "--in", str(source), "--out", str(tmp_path / "o"), "--person", "0", "--all-people"])
    assert caught.value.code == 2
    assert "--person" in capsys.readouterr().err and not (tmp_path / "o").exists()


def test_ac_v01_process_all_refuses_person(real_doc):
    with pytest.raises(ContractError) as caught:
        cli.process_all(crowd(real_doc), person=0, **CLEAN)
    assert str(caught.value).startswith("--person: cannot be combined")


def test_a_person_in_no_frame_at_all_still_says_no_person():
    doc = {"frames": [{"frame": 0, "t_ms": 0.0, "people": []}]}
    with pytest.raises(ContractError) as caught:
        cli.process(doc, person=3, **CLEAN)
    assert caught.value.path == "pose3d.frames" and "no person" in str(caught.value)


# --- AC-V02: --all-people ------------------------------------------------------------------------------

def test_ac_v02_process_all_gives_one_valid_single_person_skeleton_per_id_in_first_seen_order(real_doc):
    doc = crowd(real_doc, ids=("z", 5))
    results = cli.process_all(doc, **CLEAN)
    assert [pid for pid, _ in results] == [0, "z", 5]
    for pid, skeleton in results:
        validate_skeleton(skeleton)
        assert skeleton["person"]["id"] == pid and skeleton["person"]["rule"] == "requested"
        assert {p["id"] for f in skeleton["frames"] for p in f["people"]} == {pid}
        assert len(skeleton["frames"]) == 20


def test_ac_v02_an_id_with_coincident_hips_is_skipped_with_a_reason(real_doc):
    doc = coincident_hips(crowd(real_doc, ids=("b", "c")), "b")
    results = dict(cli.process_all(doc, **CLEAN))
    assert list(results) == [0, "b", "c"]
    assert results["b"] == {"skipped": "the chosen person has no usable frame (the hips coincide)"}
    assert "frames" in results[0] and "frames" in results["c"]


def test_process_all_fills_trace_from_the_first_processed_id(real_doc):
    trace = {}
    cli.process_all(crowd(real_doc), trace=trace, **CLEAN)
    assert set(trace) == {"up_in_input", "up_source"}


def test_process_all_on_one_person_matches_a_requested_run(real_doc):
    doc = crowd(real_doc, ids=())
    [(pid, skeleton)] = cli.process_all(doc, **CLEAN)
    assert pid == 0 and skeleton == cli.process(doc, person=0, **CLEAN)


def test_process_all_uses_each_persons_own_measured_body(real_doc):
    doc = crowd(real_doc, ids=("b",))
    for frame in doc["frames"]:  # person b is a taller body: scale their joints about the hip midpoint
        for joint in frame["people"][1]["joints"].values():
            joint["y"] = joint["y"] * 1.2
    a, b = (s for _, s in cli.process_all(doc, body="measured", **{"env": {}, "config": False}))
    assert a["bone_lengths_m"] != b["bone_lengths_m"]


# --- slugs and the layout ---------------------------------------------------------------------------------

@pytest.mark.parametrize("ids,expected", [
    ([0, 1, 2], ["0", "1", "2"]),
    (["a/b", "ok"], ["p0", "ok"]),
    (["with space", "x"], ["p0", "x"]),
    (["é", ".."], ["p0", "p1"]),
    (["a" * 40, "b" * 41], ["a" * 40, "p1"]),
    ([1, "1"], ["1", "p1"]),
    (["A", "a"], ["A", "p1"]),
    (["p1", "a/b"], ["p1", "p1-2"]),
    (["", "ok"], ["p0", "ok"]),
])
def test_slugs(ids, expected):
    assert people.slugs(ids) == expected


def render_one(skeleton):
    return {"skeleton.json": skeleton, "extra.json": {"for": skeleton["person"]["id"]}}


def test_ac_v02_layout_lists_files_then_people_json_in_first_seen_order(real_doc):
    doc = coincident_hips(crowd(real_doc, ids=("b/c", "d")), "d")
    results = cli.process_all(doc, **CLEAN)
    files = people.layout(results, render_one)
    assert [path for path, _ in files] == ["person-0/skeleton.json", "person-0/extra.json",
                                           "person-p1/skeleton.json", "person-p1/extra.json", "people.json"]
    index = files[-1][1]
    assert index["schema"] == "simon.part3.people/1"
    assert index["people"] == [
        {"id": 0, "dir": "person-0", "frames_present": 20, "file": "person-0/skeleton.json"},
        {"id": "b/c", "dir": "person-p1", "frames_present": 20, "file": "person-p1/skeleton.json"},
        {"id": "d", "dir": "person-d", "frames_present": 0,
         "skipped": "the chosen person has no usable frame (the hips coincide)"}]


def test_a_skipped_id_has_no_file_and_the_folder_is_not_in_the_files(real_doc):
    results = [(1, {"skipped": "why"})]
    files = people.layout(results, render_one)
    assert [path for path, _ in files] == ["people.json"] and "file" not in files[0][1]["people"][0]
