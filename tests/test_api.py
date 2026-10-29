"""part5.api.handle: the analysis API without sockets (docs/specs/staging.md, AC-S02 to AC-S09)."""
import json
import threading
import time
from pathlib import Path

import pytest

from part5 import api, pipeline

ROOT = Path(__file__).resolve().parent.parent
LABELS = json.loads((ROOT / "fixtures/input/followers/labels.json").read_text())
GOOD_FRONT = [t for t in LABELS["takes"] if (t["set"], t["angle"], t["lighting"]) == ("exercise", "front", "good")]
FOOT_TAKE = next(t for t in GOOD_FRONT if [f["type"] for f in t["faults"]] == ["foot_out"])
FOOT_OUT = FOOT_TAKE["take_id"]
CORRECT = next(t["take_id"] for t in GOOD_FRONT if not t["faults"])
FOOT_PATH = ROOT / FOOT_TAKE["follower"]
EXPECTED_PATH = ROOT / FOOT_TAKE["expected"]
EXPECTED_FRAMES = len(json.loads(EXPECTED_PATH.read_text())["frames"])


def call(method, path, payload=None, *, base="/", raw=None):
    body = raw if raw is not None else (b"" if payload is None else json.dumps(payload).encode())
    status, headers, out = api.handle(method, path, body, base_path=base)
    return status, headers, json.loads(out)


def analyse(expected, follower, **extra):
    return call("POST", "/api/analyse", {"expected": expected, "follower": follower, **extra})


def samples(expected="exercise", follower=FOOT_OUT):
    return {"sample": expected}, {"sample": follower}


def foot_doc():
    return json.loads(FOOT_PATH.read_text())


def error_of(response):
    status, _, body = response
    return status, body["error"]["field"], body["error"]["message"]


# ----------------------------------------------------------------------------- health and samples

def test_health_answers_ok_with_the_version():
    status, headers, body = call("GET", "/api/health")
    assert status == 200 and body["ok"] is True and body["version"]
    assert headers["Content-Type"].startswith("application/json")


def test_AC_S02_health_answers_under_the_staging_base_path_only_there():
    assert call("GET", "/simon-part-5/api/health", base="/simon-part-5/")[0] == 200
    assert call("GET", "/simon-part-5/api/health", base="/simon-part-5")[0] == 200
    assert call("GET", "/api/health", base="/simon-part-5/")[0] == 404
    assert call("GET", "/api/health?probe=1", base="/")[0] == 200


def test_contract_serves_what_part5_contract_json_prints():
    from part5.contract import contract_document
    status, _, body = call("GET", "/simon-part-5/api/contract", base="/simon-part-5/")
    assert status == 200
    assert body == json.loads(json.dumps(contract_document()))
    assert {s["name"] for s in body["schemas"]} >= {"analysis", "metrics"}


def test_samples_lists_the_two_expected_clips_and_every_labelled_take(monkeypatch):
    monkeypatch.delenv("META_LIVE", raising=False)
    status, _, body = call("GET", "/api/samples")
    assert status == 200
    assert {e["id"] for e in body["expected"]} == {"exercise", "dance"}
    assert {e["label"] for e in body["expected"]} == {"Squat (exercise)", "Step touch (dance)"}
    ids = [t["id"] for t in body["followers"]]
    assert ids == [t["take_id"] for t in LABELS["takes"]] and len(set(ids)) == len(ids)
    assert body["phrasing"] == ["template"]


def test_samples_carry_set_angle_light_and_the_fault_in_the_label():
    followers = {t["id"]: t for t in call("GET", "/api/samples")[2]["followers"]}
    foot = followers[FOOT_OUT]
    assert (foot["set"], foot["angle"], foot["light"]) == ("exercise", "front", "good")
    assert "foot" in foot["label"].lower() and foot["faults"][0]["type"] == "foot_out"
    assert followers[CORRECT]["faults"] == [] and "orrect" in followers[CORRECT]["label"]
    groups = {}
    for t in followers.values():
        groups.setdefault((t["set"], t["angle"], t["light"]), []).append(t["id"])
    labelled = {(t["set"], t["angle"], t["lighting"]) for t in LABELS["takes"]}
    assert set(groups) == labelled and {"exercise", "dance"} == {g[0] for g in groups}


def test_every_sample_resolves_to_a_fixture_file_under_the_table():
    t = api.table()
    assert set(t.expected) == {"exercise", "dance"} and len(t.follower) == len(LABELS["takes"])
    assert all(s.path.is_file() and s.rel.startswith("fixtures/input/") for s in [*t.expected.values(), *t.follower.values()])


# ----------------------------------------------------------------------------- analyse

def test_AC_S04_analyse_runs_the_real_pipeline_on_picked_samples(monkeypatch):
    seen = []
    real_run = pipeline.run
    monkeypatch.setattr(api, "run", lambda *a, **k: seen.append((a, k)) or real_run(*a, **k))
    status, _, body = analyse(*samples())
    assert status == 200 and len(seen) == 1
    direct = pipeline.analyse(str(EXPECTED_PATH), str(FOOT_PATH))
    assert "foot_out" in [f["measure"] for f in body["analysis"]["faults"]]
    assert body["analysis"]["faults"] == direct["faults"]
    assert body["analysis"]["format"] == "simon.analysis.v1"
    assert body["analysis"]["expected"] == {"path": "fixtures/input/expected/exercise/animation.json",
                                            "set": "exercise", "movement": "squat"}
    assert body["analysis"]["follower"]["take_id"] == FOOT_OUT
    assert "doc" not in json.dumps(body["analysis"]["follower"])


def test_AC_S04_no_precomputed_analysis_is_shipped_with_the_page():
    assert list((ROOT / "web").rglob("*.json")) == []


def test_analyse_returns_the_replay_matched_to_the_expected_frames():
    _, _, body = analyse(*samples())
    replay = body["replay"]
    assert len(replay["exp_to_fol"]) == len(replay["expected"]) == EXPECTED_FRAMES
    assert len(replay["follower"]) == FOOT_TAKE["frame_count"] and max(replay["exp_to_fol"]) < FOOT_TAKE["frame_count"]
    assert replay["joints"][0] == "nose" and replay["fps"] == 30.0


def test_a_correct_take_gets_an_empty_fault_list():
    _, _, body = analyse(*samples(follower=CORRECT))
    assert body["analysis"]["faults"] == []


def test_a_dance_take_against_the_dance_clip_is_analysed():
    take = next(t["take_id"] for t in LABELS["takes"] if t["set"] == "dance")
    status, _, body = analyse(*samples("dance", take))
    assert status == 200 and body["analysis"]["expected"]["movement"] == "step_touch"


def test_an_upload_as_text_and_as_an_object_give_the_same_faults():
    sample = analyse(*samples())[2]["analysis"]["faults"]
    expected = {"sample": "exercise"}
    as_object = analyse(expected, {"upload": foot_doc()})
    as_text = analyse(expected, {"upload": json.dumps(foot_doc())})
    assert as_object[0] == as_text[0] == 200
    assert as_object[2]["analysis"]["faults"] == as_text[2]["analysis"]["faults"] == sample
    assert as_text[2]["analysis"]["follower"] == {"path": "follower.upload"}


def test_muse_spark_is_offered_only_with_the_key_file_and_meta_live(monkeypatch, tmp_path):
    """Staging offers muse-spark only when the server has the key and META_LIVE=1; the key never leaves."""
    key = tmp_path / "BASETEN_API_KEY"
    monkeypatch.setenv("PART5_BASETEN_KEY_FILE", str(key))
    monkeypatch.setenv("META_LIVE", "1")
    assert "muse-spark" not in call("GET", "/api/samples")[2]["phrasing"]
    assert error_of(analyse(*samples(), phrasing="muse-spark"))[:2] == (400, "phrasing")
    key.write_text("sentinel-key-value\n")
    status, _, raw = api.handle("GET", "/api/samples", b"", base_path="/")
    assert "muse-spark" in json.loads(raw)["phrasing"] and b"sentinel-key-value" not in raw
    monkeypatch.setenv("META_LIVE", "0")
    assert "muse-spark" not in call("GET", "/api/samples")[2]["phrasing"]


def test_phrasing_template_is_accepted_and_an_unknown_backend_is_a_400_on_phrasing():
    assert analyse(*samples(), phrasing="template")[0] == 200
    status, field, message = error_of(analyse(*samples(), phrasing="nope"))
    assert (status, field) == (400, "phrasing") and "template" in message
    assert error_of(analyse(*samples(), phrasing=7))[:2] == (400, "phrasing")


# ----------------------------------------------------------------------------- AC-S05, AC-S09 and request errors

def test_AC_S05_an_upload_over_16_mib_is_413_with_a_plain_message():
    big = "x" * (17 * 1024 * 1024)
    assert error_of(analyse({"sample": "exercise"}, {"upload": big})) == (
        413, "follower.upload", "follower.upload: larger than 16 MiB")
    assert error_of(analyse({"upload": big}, {"sample": FOOT_OUT}))[:2] == (413, "expected.upload")


def test_AC_S05_a_body_beyond_two_uploads_is_413_without_being_read():
    status, field, message = error_of(call("POST", "/api/analyse", raw=b"{" + b" " * (api.MAX_BODY_BYTES + 1)))
    assert (status, field, message) == (413, "upload", "upload: larger than 16 MiB")


def test_AC_S05_a_bad_joint_is_a_400_naming_the_field_and_no_trace():
    doc = foot_doc()
    doc["frames"][12]["joints"]["left_knee"] = "not a list"
    response = analyse({"sample": "exercise"}, {"upload": doc})
    status, field, message = error_of(response)
    assert (status, field) == (400, "follower.upload")
    assert message.startswith("follower.upload: ") and "frames[12].joints.left_knee" in message
    assert "Traceback" not in json.dumps(response[2])


def test_AC_S05_an_upload_that_is_not_json_is_a_400_on_that_side():
    assert error_of(analyse({"sample": "exercise"}, {"upload": "{not json"})) == (
        400, "follower.upload", "follower.upload: not JSON")
    assert error_of(analyse({"upload": "]"}, {"sample": FOOT_OUT}))[:2] == (400, "expected.upload")


def test_AC_S05_a_request_body_that_is_not_json_is_a_400_on_the_body():
    assert error_of(call("POST", "/api/analyse", raw=b"{oops"))[:2] == (400, "body")
    assert error_of(call("POST", "/api/analyse", raw=b"[1, 2]"))[:2] == (400, "body")
    assert error_of(call("POST", "/api/analyse", raw=b"\xff\xfe\x00"))[:2] == (400, "body")


def test_a_clip_over_6000_frames_is_a_400_before_it_is_parsed():
    doc = foot_doc()
    doc["frames"] = [{}] * 6001
    status, field, message = error_of(analyse({"sample": "exercise"}, {"upload": doc}))
    assert (status, field) == (400, "follower.upload") and "6001" in message and "6000" in message


def test_a_clip_that_cannot_be_compared_names_the_side_in_the_message():
    doc = foot_doc()
    doc["format"] = "something.else"
    status, field, message = error_of(analyse({"upload": doc}, {"sample": FOOT_OUT}))
    assert (status, field) == (400, "expected.upload") and "format" in message


def test_a_long_bad_value_is_cut_short_in_the_message():
    doc = foot_doc()
    doc["frames"][0]["joints"]["nose"] = ["y" * 5000]
    message = error_of(analyse({"sample": "exercise"}, {"upload": doc}))[2]
    assert len(message) <= api.MAX_MESSAGE_CHARS


def test_AC_S09_an_unknown_sample_id_is_a_404_and_no_file_outside_the_table_is_read(monkeypatch):
    opened = []
    real_open = Path.open

    def spy(self, *args, **kwargs):
        opened.append(str(self))
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", spy)  # Path.read_text goes through Path.open
    for evil in ("../../etc/passwd", "/etc/passwd", "..\\..\\windows", "exercise/../../x", "%2e%2e/%2e%2e/etc/passwd"):
        status, field, message = error_of(analyse({"sample": "exercise"}, {"sample": evil}))
        assert (status, field) == (404, "follower.sample") and message.startswith("follower.sample: no sample named ")
    assert opened and not [p for p in opened if "passwd" in p or "windows" in p]
    assert error_of(analyse({"sample": "../../etc/passwd"}, {"sample": FOOT_OUT}))[:2] == (404, "expected.sample")


def test_a_take_id_is_not_an_expected_sample_and_the_other_way_round():
    assert error_of(analyse({"sample": FOOT_OUT}, {"sample": FOOT_OUT}))[:2] == (404, "expected.sample")
    assert error_of(analyse({"sample": "exercise"}, {"sample": "exercise"}))[:2] == (404, "follower.sample")


def test_each_side_needs_exactly_one_of_sample_or_upload():
    both = {"sample": "exercise", "upload": {}}
    for bad in (both, {}, None, "exercise", ["exercise"]):
        assert error_of(analyse(bad, {"sample": FOOT_OUT}))[:2] == (400, "expected")
    assert error_of(call("POST", "/api/analyse", {"expected": {"sample": "exercise"}}))[:2] == (400, "follower")


def test_a_sample_id_must_be_text():
    for bad in (7, ["exercise"], {"a": 1}, None):
        assert error_of(analyse({"sample": bad}, {"sample": FOOT_OUT}))[:2] == (400, "expected.sample")


# ----------------------------------------------------------------------------- routing, timeout, 500

def test_wrong_method_is_405_with_allow_and_unknown_address_is_404():
    status, headers, _ = call("GET", "/api/analyse")
    assert status == 405 and headers["Allow"] == "POST"
    status, headers, _ = call("POST", "/api/health", {})
    assert status == 405 and headers["Allow"] == "GET"
    assert call("GET", "/api/nothing")[0] == 404 and call("GET", "/elsewhere")[0] == 404
    assert call("GET", "/api/health/")[0] == 404


def test_AC_S05_analysis_over_the_time_limit_is_a_503(monkeypatch):
    done = threading.Event()

    def slow(*args, **kwargs):
        time.sleep(0.4)
        done.set()
        raise RuntimeError("late")

    monkeypatch.setattr(api, "run", slow)
    monkeypatch.setattr(api, "ANALYSIS_TIMEOUT_S", 0.1)
    status, field, message = error_of(analyse(*samples()))
    assert (status, field, message) == (503, "analysis", "analysis took longer than 0.1 s")
    assert done.wait(2)
    time.sleep(0.05)  # the worker releases the lock right after


def test_only_one_analysis_runs_at_a_time(monkeypatch):
    release = threading.Event()
    monkeypatch.setattr(api, "run", lambda *a, **k: release.wait(2))
    monkeypatch.setattr(api, "ANALYSIS_TIMEOUT_S", 0.15)
    assert error_of(analyse(*samples()))[0] == 503
    status, field, message = error_of(analyse(*samples()))
    assert (status, field) == (503, "analysis") and "still running" in message
    release.set()
    time.sleep(0.1)


def test_a_500_never_shows_a_trace_or_the_error(monkeypatch, caplog):
    def broken(*args, **kwargs):
        raise RuntimeError("secret detail from /home/someone/private.py")

    monkeypatch.setattr(api, "run", broken)
    status, headers, raw = api.handle("POST", "/api/analyse", json.dumps(
        {"expected": {"sample": "exercise"}, "follower": {"sample": FOOT_OUT}}).encode(), base_path="/")
    text = raw.decode()
    assert status == 500 and json.loads(text)["error"]["field"] == "server"
    assert "Traceback" not in text and "secret detail" not in text and "private.py" not in text
    assert any(r.exc_info for r in caplog.records)  # the trace goes to the log, not the visitor


# ----------------------------------------------------------------------------- base path

@pytest.mark.parametrize("given,expected", [("", "/"), ("/", "/"), ("/simon-part-5", "/simon-part-5/"),
                                            ("/simon-part-5/", "/simon-part-5/"), ("a/b", "/a/b/")])
def test_normalise_base_path(given, expected):
    assert api.normalise_base_path(given) == expected


@pytest.mark.parametrize("bad", ["/a b/", "/../x/", "/a//b/", "/x?y=1", "/x#"])
def test_normalise_base_path_refuses_odd_paths(bad):
    with pytest.raises(ValueError, match="base path"):
        api.normalise_base_path(bad)
