"""Step 2: one person (AC-003, ADR-0005)."""

import numpy as np
import pytest

from clipkit import doc_arrays
from part3 import cli, person
from part3.joints import JOINTS
from part3.schema import ContractError


def entry(pid, J, conf, scale=1.0):
    return {"id": pid, "joints": {name: {"x": float(J[j, 0] * scale), "y": float(J[j, 1] * scale),
                                         "z": float(J[j, 2] * scale), "conf": float(conf[j])}
                                  for j, name in enumerate(JOINTS)}}


def clip(real_doc, presence, scales=None, n=12):
    """pose3d with the real squat for every id in `presence` ({id: frame indices}), in dict order."""
    J, conf = doc_arrays(real_doc)
    scales = scales or {}
    frames = []
    for i in range(n):
        people = [entry(pid, J[i], conf[i], scales.get(pid, 1.0))
                  for pid, where in presence.items() if i in where]
        frames.append({"frame": i, "t_ms": round(1000.0 * i / 15, 3), "people": people})
    return {"frames": frames}


def chosen_id(skeleton):
    return skeleton["person"]["id"]


def test_most_frames_wins_and_candidates_are_recorded(real_doc):
    doc = clip(real_doc, {"a": range(0, 3), 7: range(0, 12), 3: range(4, 9)})
    out = cli.process(doc)
    assert chosen_id(out) == 7 and isinstance(chosen_id(out), int)
    assert out["person"]["candidates"] == {"a": 3, "7": 12, "3": 5}
    assert out["person"]["rule"] == "most_frames"
    assert all(p["id"] == 7 for f in out["frames"] for p in f["people"])


def test_string_ids_are_kept_as_given(real_doc):
    out = cli.process(clip(real_doc, {"7": range(0, 12), 8: range(0, 5)}))
    assert chosen_id(out) == "7" and isinstance(chosen_id(out), str)
    assert out["person"]["candidates"] == {"7": 12, "8": 5}
    # An int id and a string id that print alike stay two people; the chosen one's count is reported.
    alike = cli.process(clip(real_doc, {"7": range(0, 12), 7: range(0, 5)}))
    assert alike["person"]["candidates"] == {"7": 12} and alike["person"]["id"] == "7"


def test_tie_goes_to_the_larger_hip_to_ankle_extent(real_doc):
    doc = clip(real_doc, {1: range(0, 8), 2: range(0, 8)}, scales={2: 1.2})
    assert chosen_id(cli.process(doc)) == 2
    doc = clip(real_doc, {1: range(0, 8), 2: range(0, 8)}, scales={1: 1.2})
    assert chosen_id(cli.process(doc)) == 1


def test_remaining_tie_goes_to_the_first_id_in_input_order(real_doc):
    assert chosen_id(cli.process(clip(real_doc, {"x": range(0, 8), "y": range(0, 8)}))) == "x"
    assert chosen_id(cli.process(clip(real_doc, {"y": range(0, 8), "x": range(0, 8)}))) == "y"


def test_count_beats_extent(real_doc):
    doc = clip(real_doc, {1: range(0, 10), 2: range(0, 8)}, scales={2: 1.5})
    assert chosen_id(cli.process(doc)) == 1


def test_frames_without_the_chosen_person_have_empty_people(real_doc):
    doc = clip(real_doc, {0: range(0, 12), 5: range(2, 5)})
    J, conf = doc_arrays(real_doc)
    doc["frames"][8]["people"] = []  # nobody at all
    doc["frames"][9]["people"] = []
    doc["frames"][10]["people"] = [entry(5, J[10], conf[10])]  # only the other person
    out = cli.process(doc)
    assert chosen_id(out) == 0
    empty = [i for i, f in enumerate(out["frames"]) if not f["people"]]
    assert empty == [8, 9, 10]
    assert [f["frame"] for f in out["frames"]] == list(range(12))
    assert out["person"]["frames_present"] == 9 and out["person"]["frames_dropped"] == 0
    assert out["person"]["candidates"] == {"0": 9, "5": 4}


def test_chosen_person_data_is_used_not_the_others(real_doc):
    both = clip(real_doc, {0: range(0, 12), 1: range(0, 6)}, scales={1: 1.3})
    alone = clip(real_doc, {0: range(0, 12)})
    assert cli.process(both)["frames"] == cli.process(alone)["frames"]


def test_few_frames_flag(real_doc):
    four = cli.process(clip(real_doc, {0: range(0, 4)}))
    five = cli.process(clip(real_doc, {0: range(0, 5)}))
    assert four["person"]["few_frames"] is True and four["person"]["frames_present"] == 4
    assert five["person"]["few_frames"] is False
    one = cli.process(clip(real_doc, {0: [3]}))
    assert one["person"]["frames_present"] == 1 and len(one["frames"][3]["people"]) == 1


def test_hips_that_coincide_drop_the_frame(real_doc):
    doc = clip(real_doc, {0: range(0, 12)})
    joints = doc["frames"][6]["people"][0]["joints"]
    joints["right_hip"].update({axis: joints["left_hip"][axis] for axis in "xyz"})
    out = cli.process(doc)
    assert out["frames"][6]["people"] == []
    assert out["person"]["frames_dropped"] == 1 and out["person"]["frames_present"] == 11
    assert out["person"]["candidates"] == {"0": 12}
    assert out["person"]["few_frames"] is False


def test_hips_apart_threshold():
    J = np.zeros((3, 17, 3))
    J[:, 11, 0], J[:, 12, 0] = [1.0, 5e-7, 2e-6], [0.0, 0.0, 0.0]
    assert person.hips_apart(J).tolist() == [True, False, True]


def test_choose_and_extract_unit(real_doc):
    doc = clip(real_doc, {"a": range(0, 3), "b": range(0, 6)})
    chosen, candidates = person.choose(doc["frames"])
    assert (chosen, candidates) == ("b", {"a": 3, "b": 6})
    indices, J, conf = person.extract(doc["frames"], chosen)
    assert indices == list(range(6)) and J.shape == (6, 17, 3) and conf.shape == (6, 17)
    assert person.choose([{"frame": 0, "t_ms": 0, "people": []}]) == (None, {})
    assert person.extract([], "x")[1].shape == (0, 17, 3)


def test_no_person_anywhere_and_empty_clip_are_errors(real_doc):
    with pytest.raises(ContractError) as empty:
        cli.process({"frames": []})
    assert "empty" in empty.value.msg and empty.value.path == "pose3d.frames"
    nobody = {"frames": [{"frame": 0, "t_ms": 0.0, "people": []}, {"frame": 1, "t_ms": 66.7, "people": []}]}
    with pytest.raises(ContractError) as none:
        cli.process(nobody)
    assert "no person" in none.value.msg


def test_all_hips_coincide_is_an_error(real_doc):
    doc = clip(real_doc, {0: range(0, 3)}, n=3)
    for frame in doc["frames"]:
        joints = frame["people"][0]["joints"]
        joints["right_hip"].update({axis: joints["left_hip"][axis] for axis in "xyz"})
    with pytest.raises(ContractError):
        cli.process(doc)
