"""--fps resampling (spec integration-contract.md "Resampling"; AC-V03)."""

import copy
import time

import numpy as np
import pytest

from clipkit import skeleton_arrays
from part3 import bones, cli, resample
from part3.metrics import bone_variation
from part3.schema import ContractError, validate_skeleton

CLEAN = {"env": {}, "config": False}


def run(doc, fps, **kw):
    return cli.process(doc, fps=fps, **CLEAN, **kw)


def variation(skeleton):
    return bone_variation(skeleton, bones.lengths_array(skeleton["bone_lengths_m"]))


@pytest.fixture(scope="module")
def clip(real_doc):
    """The first 30 frames of the real clip (15 fps, about 1.93 s)."""
    doc = copy.deepcopy(real_doc)
    doc["frames"] = doc["frames"][:30]
    return doc


# --- the grid ---------------------------------------------------------------------------------------------

def test_ac_v03_fps_30_writes_a_uniform_grid_on_the_source_clock(real_doc):
    skeleton = run(real_doc, 30)
    frames = skeleton["frames"]
    last = real_doc["frames"][-1]["t_ms"]
    assert [f["frame"] for f in frames] == list(range(len(frames))) and len(frames) == 213
    assert frames[0]["t_ms"] == real_doc["frames"][0]["t_ms"]
    assert [f["t_ms"] for f in frames[:4]] == [0.0, 33.333, 66.667, 100.0]
    assert frames[-1]["t_ms"] == pytest.approx(last, abs=0.001) and frames[-1]["t_ms"] <= last + 1e-9
    steps = np.diff([f["t_ms"] for f in frames])
    assert abs(steps - 1000 / 30).max() < 0.0011
    assert skeleton["resample"] == {"fps": 30, "source_frames": 107,
                                    "method": "linear blend then fixed-length rebuild"}


def test_ac_v03_every_frame_names_its_bracketing_input_frames_and_weight(real_doc):
    frames = run(real_doc, 30)["frames"]
    assert frames[0]["source"] == {"frames": [0, 0], "weight": 0.0}
    assert frames[1]["source"] == {"frames": [0, 1], "weight": 0.499993}
    assert frames[2]["source"] == {"frames": [1, 1], "weight": 0.0}  # lands exactly on input frame 1
    assert frames[-1]["source"] == {"frames": [106, 106], "weight": 0.0}
    for frame in frames:
        a, b = frame["source"]["frames"]
        assert a <= b <= a + 1 and 0 <= frame["source"]["weight"] < 1
        assert list(frame) == ["frame", "t_ms", "people", "source"]


def test_ac_v03_bone_variation_stays_under_two_percent_and_the_file_validates(real_doc):
    for fps in (1, 7.5, 30, 60, 240):
        skeleton = run(real_doc, fps)
        assert variation(skeleton) < 0.02
        validate_skeleton(skeleton)


def test_ac_v03_resampling_at_the_input_rate_reproduces_the_frames(clip):
    plain, same = cli.process(clip, **CLEAN), run(clip, 15)
    assert len(same["frames"]) == len(plain["frames"])
    a, _, _ = skeleton_arrays(plain)
    b, _, _ = skeleton_arrays(same)
    assert abs(a - b).max() <= 1.5e-4 + 1e-9
    assert all(f["source"]["weight"] == 0.0 for f in same["frames"])
    assert [f["t_ms"] for f in same["frames"]] == [f["t_ms"] for f in plain["frames"]]


def test_a_blend_sits_between_its_brackets(clip):
    twice = run(clip, 30)
    J, _, present = skeleton_arrays(twice)
    for i in range(1, len(twice["frames"]) - 1, 2):
        before, after = J[i - 1], J[i + 1]  # grid frames on the input frames, the middle one is a blend
        middle = J[i]
        assert abs(middle - (before + after) / 2).max() < 0.02  # a blend of two near poses stays near their mean


def test_a_blended_frame_keeps_the_lower_conf_and_the_union_of_repairs(clip):
    plain = cli.process(clip, **CLEAN)
    out = run(clip, 30)
    for frame in out["frames"]:
        a, b = frame["source"]["frames"]
        confs = [plain["frames"][k]["people"][0]["joints"]["right_ankle"]["conf"] for k in (a, b)]
        assert frame["people"][0]["joints"]["right_ankle"]["conf"] == min(confs)


def test_the_person_block_still_describes_the_input_clip(real_doc):
    plain, out = cli.process(real_doc, **CLEAN), run(real_doc, 30)
    assert out["person"] == plain["person"] and out["input"] == plain["input"]
    assert out["bone_lengths_m"] == plain["bone_lengths_m"]


def test_a_single_frame_clip_gives_one_frame(clip):
    one = copy.deepcopy(clip)
    one["frames"] = one["frames"][:1]
    out = run(one, 30)
    assert len(out["frames"]) == 1 and out["frames"][0]["source"] == {"frames": [0, 0], "weight": 0.0}


def test_a_clip_with_a_non_zero_start_keeps_its_clock(clip):
    late = copy.deepcopy(clip)
    for frame in late["frames"]:
        frame["t_ms"] = round(frame["t_ms"] + 1000.0, 3)
    out = run(late, 30)
    assert out["frames"][0]["t_ms"] == 1000.0 and out["frames"][1]["t_ms"] == 1033.333


def test_frame_numbers_in_source_are_the_inputs_own_frame_numbers(clip):
    shifted = copy.deepcopy(clip)
    for frame in shifted["frames"]:
        frame["frame"] += 100
    out = run(shifted, 30)
    assert out["frames"][1]["source"]["frames"] == [100, 101] and out["frames"][1]["frame"] == 1


# --- a gap is never blended across ---------------------------------------------------------------------------

def gapped(clip, gap):
    doc = copy.deepcopy(clip)
    for k in gap:
        doc["frames"][k]["people"] = []
    return doc


def test_ac_v03_a_frame_bracketed_by_an_absent_person_is_empty(clip):
    out = run(gapped(clip, range(10, 13)), 30)
    for frame in out["frames"]:
        a, b = frame["source"]["frames"]
        holds = a not in range(10, 13) and b not in range(10, 13)
        assert bool(frame["people"]) == holds, frame["frame"]
    empty = [f["frame"] for f in out["frames"] if not f["people"]]
    # grid frame 18 sits exactly on present input frame 9 and 26 on frame 13; 19 to 25 touch the gap
    assert empty == list(range(19, 26))
    validate_skeleton(out)


def test_a_grid_frame_exactly_on_a_present_frame_next_to_a_gap_is_kept(clip):
    out = run(gapped(clip, [5]), 15)
    assert [bool(f["people"]) for f in out["frames"][:7]] == [True, True, True, True, True, False, True]


def test_a_person_present_in_one_frame_only_keeps_that_frame_at_the_input_rate(clip):
    out = run(gapped(clip, [k for k in range(30) if k != 4]), 15)
    assert [f["frame"] for f in out["frames"] if f["people"]] == [4]


def test_nothing_left_after_resampling_is_an_error(clip):
    out = gapped(clip, [k for k in range(30) if k != 4])
    with pytest.raises(ContractError) as caught:
        run(out, 20)  # no grid time lands on frame 4
    assert caught.value.path == "--fps"


# --- errors ----------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("value", [0, 0.5, 240.5, 1000, -30, "fast", "", True, float("nan"), "inf"])
def test_ac_v03_fps_out_of_range_names_the_option(clip, value):
    with pytest.raises(ContractError) as caught:
        run(clip, value)
    assert str(caught.value).startswith("--fps: must be 1 to 240")


def test_fps_limits_and_text_are_accepted():
    assert resample.check_fps("30") == 30 and resample.check_fps(1) == 1 and resample.check_fps(240.0) == 240
    assert resample.check_fps("7.5") == 7.5 and isinstance(resample.check_fps(30.0), int)


def test_times_that_do_not_increase_cannot_be_resampled(clip):
    bad = copy.deepcopy(clip)
    bad["frames"][5]["t_ms"] = bad["frames"][4]["t_ms"]
    with pytest.raises(ContractError) as caught:
        run(bad, 30)
    assert caught.value.path == "pose3d.frames[5].t_ms" and "must increase" in str(caught.value)
    assert cli.process(bad, **CLEAN)  # without --fps the same input is fine


def test_the_input_is_not_modified(clip):
    before = copy.deepcopy(clip)
    run(clip, 30)
    assert clip == before


def test_resampling_works_with_every_profile(clip):
    for body in ("part4-rig", "measured"):
        out = run(clip, 30, body=body)
        assert variation(out) < 0.02 and out["body"]["profile"] == body
        validate_skeleton(out)


# --- review B1: the grid has a frame cap ---------------------------------------------------------------------

def two_frames(real_doc, last_ms, first_ms=0.0):
    """The first two frames of the real clip with the second moved to `last_ms`: a tiny upload with a long span."""
    doc = copy.deepcopy(real_doc)
    doc["frames"] = doc["frames"][:2]
    doc["frames"][0]["t_ms"], doc["frames"][1]["t_ms"] = first_ms, last_ms
    return doc


def test_b1_the_cap_is_one_hundred_thousand_frames():
    assert resample.MAX_FRAMES == 100_000


def test_b1_a_two_frame_file_with_a_ten_thousand_second_span_is_refused_before_any_work(real_doc):
    start = time.perf_counter()
    with pytest.raises(ContractError) as caught:
        run(two_frames(real_doc, 10_000_000), 60)
    assert str(caught.value) == "--fps 60 would write 600001 frames; the limit is 100000"
    assert caught.value.path == "--fps 60" and time.perf_counter() - start < 1.0


def test_b1_a_span_of_1e300_ms_names_the_option_and_does_not_overflow(real_doc):
    with pytest.raises(ContractError) as caught:
        run(two_frames(real_doc, 1e300), 30)
    assert str(caught.value) == "--fps 30 would write 3e+298 frames; the limit is 100000"


def test_b1_a_span_past_the_float_range_is_refused_the_same_way(real_doc):
    with pytest.raises(ContractError, match=r"^--fps 30 would write more frames than the limit of 100000: "
                                            r"the clip span \(first to last t_ms\) is not finite$"):
        run(two_frames(real_doc, 1.7e308, first_ms=-1.7e308), 30)


def test_b1_the_grid_count_is_the_frames_the_resample_writes(real_doc):
    doc = two_frames(real_doc, 3000.0)
    assert resample.grid_count(0.0, 3000.0, 10) == 31 == len(run(doc, 10)["frames"])
    assert resample.grid_count(0.0, 3000.0, 7.5) == len(run(doc, 7.5)["frames"])


def test_b1_exactly_the_cap_passes_and_one_more_frame_does_not():
    assert resample.grid_count(0.0, 99_999_000.0, 1) == 100_000  # 99,999 s at 1 fps is 100,000 frames
    with pytest.raises(ContractError, match=r"^--fps 1 would write 100001 frames; the limit is 100000$"):
        resample.grid_count(0.0, 100_000_000.0, 1)


def test_b1_max_frames_refuses_what_the_default_cap_accepts():
    assert resample.grid_count(0.0, 50_000_000.0, 1) == 50_001  # fine under 100,000 ...
    with pytest.raises(ContractError, match=r"^--fps 1 would write 50001 frames; the limit is 20000$"):
        resample.grid_count(0.0, 50_000_000.0, 1, max_frames=20_000)  # ... not under the server's 20,000


def test_b1_process_takes_max_frames_and_checks_it_before_the_pipeline_runs(real_doc):
    doc = two_frames(real_doc, 3000.0)
    assert len(run(doc, 10, max_frames=31)["frames"]) == 31
    with pytest.raises(ContractError, match=r"^--fps 10 would write 31 frames; the limit is 30$"):
        run(doc, 10, max_frames=30)
    with pytest.raises(ContractError, match=r"the limit is 30$"):
        cli.process_all(doc, fps=10, max_frames=30, **CLEAN)
    assert len(run(doc, 10, max_frames=None)["frames"]) == 31  # None means the default cap


def test_b1_without_fps_the_span_is_not_limited(real_doc):
    skeleton = cli.process(two_frames(real_doc, 1e300), **CLEAN)
    assert [f["t_ms"] for f in skeleton["frames"]] == [0.0, 1e300]


def test_b1_times_that_do_not_increase_are_still_named_before_the_cap(real_doc):
    doc = two_frames(real_doc, 0.0)
    with pytest.raises(ContractError) as caught:
        run(doc, 30)
    assert caught.value.path == "pose3d.frames[1].t_ms"
