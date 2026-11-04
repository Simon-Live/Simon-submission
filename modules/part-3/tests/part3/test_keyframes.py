"""Keyframes input: Part 1, Part 4 and every:<n> sources on the 30 fps clock (AC-P03, AC-P04, TICKET-025)."""

import json

import pytest

from part3 import keyframes as kf
from part3.schema import ContractError

T0, T_LAST = 0.0, 7066.667  # the real Part 2 squat: 213 ticks at 30 fps
COUNT = 213


def part1_doc(keys_by_rep, fps=60.0, people_ids=(0,)):
    """A Part 1 file: each person gets every repetition in `keys_by_rep` [[(name, t_ms), ...], ...]."""
    reps = [{"rep": r + 1, "movement": "squat",
             "keyframes": [{"name": n, "frame": round(t * fps / 1000), "t_ms": t} for n, t in keys]}
            for r, keys in enumerate(keys_by_rep)]
    return {"video": "squat.mp4", "fps": fps, "analysis_fps": 15.0, "quality": {},
            "people": [{"id": pid, "repetitions": reps} for pid in people_ids]}


def part4_doc(*indices, fps=30, names=None):
    return {"format": "simon.keyframes.v1", "fps": fps, "duration_s": 7.066667, "frame_count": COUNT,
            "keyframes": [{"index": i, "t": round(i / 30, 6), "name": (names or {}).get(i, f"k{i}")}
                          for i in indices]}


def indices(timeline):
    return [i for i, _ in timeline.keys]


# --- the clock ---------------------------------------------------------------------------------

def test_frame_count_is_floor_of_ticks_plus_one():
    assert kf.frame_count(0, 7066.667) == COUNT
    assert kf.frame_count(0, 3000) == 91
    assert kf.frame_count(1000, 4000) == 91
    assert kf.frame_count(0, 2999.9999) == 90
    assert kf.frame_count(500, 500) == 1
    assert kf.frame_count(0, 3333.3333333333335) == 101  # a last frame on a tick keeps that tick
    assert kf.frame_count(100, 50) == 1  # a backwards clock never gives zero ticks


def test_timeline_clock_fields():
    timeline = kf.load("every:10", 1000.0, 1000.0 + 3000.0)
    assert (timeline.fps, timeline.frame_count, timeline.duration_s, timeline.t0_ms) == (30, 91, 3.0, 1000.0)
    assert (timeline.source_kind, timeline.person, timeline.dropped) == ("every", None, [])


# --- AC-P03: every:<n> -------------------------------------------------------------------------

def test_p03_every_10_keys_every_tenth_tick_and_the_last():
    timeline = kf.load("every:10", T0, T_LAST)
    assert indices(timeline) == list(range(0, 211, 10)) + [212]
    assert timeline.keys[0] == (0, "key_0") and timeline.source_kind == "every"


def test_p03_every_edges():
    assert indices(kf.load("every:1", T0, T_LAST)) == list(range(COUNT))
    assert indices(kf.load("every:300", T0, T_LAST)) == [0, 212]
    assert indices(kf.load("every:212", T0, T_LAST)) == [0, 212]  # the last tick is not listed twice
    assert indices(kf.load("every:5", 0, 3000)) == list(range(0, 91, 5))
    assert indices(kf.load("every:7", 0, 0)) == [0]  # a one-frame clip: one key at index 0


@pytest.mark.parametrize("spec", ["every:0", "every:301", "every:abc", "every:", "every:-1", "every:1.5",
                                  "every:10 ", "every: 10", "every:1e2"])
def test_p04_a_bad_every_value_exits_naming_the_option(spec):
    with pytest.raises(ContractError) as caught:
        kf.load(spec, T0, T_LAST)
    assert str(caught.value) == f"--keyframes {spec}: n must be a whole number from 1 to 300"


# --- AC-P03: Part 1 ----------------------------------------------------------------------------

def test_p03_part1_keys_at_60_fps_map_to_the_30_fps_index_by_time():
    keys = [[("start", 0.0), ("descend", 800.0), ("bottom", 1700.0)],
            [("ascend", 2500.5), ("start", 3400.0), ("end", 7066.667)]]
    timeline = kf.load(part1_doc(keys), T0, T_LAST)
    want = [(round(t * 30 / 1000), n) for rep in keys for n, t in rep]
    assert timeline.keys == want == [(0, "start"), (24, "descend"), (51, "bottom"), (75, "ascend"),
                                     (102, "start"), (212, "end")]
    assert (timeline.source_kind, timeline.person, timeline.dropped) == ("part1", 0, [])
    assert timeline.frame_count == COUNT


def test_p03_part1_times_are_on_the_video_clock_relative_to_the_first_input_frame():
    keys = [[("a", 12000.0), ("b", 12500.0), ("c", 13000.0)]]
    timeline = kf.load(part1_doc(keys), 12000.0, 12000.0 + 3000.0)
    assert indices(timeline) == [0, 15, 30] and timeline.t0_ms == 12000.0


def test_p03_part1_takes_every_repetition_in_time_order():
    keys = [[("late", 3000.0), ("later", 3500.0)], [("early", 100.0), ("earlier", 500.0)]]
    timeline = kf.load(part1_doc(keys), T0, T_LAST)
    assert timeline.keys == [(3, "early"), (15, "earlier"), (90, "late"), (105, "later")]


def test_p03_part1_rounding_goes_to_the_nearest_tick_half_up():
    keys = [[("below", 49.9), ("half", 150.0), ("above", 250.1)]]  # 1.497, 4.5, 7.503 ticks
    assert kf.load(part1_doc(keys), T0, T_LAST).keys == [(1, "below"), (5, "half"), (8, "above")]


def test_p03_part1_frame_and_fps_stand_in_for_a_missing_t_ms():
    doc = part1_doc([[("a", 0.0), ("b", 1000.0)]])
    for key in doc["people"][0]["repetitions"][0]["keyframes"]:
        del key["t_ms"]
    assert kf.load(doc, T0, T_LAST).keys == [(0, "a"), (30, "b")]


def test_p03_part1_picks_the_person_by_id_as_int_or_string_else_the_first():
    doc = part1_doc([[("one", 1000.0)]], people_ids=(0, 1))
    doc["people"][1]["repetitions"] = [{"rep": 1, "keyframes": [{"name": "two", "frame": 120, "t_ms": 2000.0}]}]
    assert kf.load(doc, T0, T_LAST).keys == [(30, "one")]
    assert kf.load(doc, T0, T_LAST, person=1).keys == [(60, "two")]
    chosen = kf.load(doc, T0, T_LAST, person="1")
    assert chosen.keys == [(60, "two")] and chosen.person == 1


def test_p04_part1_person_that_is_not_in_the_file_lists_the_ids(tmp_path):
    path = tmp_path / "keyframes.json"
    path.write_text(json.dumps(part1_doc([[("a", 0.0)]], people_ids=(0, "x"))))
    with pytest.raises(ContractError) as caught:
        kf.load(path, T0, T_LAST, person=7)
    assert str(caught.value) == f"--keyframes-person 7: not in {path} (ids: 0, x)"


def test_p03_part1_keys_outside_the_clip_and_colliding_keys_are_dropped_with_reasons():
    keys = [[("before", -400.0), ("first", 0.0), ("twin_a", 1000.0), ("twin_b", 1010.0),
             ("last", 7066.667), ("after", 7500.0)]]
    timeline = kf.load(part1_doc(keys), T0, T_LAST)
    assert timeline.keys == [(0, "first"), (30, "twin_a"), (212, "last")]
    assert [d["name"] for d in timeline.dropped] == ["before", "twin_b", "after"]
    before, twin, after = timeline.dropped
    assert before == {"name": "before", "t_ms": -400.0, "reason": "before the clip start (tick 0 is 0 ms)"}
    assert twin["t_ms"] == 1010.0 and twin["reason"] == "tick 30 already holds the key 'twin_a'"
    assert after["reason"] == "after the clip end (last tick 212 is 7066.667 ms)"
    assert set(before) == {"name", "t_ms", "reason"}


def test_p03_part1_a_key_within_half_a_tick_of_the_clip_edge_snaps_to_it():
    timeline = kf.load(part1_doc([[("a", -10.0), ("b", 7075.0)]]), T0, T_LAST)
    assert timeline.keys == [(0, "a"), (212, "b")] and timeline.dropped == []


def test_p03_a_one_frame_clip_keeps_one_key_at_index_0():
    timeline = kf.load(part1_doc([[("a", 5000.0), ("b", 5400.0)]]), 5000.0, 5000.0)
    assert timeline.keys == [(0, "a")] and timeline.frame_count == 1
    assert [d["name"] for d in timeline.dropped] == ["b"]


# --- AC-P03: Part 4 ----------------------------------------------------------------------------

def test_p03_part4_keys_keep_their_index_and_name():
    doc = part4_doc(0, 10, 90, 212, names={0: "stand", 10: "descend"})
    timeline = kf.load(doc, T0, T_LAST)
    assert timeline.keys == [(0, "stand"), (10, "descend"), (90, "k90"), (212, "k212")]
    assert (timeline.source_kind, timeline.person, timeline.dropped) == ("part4", None, [])


def test_p03_part4_keys_outside_the_clip_or_repeated_are_dropped_and_the_rest_sorted():
    timeline = kf.load(part4_doc(40, 10, 10, 300, -2), 0, 3000)
    assert timeline.keys == [(10, "k10"), (40, "k40")]
    reasons = {(d["name"], d["reason"].split(" (")[0]) for d in timeline.dropped}
    assert reasons == {("k10", "tick 10 already holds the key 'k10'"), ("k300", "after the clip end"),
                       ("k-2", "before the clip start")}
    assert {d["t_ms"] for d in timeline.dropped if d["name"] == "k300"} == {10000.0}


def test_p04_part4_needs_fps_30_a_whole_index_and_a_list():
    with pytest.raises(ContractError, match=r"keyframes\.fps: must be 30 \(got 60\)"):
        kf.load(part4_doc(0, fps=60), T0, T_LAST)
    missing = part4_doc(0)
    del missing["fps"]
    with pytest.raises(ContractError, match=r"keyframes\.fps: must be 30 \(got None\)"):
        kf.load(missing, T0, T_LAST)
    bad_index = part4_doc(0)
    bad_index["keyframes"][0]["index"] = 1.5
    with pytest.raises(ContractError, match=r"keyframes\.keyframes\[0\]\.index: expected a whole number"):
        kf.load(bad_index, T0, T_LAST)
    with pytest.raises(ContractError, match=r"keyframes\.keyframes: expected a list"):
        kf.load({"format": "simon.keyframes.v1", "fps": 30, "keyframes": None}, T0, T_LAST)


# --- AC-P04: reading and errors ----------------------------------------------------------------

def test_read_passes_a_dict_through_checks_every_and_parses_a_file(tmp_path):
    doc = part4_doc(0, 5)
    assert kf.read(doc) is doc
    assert kf.read("every:12") == "every:12"
    path = tmp_path / "k.json"
    path.write_text(json.dumps(doc))
    assert kf.read(str(path)) == doc and kf.read(path) == doc
    assert indices(kf.load(path, T0, T_LAST)) == [0, 5]
    assert indices(kf.load(str(path), T0, T_LAST)) == [0, 5]


def test_p04_an_unreadable_file_names_the_path(tmp_path):
    path = tmp_path / "missing.json"
    with pytest.raises(ContractError) as caught:
        kf.load(str(path), T0, T_LAST)
    assert str(caught.value).startswith(f"{path}: cannot read (")


def test_p04_a_file_that_is_not_json_names_the_path(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{not json")
    with pytest.raises(ContractError) as caught:
        kf.load(path, T0, T_LAST)
    assert str(caught.value).startswith(f"{path}: not valid JSON (")


@pytest.mark.parametrize("content", [{}, {"fps": 30}, {"frames": []}, [1, 2], "text", "every:10", 7, None])
def test_p04_an_unknown_kind_is_not_a_part1_or_part4_file(tmp_path, content):
    path = tmp_path / "other.json"
    path.write_text(json.dumps(content))
    with pytest.raises(ContractError) as caught:
        kf.load(path, T0, T_LAST)
    assert str(caught.value) == f"{path}: not a Part 1 or Part 4 keyframes file"


def test_p04_no_key_inside_the_clip_names_the_file_and_the_range(tmp_path):
    path = tmp_path / "keyframes.json"
    path.write_text(json.dumps(part1_doc([[("late", 99000.0), ("early", -9000.0)]])))
    with pytest.raises(ContractError) as caught:
        kf.load(path, T0, T_LAST)
    assert str(caught.value) == f"{path}: no keyframe falls inside the clip (0 to 7066.667 ms)"
    for empty in (part1_doc([]), {"people": []}, part4_doc()):
        with pytest.raises(ContractError, match=r"keyframes: no keyframe falls inside the clip \(0 to 7066.667 ms\)"):
            kf.load(empty, T0, T_LAST)


def test_p04_a_part1_key_without_a_time_names_the_key():
    doc = part1_doc([[("a", 0.0)]])
    doc["people"][0]["repetitions"][0]["keyframes"][0] = {"name": "a"}
    with pytest.raises(ContractError, match=r"keyframes\.people\[0\]\.repetitions\[0\]\.keyframes\[0\]\.t_ms: missing"):
        kf.load(doc, T0, T_LAST)


def test_p04_a_source_that_is_not_a_path_a_spec_or_a_dict_is_refused():
    with pytest.raises(ContractError, match="keyframes: expected a file path"):
        kf.read(["every:10"])


# --- review B1: the timeline has a frame cap -----------------------------------------------------

def test_b1_a_timeline_longer_than_the_cap_is_refused_with_the_count_and_the_limit():
    assert kf.frame_count(0, 3_333_333) == 100_000  # exactly the cap is fine
    with pytest.raises(ContractError) as caught:
        kf.frame_count(0, 3_333_367)
    assert str(caught.value) == "--keyframes: the 30 fps timeline would have 100002 ticks; the limit is 100000"
    assert caught.value.path == "--keyframes"


def test_b1_max_frames_lowers_the_cap_and_none_means_the_default():
    assert kf.frame_count(0, 7066.667, max_frames=213) == COUNT
    with pytest.raises(ContractError, match=r"would have 213 ticks; the limit is 212$"):
        kf.frame_count(0, 7066.667, max_frames=212)
    assert kf.frame_count(0, 7066.667, max_frames=None) == COUNT
    with pytest.raises(ContractError, match=r"the limit is 20000$"):
        kf.load("every:10", 0.0, 1_000_000.0, max_frames=20_000)  # 30001 ticks pass the default cap, not this one
    assert kf.load("every:10", 0.0, 1_000_000.0).frame_count == 30_001


@pytest.mark.parametrize("source", ["every:10", part4_doc(0, 5), part1_doc([[("a", 0.0)]])])
def test_b1_every_source_kind_is_capped_before_a_key_is_looked_at(source):
    with pytest.raises(ContractError, match=r"^--keyframes: the 30 fps timeline would have 3e\+298 ticks; "
                                            r"the limit is 100000$"):
        kf.load(source, 0.0, 1e300)


def test_b1_a_span_past_the_float_range_is_refused_not_a_traceback():
    for first, last in ((-1.7e308, 1.7e308), (0.0, float("inf"))):
        with pytest.raises(ContractError, match=r"^--keyframes: the 30 fps timeline would have more ticks than "
                                                r"the limit of 100000: the clip span \(first to last t_ms\) is not "
                                                r"finite$"):
            kf.load("every:10", first, last)


def test_b1_a_backwards_clock_still_gives_one_tick_under_any_cap():
    assert kf.frame_count(100, 50, max_frames=1) == 1


# --- review residual 11: a Part 1 person that is not an object is an error ------------------------

@pytest.mark.parametrize("entry,kind", [(None, "null"), ("p", "a string"), (3, "a number"), ([1], "an array"),
                                        (True, "a boolean")])
def test_r11_a_part1_person_that_is_not_an_object_names_the_field(entry, kind):
    doc = part1_doc([[("a", 0.0)]])
    doc["people"] = [doc["people"][0], entry]
    with pytest.raises(ContractError) as caught:
        kf.load(doc, T0, T_LAST)
    assert str(caught.value) == f"keyframes.people[1]: expected an object (got {kind})"
    assert caught.value.path == "keyframes.people[1]"


def test_r11_the_first_listed_person_is_checked_too_and_a_requested_one_does_not_hide_it(tmp_path):
    path = tmp_path / "keyframes.json"
    doc = part1_doc([[("a", 0.0)]])
    doc["people"].insert(0, None)
    path.write_text(json.dumps(doc))
    with pytest.raises(ContractError, match=rf"^{path}\.people\[0\]: expected an object \(got null\)$"):
        kf.load(path, T0, T_LAST)
    with pytest.raises(ContractError, match=r"people\[0\]: expected an object"):
        kf.load(path, T0, T_LAST, person=0)
