"""part6/processor.py: the mock processor seam (AC-008a, AC-C09) and its locked parameters, and
the fake Part 4 processors that exercise the seam (AC-C11)."""
import hashlib
import inspect
import math
import time
from pathlib import Path

import pytest

from fixtures.processors import part4_fake
from part6 import formats, jobs, motion, processor, validate

PART6 = Path(__file__).resolve().parents[2] / "part6"


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


def test_the_mock_description_is_one_constant_used_by_the_jobs_and_the_conformance_kit():
    assert processor.MOCK_DESCRIPTION.format(day="2026-10-28") == (
        "Mock recording from 2026-10-28. Capture and processing are mocked.")
    root = PART6.parent
    copies = [p.relative_to(root).as_posix() for p in [*PART6.glob("*.py"), *(root / "fixtures").rglob("*.py")]
              if "Capture and processing are mocked" in p.read_text()]
    assert copies == ["part6/processor.py"]
    from fixtures.conformance import make_entries
    assert make_entries.MOCK_DESCRIPTION == processor.MOCK_DESCRIPTION.format(day="2026-10-28")


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


# the plug-in contract (AC-C09)

def test_the_signature_is_recording_then_an_optional_report():
    params = inspect.signature(processor.process).parameters
    assert list(params) == ["recording", "report"] and params["report"].default is None


def test_the_default_spec_names_the_mock():
    assert processor.DEFAULT == jobs.DEFAULT_PROCESSOR == "part6.processor:process"
    assert jobs.parse_processor(processor.DEFAULT) is processor.process


def test_the_mock_ignores_report_and_never_calls_it():
    calls = []
    with_report = processor.process(recording(), calls.append)
    assert calls == [] and with_report == processor.process(recording())
    assert with_report == processor.process(recording(), report=None)


def test_the_module_documents_the_plug_in_contract():
    doc = processor.__doc__
    for text in ("serve --processor <module>:<function>", "SIMON6_PROCESSOR", "function(recording, report)",
                 "{id, name, category, duration_ms, video_path}", "processing:<stage>",
                 "^[a-z0-9][a-z0-9_-]{0,31}$", '{"status": "failed:<stage>: <reason>"}',
                 "failed:validate", "`queued`, `processing:<stage>`, `failed:<stage>: <reason>`",
                 'files_source: "mock"', "processor"):
        assert text in doc, text


def test_no_part6_module_imports_the_fake_processors():
    for path in PART6.glob("*.py"):
        text = path.read_text()
        assert "import fixtures" not in text and "from fixtures" not in text, path.name


# the fake Part 4 processors (AC-C11)

@pytest.fixture
def fast(monkeypatch):
    monkeypatch.setenv(part4_fake.STAGE_ENV, "0")


def test_the_fake_reports_three_stages_in_order_and_returns_part4_v1_files(fast):
    reports = []
    out = part4_fake.process(recording(), reports.append)
    assert reports == ["processing:keyframes", "processing:skeleton", "processing:animation"]
    assert set(out) == {"keyframes", "skeleton", "animation"}
    assert out["keyframes"]["format"] == "simon.keyframes.v1"
    assert out["skeleton"]["format"] == "simon.skeleton.v1"
    assert out["animation"]["format"] == "simon.animation.v1"
    assert formats.read_keyframes(out["keyframes"])["format"] == "simon.keyframes.v1"
    assert formats.read_skeleton(out["skeleton"])["format"] == "simon.skeleton.v1"
    assert formats.read_animation(out["animation"])["format"] == "simon.animation.v1"


def test_the_fake_skeleton_is_the_key_poses_only_golden(fast):
    skeleton = formats.read_skeleton(part4_fake.process(recording())["skeleton"])
    assert skeleton["frames"] is None and skeleton["keys"]


def test_the_fake_works_without_a_report_and_gives_a_fresh_copy_each_time(fast):
    first = part4_fake.process(recording())
    first["animation"]["frames"].clear()
    assert part4_fake.process(recording())["animation"]["frames"]


def test_the_fake_pauses_at_every_stage(monkeypatch):
    monkeypatch.setenv(part4_fake.STAGE_ENV, "0.05")
    began = time.monotonic()
    part4_fake.process(recording())
    assert time.monotonic() - began >= 0.15


def test_the_pause_defaults_to_1_2_seconds_and_follows_the_environment(monkeypatch):
    monkeypatch.delenv(part4_fake.STAGE_ENV, raising=False)
    assert part4_fake.stage_seconds() == 1.2
    monkeypatch.setenv(part4_fake.STAGE_ENV, "")
    assert part4_fake.stage_seconds() == 1.2
    monkeypatch.setenv(part4_fake.STAGE_ENV, "0.5")
    assert part4_fake.stage_seconds() == 0.5
    monkeypatch.setenv(part4_fake.STAGE_ENV, "0")
    assert part4_fake.stage_seconds() == 0


@pytest.mark.parametrize("value", ["abc", "-1", "nan", "1,5"])
def test_a_bad_pause_is_a_plain_error(monkeypatch, value):
    monkeypatch.setenv(part4_fake.STAGE_ENV, value)
    with pytest.raises(ValueError, match=part4_fake.STAGE_ENV):
        part4_fake.stage_seconds()


def test_the_failing_fake_reports_pose_and_fails():
    reports = []
    assert part4_fake.fail(recording(), reports.append) == {
        "status": "failed:pose: no person found in the video"}
    assert reports == ["processing:pose"]
    assert part4_fake.fail(recording()) == {"status": "failed:pose: no person found in the video"}


def test_the_fakes_load_by_spec_and_say_what_they_are():
    assert jobs.parse_processor("fixtures.processors.part4_fake:process") is part4_fake.process
    assert jobs.parse_processor("fixtures.processors.part4_fake:fail") is part4_fake.fail
    assert "not a production path" in part4_fake.__doc__
