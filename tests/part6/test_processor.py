"""part6/processor.py: the mock processor seam (AC-008a) and its locked parameters."""
import hashlib
import math

import pytest

from part6 import motion, processor, validate


def recording(entry_id="squat-ab12cd34", category="exercise", duration_ms=10000, name="Squat"):
    return {"id": entry_id, "name": name, "category": category, "duration_ms": duration_ms,
            "video_path": None}


def test_output_has_the_three_shared_files_and_they_validate():
    out = processor.process(recording())
    assert set(out) == {"keyframes", "skeleton", "animation"}
    assert validate.check_keyframes(out["keyframes"]) == []
    assert validate.check_skeleton(out["skeleton"]) == []
    assert validate.check_animation(out["animation"]) == []


@pytest.mark.parametrize("category", motion.CATEGORIES)
def test_every_family_of_the_category_validates(category):
    seen = set()
    for n in range(60):
        out = processor.process(recording(f"m-{n:08x}", category, 3000))
        assert validate.check_animation(out["animation"]) == []
        seen.add(out["keyframes"]["people"][0]["repetitions"][0]["movement"])
    assert seen == {f.id for f in motion.by_category(category)}


def test_seed_is_the_first_eight_hex_digits_of_sha256_of_the_id():
    assert processor.seed_from_id("abc") == int(hashlib.sha256(b"abc").hexdigest()[:8], 16)


def test_same_id_same_files_different_ids_different_animation():
    a1 = processor.process(recording("a-00000001", "dance", 2000))
    a2 = processor.process(recording("a-00000001", "dance", 2000))
    b = processor.process(recording("a-00000002", "dance", 2000))
    assert a1 == a2
    assert a1["animation"] != b["animation"]


def test_two_recordings_with_the_same_name_and_duration_differ():
    outs = [processor.process(recording(f"same-{n:08x}", "dance", 2000)) for n in range(12)]
    assert len({str(o["animation"]["frames"][30]) for o in outs}) == 12


def test_video_path_is_never_read():
    out = processor.process(dict(recording(), video_path="/no/such/video.webm"))
    assert validate.check_animation(out["animation"]) == []


def test_mock_params_follow_the_locked_table():
    for seed in range(300):
        for category in motion.CATEGORIES:
            duration_ms = 1000 + seed * 397
            family_id, p = processor.mock_params(seed, category, duration_ms)
            family = motion.FAMILIES[family_id]
            assert family.category == category
            seconds = duration_ms / 1000
            assert p.reps >= 1 and math.isclose(p.reps * p.period_s, seconds)
            assert p.start_s == 0.0
            assert all(0.7 <= v <= 1.0 for v in (p.depth, p.arm, p.step))
            # reps = max(1, floor(d / min(base * tempo, d))) with tempo from 0.8 to 1.25
            most = math.floor(seconds / min(family.base_period_s * 0.8, seconds))
            least = math.floor(seconds / min(family.base_period_s * 1.25, seconds))
            assert max(1, least) <= p.reps <= max(1, most)


def test_mock_params_are_deterministic_per_seed():
    assert processor.mock_params(7, "dance", 5000) == processor.mock_params(7, "dance", 5000)
    assert processor.mock_params(7, "dance", 5000) != processor.mock_params(8, "dance", 5000)


@pytest.mark.parametrize("duration_ms,animation,skeleton", [
    (1000, 30, 15), (1234, 37, 19), (2000, 60, 30), (10000, 300, 150), (120000, 3600, 1800)])
def test_frame_counts_and_rates(duration_ms, animation, skeleton):
    out = processor.process(recording(duration_ms=duration_ms))
    assert processor.frame_counts(duration_ms) == (animation, skeleton)
    assert len(out["animation"]["frames"]) == animation
    assert len(out["skeleton"]["frames"]) == skeleton
    assert out["animation"]["fps"] == 30.0
    frames = out["animation"]["frames"]
    assert [f["t_ms"] for f in frames[:3]] == [0.0, 33.333, 66.667]
    assert all(f["t_ms"] == round(f["frame"] * 1000 / 30.0, 3) for f in frames)


def test_interpolated_frames_are_the_odd_ones_and_skeleton_frames_share_t_ms():
    out = processor.process(recording(duration_ms=2000))
    frames = out["animation"]["frames"]
    assert [f["interpolated"] for f in frames[:4]] == [False, True, False, True]
    assert [f["t_ms"] for f in out["skeleton"]["frames"]] == [f["t_ms"] for f in frames[::2]]
    third = out["skeleton"]["frames"][3]["people"][0]
    assert third["joints"] == frames[6]["people"][0]["joints"] and third["flips_repaired"] == []


def test_keyframes_header_and_marks():
    out = processor.process(recording("hold-00000001", "dance", 8000))
    kf = out["keyframes"]
    assert kf["video"] is None and kf["fps"] == 30.0 and kf["analysis_fps"] == 30.0
    assert kf["quality"] == {"verdict": "fine"}
    reps = kf["people"][0]["repetitions"]
    movement = reps[0]["movement"]
    names = motion.FAMILIES[movement].marks
    for n, rep in enumerate(reps, start=1):
        assert rep["rep"] == n and rep["movement"] == movement
        assert [m["name"] for m in rep["keyframes"]] == list(names)
        times = [m["t_ms"] for m in rep["keyframes"]]
        assert times == sorted(times)
        for m in rep["keyframes"]:
            assert m["frame"] == min(round(m["t_ms"] * 30 / 1000), 239)
    assert reps[0]["keyframes"][0]["t_ms"] == 0
    assert reps[-1]["keyframes"][2]["t_ms"] == 8000 and reps[-1]["keyframes"][2]["frame"] == 239


def test_bone_lengths_are_fixed_within_one_percent():
    out = processor.process(recording("fixed-00000001", "exercise", 6000))
    lengths = [processor._bone_lengths(f["people"][0]["joints"])
               for f in out["animation"]["frames"]]
    for bone, base in out["skeleton"]["bone_lengths_m"].items():
        values = [frame[bone] for frame in lengths]
        assert base > 0 and (max(values) - min(values)) / base < 0.01


def test_skeleton_follows_the_part_3_header():
    sk = processor.process(recording())["skeleton"]
    assert sk["schema"] == "simon.skeleton/1" and len(sk["bones"]) == 18
    assert sk["frame"]["origin"] == "hip_midpoint" and sk["person"]["id"] == 0
    assert len(sk["input"]["sha256"]) == 64


@pytest.mark.parametrize("bad", [
    {"category": "yoga"}, {"duration_ms": 0}, {"duration_ms": -5}, {"duration_ms": 1.5},
    {"duration_ms": True}, {"duration_ms": "2000"}])
def test_process_rejects_bad_recordings(bad):
    with pytest.raises(ValueError):
        processor.process(dict(recording(), **bad))
