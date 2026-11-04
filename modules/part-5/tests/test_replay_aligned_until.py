"""TICKET-085: the replay says where its alignment path ends (`aligned_until_s`, `aligned_until_expected_frame`, replay 1.1.0).

The alignment is open-ended (part5/align.py), so the follower frames after the last one `exp_to_fol` reaches were never compared
or scored. The fields are reported only. Pinned on committed seed 5 takes: one compared as a whole with a trailing tail, the golden
take without one, and one compared rep by rep with a tail.
"""
import copy
import json
from pathlib import Path

import jsonschema
import pytest

from part5 import contract
from part5.pipeline import run
from part5.replay import SCHEMA_VERSION, aligned_until, build_replay
from part5.score_report import feet_kwargs

ROOT = Path(__file__).resolve().parent.parent
LABELS = {t["take_id"]: t for t in json.loads((ROOT / "fixtures/input/followers/labels.json").read_text())["takes"]}
GOLDEN = json.loads((ROOT / "fixtures/output/replay.example.json").read_text())
SCHEMA = contract.load_schema("replay")
KEYS_1_0_0 = {"format", "schema_version", "fps", "expected", "follower", "exp_to_fol", "joints", "bones", "expected_t",
              "follower_t", "coordinate_frame"}
NEW = set(contract.ALIGNED_UNTIL_KEYS)
WITH_TAIL = "exercise_front_good_00_correct"            # compared as a whole: 88 frames, the path ends at frame 83
WITHOUT_TAIL = "exercise_front_good_08_arms_wider-both+elbow_bent-right"   # the golden replay's take
REPS_WITH_TAIL = "dance_side_good_04_knees_shallow-both"   # compared rep by rep, a tail of 24 frames


def replay_of(take_id):
    take = LABELS[take_id]
    return build_replay(run(str(ROOT / take["expected"]), str(ROOT / take["follower"]), **feet_kwargs(take, ROOT)))


@pytest.fixture(scope="module")
def with_tail():
    return replay_of(WITH_TAIL)


@pytest.fixture(scope="module")
def reps_with_tail():
    return replay_of(REPS_WITH_TAIL)


def tail_frames(replay):
    return [i for i, t in enumerate(replay["follower_t"]) if t > replay["aligned_until_s"]]


def test_aligned_until_is_the_follower_time_of_the_largest_index_and_the_last_expected_frame_shown_with_it():
    assert aligned_until([0, 0, 1, 3, 3], [0.0, 0.1, 0.2, 0.3, 0.4, 0.5]) == {
        "aligned_until_s": 0.3, "aligned_until_expected_frame": 4}
    assert aligned_until([0, 2, 2, 1], [0.0, 0.25, 0.5]) == {"aligned_until_s": 0.5, "aligned_until_expected_frame": 2}
    assert aligned_until([0, 1, 2], [0.0, 0.1, 0.2]) == {"aligned_until_s": 0.2, "aligned_until_expected_frame": 2}


def test_a_take_with_a_trailing_tail_says_where_its_path_ends(with_tail):
    r = with_tail
    assert r["schema_version"] == SCHEMA_VERSION == "1.1.0" and "reps" not in r
    assert max(r["exp_to_fol"]) == 83 and len(r["follower_t"]) == 88
    assert r["aligned_until_s"] == r["follower_t"][83] == pytest.approx(2.766667) and r["follower_t"][-1] == pytest.approx(2.9)
    assert r["aligned_until_expected_frame"] == len(r["expected"]) - 1 == 90
    tail = tail_frames(r)
    assert tail == [84, 85, 86, 87] and not set(tail) & set(r["exp_to_fol"])   # the tail was never shown, so never compared


def test_a_take_without_a_tail_ends_its_path_on_the_follower_s_last_frame():
    r = replay_of(WITHOUT_TAIL)
    assert max(r["exp_to_fol"]) == len(r["follower_t"]) - 1 and tail_frames(r) == []
    assert r["aligned_until_s"] == r["follower_t"][-1] and r["aligned_until_expected_frame"] == len(r["expected"]) - 1
    assert r == GOLDEN   # the committed golden replay is this take's, rebuilt


def test_a_take_compared_rep_by_rep_says_where_the_path_over_its_reps_ends(reps_with_tail):
    r = reps_with_tail
    assert r["reps"] and max(r["exp_to_fol"]) == r["exp_to_fol"][-1] < len(r["follower_t"]) - 1
    assert len(tail_frames(r)) == 24 and r["follower_t"][-1] - r["aligned_until_s"] == pytest.approx(0.8, abs=1e-5)
    assert r["aligned_until_expected_frame"] == len(r["expected"]) - 1


@pytest.mark.parametrize("which", ["with_tail", "reps_with_tail"])
def test_the_fields_are_added_and_nothing_else_changes(which, request):
    """Reported only: the 1.0.0 keys are all there with what they held, the two fields are new and agree with them."""
    r = request.getfixturevalue(which)
    assert set(r) - {"reps"} == KEYS_1_0_0 | NEW
    assert aligned_until(r["exp_to_fol"], r["follower_t"]) == {k: r[k] for k in NEW}
    assert not list(jsonschema.Draft202012Validator(SCHEMA).iter_errors(r)) and contract.replay_problems(r) == []


def test_the_schema_is_1_1_0_and_a_1_0_0_replay_without_the_fields_still_passes(with_tail):
    assert SCHEMA["version"] == "1.1.0" and not NEW & set(SCHEMA["required"]) and NEW <= set(SCHEMA["properties"])
    old = {k: v for k, v in with_tail.items() if k not in NEW}
    old["schema_version"] = "1.0.0"
    assert not list(jsonschema.Draft202012Validator(SCHEMA).iter_errors(old)) and contract.replay_problems(old) == []


@pytest.mark.parametrize("key,value,needle", [
    ("aligned_until_s", 2.9, "not the follower time where exp_to_fol ends"),
    ("aligned_until_expected_frame", 89, "not the last expected frame shown with that follower frame"),
])
def test_the_contract_check_refuses_a_field_that_does_not_follow_exp_to_fol(with_tail, key, value, needle):
    forged = dict(copy.deepcopy(with_tail), **{key: value})
    problems = contract.replay_problems(forged)
    assert [p[0] for p in problems] == [key] and needle in problems[0][1]


def test_the_contract_check_wants_both_fields_or_neither(with_tail):
    one = {k: v for k, v in with_tail.items() if k != "aligned_until_expected_frame"}
    assert contract.replay_problems(one) == [("aligned_until_expected_frame", "missing beside aligned_until_s",
                                              "write both, as part5 analyse --replay does")]
