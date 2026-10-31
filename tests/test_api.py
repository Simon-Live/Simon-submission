"""part5.api.handle: the analysis API without sockets (docs/specs/staging.md, AC-S02 to AC-S09)."""
import json
import re
import threading
import time
from pathlib import Path

import pytest

from part5 import api, pipeline, score_report, words
from part5.evaluate import canonical_label

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


KIT = json.loads((ROOT / "fixtures/input/contract/part3/followers/labels.json").read_text())
MISMATCH = json.loads((ROOT / "fixtures/input/mismatch/manifest.json").read_text())
REAL_IDS = ["part2-class", "part2-dance", "part2-single", "part2-stretch"]


def test_samples_lists_the_three_expected_clips_and_every_take_on_offer(monkeypatch):
    monkeypatch.delenv("META_LIVE", raising=False)
    status, _, body = call("GET", "/api/samples")
    assert status == 200
    assert [e["id"] for e in body["expected"]] == ["exercise", "dance", "part3-squat"]
    assert {e["label"] for e in body["expected"]} == {
        "Squat (exercise)", "Step touch (dance)", "Squat for the real takes (part3-squat)"}
    ids = [t["id"] for t in body["followers"]]
    generated = [t["take_id"] for t in LABELS["takes"]]
    kit = [t["take_id"] for t in KIT["takes"]]
    assert ids == generated + kit + REAL_IDS and len(set(ids)) == len(ids)
    assert len(kit) == 15
    assert body["phrasing"] == ["template"]


def test_the_kit_takes_are_listed_with_the_kit_labels_and_no_invented_light():
    followers = {t["id"]: t for t in call("GET", "/api/samples")[2]["followers"]}
    for take in KIT["takes"]:
        listed = followers[take["take_id"]]
        assert (listed["set"], listed["angle"], listed["light"], listed["source"]) == (
            "part3-squat", take["angle"], None, "kit")
        assert [f["text"] for f in listed["faults"]] == [f["text"] for f in take["faults"]]
        what = take["faults"][0]["text"] if take["faults"] else "correct take"
        assert listed["label"] == what[:1].upper() + what[1:]


def test_the_part2_clips_are_labelled_from_the_manifest_and_flag_the_expected_refusals():
    followers = {t["id"]: t for t in call("GET", "/api/samples")[2]["followers"]}
    assert followers["part2-class"]["label"] == "Cat-cow yoga class (real clip, a different movement)"
    assert followers["part2-dance"]["label"] == "Dancers crossing and swapping places (real clip, a different movement)"
    assert followers["part2-single"]["label"] == "Provisional barbell back squat (real clip)"
    assert followers["part2-stretch"]["label"] == "Seated cross-legged stretches (Pexels 6019962) (real clip, a different movement)"
    assert [followers[i]["refusal_expected"] for i in REAL_IDS] == [True, True, False, True]
    assert all(followers[i]["source"] == "real" and followers[i]["faults"] == [] for i in REAL_IDS)
    assert [MISMATCH["fixtures"][i]["population"] for i in REAL_IDS] == ["mismatch", "mismatch", "matched_reference", "mismatch"]


def test_a_duplicate_sample_id_stops_the_table_being_built(monkeypatch):
    clash = KIT["takes"][0]["take_id"]
    labels = json.loads(json.dumps(LABELS))
    labels["takes"][0]["take_id"] = clash
    real_read = Path.read_text

    def read(self, *args, **kwargs):
        text = real_read(self, *args, **kwargs)
        return json.dumps(labels) if self.name == "labels.json" and self.parent.name == "followers" \
            and "contract" not in self.parts else text

    monkeypatch.setattr(Path, "read_text", read)
    with pytest.raises(ValueError, match="share the id"):
        api.build_table()


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
    generated = {g for g in groups if g[0] in ("exercise", "dance")}
    assert generated == labelled
    assert {g for g in groups if g[0] == "part3-squat"} == {("part3-squat", a, None) for a in ("front", "45", "side")} | {
        ("part3-squat", None, None)}


def test_every_sample_resolves_to_a_fixture_file_under_the_table():
    t = api.table()
    assert set(t.expected) == {"exercise", "dance", "part3-squat"}
    assert len(t.follower) == len(LABELS["takes"]) + len(KIT["takes"]) + len(REAL_IDS)
    assert all(s.path.is_file() and s.rel.startswith("fixtures/input/") for s in [*t.expected.values(), *t.follower.values()])


def test_every_follower_in_the_list_is_analysed_against_its_own_expected_clip():
    """AC-V11 and the M3 drive depend on every listed pair running; one run per set is enough here."""
    for follower, expected in (("squat_side_knee_caving-left", "part3-squat"), ("part2-single", "part3-squat")):
        status, _, body = analyse({"sample": expected}, {"sample": follower})
        assert status == 200 and body["analysis"]["status"]["code"] == "ok", follower
        assert body["analysis"]["follower"] == {"path": api.table().follower[follower].rel, "take_id": follower}
        assert body["analysis"]["expected"]["set"] == "part3-squat"


def _analysed_with_low_match(analysis):
    """ADR-0012: a different movement is analysed, with a low_match warning and grade F."""
    return (analysis["status"]["code"] == "ok" and analysis["match"]["quality"] == "low"
            and [w["code"] for w in analysis["warnings"]] == ["low_match"]
            and analysis["score"]["grade"] == "F" and analysis["score"]["capped_by"] == ["low_match"])


def test_AC_S06_a_yoga_or_dance_clip_against_the_squat_is_analysed_with_a_warning_and_grade_f():
    for follower in ("part2-class", "part2-dance"):
        status, _, body = analyse({"sample": "part3-squat"}, {"sample": follower})
        assert status == 200 and _analysed_with_low_match(body["analysis"]), follower
        assert len(body["replay"]["exp_to_fol"]) == len(body["replay"]["expected"])  # the replay still comes back
    dance = next(t["take_id"] for t in LABELS["takes"] if t["set"] == "dance")
    assert _analysed_with_low_match(analyse(*samples(follower=dance))[2]["analysis"])


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


# A labelled take is analysed with the foot side files its label names (ADR-0015, AC-FOOT-18), as every other caller does.
FOOT_TURNED = next(t for t in LABELS["takes"] if t["take_id"] == "exercise_front_good_09_foot_turned_out-right")


def feet_of(body):
    return body["analysis"]["diagnostics"].get("feet")


def test_a_sample_take_is_analysed_with_the_foot_files_its_label_names():
    status, _, body = analyse(*samples(follower=FOOT_TURNED["take_id"]))
    assert status == 200
    faults = body["analysis"]["faults"]
    assert [(f["measure"], f["side"]) for f in faults] == [("foot_rotation", "right")]
    assert feet_of(body) is not None and feet_of(body)["follower"]["usable"]
    assert body["analysis"]["score"]["value"] < 100


def test_the_sample_answer_is_the_pipeline_run_with_the_labels_feet_files():
    names = score_report.feet_kwargs(FOOT_TURNED, ROOT)
    assert set(names) == {"expected_feet", "follower_feet"}
    direct = pipeline.run(str(ROOT / FOOT_TURNED["expected"]), str(ROOT / FOOT_TURNED["follower"]),
                          score=score_report.score_block, **names).analysis
    body = analyse(*samples(follower=FOOT_TURNED["take_id"]))[2]["analysis"]
    assert body["faults"] == direct["faults"] and body["score"] == direct["score"]
    assert body["diagnostics"]["feet"]["compared"] == direct["diagnostics"]["feet"]["compared"]


def test_the_feet_sources_in_the_answer_are_repo_relative_never_this_servers_path():
    feet = feet_of(analyse(*samples(follower=FOOT_TURNED["take_id"]))[2])
    assert {s: feet[s]["source"] for s in ("expected", "follower")} == {
        "expected": FOOT_TURNED["expected_feet"], "follower": FOOT_TURNED["follower_feet"]}
    assert str(ROOT) not in json.dumps(feet) and "/home/" not in json.dumps(feet)


def test_every_generated_sample_carries_its_label_feet_and_every_other_sample_none():
    t = api.table()
    generated = {tk["take_id"]: tk for tk in LABELS["takes"]}
    assert all(t.follower[i].feet == {"follower_feet": tk["follower_feet"]} for i, tk in generated.items())
    assert {s: t.expected[s].feet for s in ("exercise", "dance")} == {
        s: {"expected_feet": next(tk["expected_feet"] for tk in generated.values() if tk["set"] == s)}
        for s in ("exercise", "dance")}
    others = [s for i, s in t.follower.items() if i not in generated] + [t.expected["part3-squat"]]
    assert others and all(s.feet == {} for s in others)


def test_a_take_with_no_foot_files_is_analysed_as_before():
    """The Part 3 kit and an upload name none, so there is no feet block and the answer is the plain pipeline's."""
    kit = analyse({"sample": "part3-squat"}, {"sample": "squat_side_knee_caving-left"})[2]
    assert feet_of(kit) is None
    direct = pipeline.analyse(str(ROOT / api.KIT_EXPECTED), str(api.table().follower["squat_side_knee_caving-left"].path))
    assert kit["analysis"]["faults"] == direct["faults"]
    for pair in (({"sample": "exercise"}, {"upload": json.loads((ROOT / FOOT_TURNED["follower"]).read_text())}),
                 ({"upload": json.loads(EXPECTED_PATH.read_text())}, {"sample": FOOT_TURNED["take_id"]})):
        status, _, body = analyse(*pair)
        assert status == 200 and feet_of(body) is None and body["analysis"]["faults"] == []


def test_a_label_naming_a_foot_file_outside_the_fixtures_is_refused_when_the_table_is_built():
    with pytest.raises(FileNotFoundError, match="not a fixture file"):
        api._feet_file(ROOT, {"follower_feet": "part5/rules.json"}, "follower_feet")
    assert api._feet_file(ROOT, {"take_id": "t"}, "follower_feet") == {}


# --- the picker and the listing word a foot take as the analysis does (AC-S10, delivery review N1) -------------------
FOOT_MEASURES = ("foot_rotation", "ankle_inversion")
FOOT_LABELLED = [t for t in LABELS["takes"] if any(canonical_label(f)[0] in FOOT_MEASURES for f in t["faults"])]
TAKE_11 = next(t for t in LABELS["takes"] if t["take_id"] == "exercise_front_good_11_ankle_rolled_in-left")
# The way each ankle roll is worded, whatever the size word: `more` is the ankle rolling out, `less` rolling in.
ROLL_WORDS = {"more": "rolling out", "less": "rolling in"}


def listed_followers():
    return {t["id"]: t for t in call("GET", "/api/samples")[2]["followers"]}


def sentence(text):
    return text[:1].upper() + text[1:]


def test_every_foot_take_is_worded_in_the_picker_and_the_listing_as_the_analysis_words_it():
    followers = listed_followers()
    assert len(FOOT_LABELLED) == 48 and {canonical_label(f)[0] for t in FOOT_LABELLED for f in t["faults"]} == set(FOOT_MEASURES)
    for take in FOOT_LABELLED:
        listed = followers[take["take_id"]]
        assert len(listed["faults"]) == len(take["faults"]) == 1
        measure, side, direction = canonical_label(take["faults"][0])
        want = words.phrase(measure, direction, side)   # the analysis's words for this measure, direction and side
        assert listed["faults"][0] == {"type": take["faults"][0]["type"], "side": side, "text": want}, take["take_id"]
        assert listed["label"].endswith(f": {sentence(want)}"), (take["take_id"], listed["label"])
        if measure == "ankle_inversion":   # said again without the shared helper: the roll's own direction words
            assert ROLL_WORDS[direction] in want and ROLL_WORDS[{"more": "less", "less": "more"}[direction]] not in want


def test_the_ankle_label_ids_and_the_label_file_keep_their_old_words_and_only_the_page_changes():
    followers = listed_followers()
    rolled = [t for t in FOOT_LABELLED if t["faults"][0]["type"] in ("ankle_rolled_in", "ankle_rolled_out")]
    assert len(rolled) == 24
    assert {t["faults"][0]["text"].split()[-1] for t in rolled} == {"in", "out"}   # the label file still says "rolled in/out"
    for take in rolled:
        assert followers[take["take_id"]]["id"] == take["take_id"]
        assert followers[take["take_id"]]["faults"][0]["type"] == take["faults"][0]["type"]
        assert "rolled" not in followers[take["take_id"]]["label"]


def test_a_take_with_no_foot_fault_keeps_the_words_of_its_label():
    followers = listed_followers()
    others = [t for t in LABELS["takes"] if t not in FOOT_LABELLED]
    assert len(others) + len(FOOT_LABELLED) == len(LABELS["takes"]) and others
    for take in others:
        listed = followers[take["take_id"]]
        assert [f["text"] for f in listed["faults"]] == [f["text"] for f in take["faults"]], take["take_id"]
        what = "; ".join(f["text"] for f in take["faults"]) or "correct take"
        assert listed["label"].endswith(f": {sentence(what)}"), take["take_id"]


def test_every_generated_take_label_starts_with_the_takes_own_number_the_45_degree_ones_included():
    """Take ids are `<set>_<angle>_<light>_<NN>_<faults>`: the first digit group of a 45 degree id is the angle, not the take."""
    followers = listed_followers()
    for take in LABELS["takes"]:
        number = take["take_id"].split("_")[3]
        assert number.isdigit() and len(number) == 2, take["take_id"]
        assert followers[take["take_id"]]["label"].startswith(f"Take {number}: "), (take["take_id"], followers[take["take_id"]]["label"])
    assert {t["angle"] for t in LABELS["takes"]} == {"front", "45", "side"}
    assert followers["exercise_45_good_11_ankle_rolled_in-left"]["label"] == "Take 11: Left ankle rolling out"
    assert followers["dance_45_low_02_arms_wider-left"]["label"].startswith("Take 02: ")


def test_front_and_side_labels_keep_the_number_they_had():
    """Before this the number was the first digit group of the id, which is the take's own for a front or side take."""
    followers = listed_followers()
    plain = [t for t in LABELS["takes"] if t["angle"] != "45"]
    assert len(plain) == 104
    for take in plain:
        first_group = re.search(r"_(\d+)_", take["take_id"]).group(1)
        assert followers[take["take_id"]]["label"].startswith(f"Take {first_group}: "), take["take_id"]
    assert followers["exercise_front_good_09_foot_turned_out-right"]["label"] == "Take 09: Right foot turned out more than the example"


def test_take_11_picker_label_and_its_analysed_fault_line_point_the_same_way():
    """The finding: the picker said "Left ankle rolled in" over a result that said "left ankle rolling out slightly"."""
    listed = listed_followers()[TAKE_11["take_id"]]
    assert listed["label"] == "Take 11: Left ankle rolling out"
    status, _, body = analyse(*samples(follower=TAKE_11["take_id"]))
    assert status == 200
    ankle = [f for f in body["analysis"]["faults"] if f["measure"] == "ankle_inversion"]
    assert len(ankle) == 1 and (ankle[0]["side"], ankle[0]["direction"]) == ("left", "more")
    picked = listed["faults"][0]["text"]
    sized = {words.phrase("ankle_inversion", "more", "left", size) for size in words.QUALIFIERS}
    assert picked == "left ankle rolling out" and ankle[0]["text"] in sized   # the same words, the size word aside
    assert ROLL_WORDS["more"] in picked and ROLL_WORDS["more"] in ankle[0]["text"] and ROLL_WORDS["more"] in ankle[0]["text_timed"]
    assert "rolling in" not in listed["label"] + ankle[0]["text"] + ankle[0]["text_timed"]


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


def test_a_follower_that_would_be_resampled_past_6000_frames_is_a_400_naming_it():
    # Three frames spanning 1000 s read as 30001 frames on the example's 30 fps clock.
    doc = foot_doc()
    doc["frames"] = doc["frames"][:3]
    for frame, t in zip(doc["frames"], (0.0, 500.0, 1000.0)):
        frame["t"] = t
    started = time.monotonic()
    status, field, message = error_of(analyse({"sample": "exercise"}, {"upload": doc}))
    assert (status, field) == (400, "follower.upload")
    assert message.startswith("follower.upload: ") and "30001" in message and "6000" in message
    assert time.monotonic() - started < 5


def test_an_expected_upload_with_a_huge_frame_rate_is_a_400_naming_it():
    doc = json.loads(EXPECTED_PATH.read_text())
    doc["fps"] = 1e6
    status, field, message = error_of(analyse({"upload": doc}, {"sample": FOOT_OUT}))
    assert (status, field) == (400, "expected.upload")
    assert message.startswith("expected.upload: ") and "240" in message


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


# ----------------------------------------------------------------------------- real takes (AC-V09)

REPORT = {"format": "simon.part5.real_report.v1", "gated": False, "takes": [], "summary": {}, "notes": []}


@pytest.fixture
def real_report(monkeypatch):
    """A fake `part5.real.build_report`, so these tests do not need part5/real.py to exist."""
    calls = []
    monkeypatch.setattr(api, "_REAL_REPORT", {})
    monkeypatch.setattr(api, "_build_real_report", lambda: calls.append(1) or REPORT)
    return calls


def test_AC_V09_real_takes_serves_the_report_and_builds_it_once_per_process(real_report):
    first = call("GET", "/api/real-takes")
    second = call("GET", "/api/real-takes")
    assert first[0] == second[0] == 200 and first[2] == second[2] == REPORT
    assert len(real_report) == 1


def test_AC_V09_real_takes_answers_503_in_plain_words_when_the_report_cannot_be_built(monkeypatch):
    monkeypatch.setattr(api, "_REAL_REPORT", {})

    def broken():
        raise ModuleNotFoundError("No module named 'part5.real'")

    monkeypatch.setattr(api, "_build_real_report", broken)
    response = call("GET", "/api/real-takes")
    assert error_of(response) == (503, "real-takes", "The real-take report is not available on this server.")
    assert "part5.real" not in json.dumps(response[2]) and "Traceback" not in json.dumps(response[2])


def test_a_failed_real_report_is_not_cached_so_it_works_once_the_module_lands(monkeypatch):
    monkeypatch.setattr(api, "_REAL_REPORT", {})
    monkeypatch.setattr(api, "_build_real_report", lambda: 1 / 0)
    assert call("GET", "/api/real-takes")[0] == 503
    monkeypatch.setattr(api, "_build_real_report", lambda: REPORT)
    assert call("GET", "/api/real-takes")[0] == 200


def test_real_takes_answers_get_only():
    status, headers, _ = call("POST", "/api/real-takes", {})
    assert status == 405 and headers["Allow"] == "GET"


def test_a_report_json_cannot_hold_is_a_503_not_a_500(monkeypatch):
    monkeypatch.setattr(api, "_REAL_REPORT", {})
    monkeypatch.setattr(api, "_build_real_report", lambda: {"x": float("nan")})
    assert call("GET", "/api/real-takes")[0] == 503


# ----------------------------------------------------------------------------- muse-spark rate limit

class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def muse(monkeypatch, tmp_path):
    """muse-spark offered (key file and META_LIVE=1 present) with a fake clock and no live call."""
    (tmp_path / "BASETEN_API_KEY").write_text("sentinel-key-value\n")
    monkeypatch.setenv("PART5_BASETEN_KEY_FILE", str(tmp_path / "BASETEN_API_KEY"))
    monkeypatch.setenv("META_LIVE", "1")
    clock = Clock()
    monkeypatch.setattr(api, "_MUSE_LIMIT", api.ClientLimit(clock=clock))
    monkeypatch.setattr(api, "_in_worker", lambda fn, *a: {"analysis": {"phrasing": {"backend": "muse-spark"}}, "replay": {}})
    return clock


def ask(client, phrasing="muse-spark"):
    body = json.dumps({"expected": {"sample": "exercise"}, "follower": {"sample": FOOT_OUT}, "phrasing": phrasing}).encode()
    status, headers, out = api.handle("POST", "/api/analyse", body, base_path="/", client=client)
    return status, headers, json.loads(out)


def test_muse_spark_allows_six_requests_a_minute_per_client_then_429_with_the_exact_text(muse):
    for _ in range(6):
        assert ask("10.0.0.1")[0] == 200
        muse.now += 1
    status, headers, body = ask("10.0.0.1")
    assert status == 429
    assert body == {"error": {"field": "phrasing", "message":
                              "Too many Muse Spark requests. Wait a minute or pick template."}}
    assert 1 <= int(headers["Retry-After"]) <= 60


def test_muse_spark_limit_is_per_client_and_lifts_after_a_minute(muse):
    for _ in range(6):
        assert ask("10.0.0.1")[0] == 200
    assert ask("10.0.0.1")[0] == 429 and ask("10.0.0.2")[0] == 200
    muse.now += 61
    assert ask("10.0.0.1")[0] == 200


def test_muse_spark_runs_one_request_at_a_time_per_client(muse, monkeypatch):
    seen = []

    def during(fn, *a):
        if not seen:
            seen.append(None)                # only the outer request looks around
            seen[0] = [ask("10.0.0.1")[0],   # a second request from the same client while one runs
                       ask("10.0.0.2")[0]]   # another client is not held up
        return {"analysis": {}, "replay": {}}

    monkeypatch.setattr(api, "_in_worker", during)
    assert ask("10.0.0.1")[0] == 200
    assert seen == [[429, 200]]
    assert ask("10.0.0.1")[0] == 200          # the slot is free again afterwards


def test_template_requests_are_never_limited(muse):
    for _ in range(6):
        ask("10.0.0.1")
    assert ask("10.0.0.1")[0] == 429
    assert [ask("10.0.0.1", "template")[0] for _ in range(8)] == [200] * 8


def test_a_failed_muse_spark_request_frees_the_slot_but_still_counts(muse, monkeypatch):
    def boom(fn, *a):
        raise api.AnalysisError("follower.upload: nope")

    monkeypatch.setattr(api, "_in_worker", boom)
    assert ask("10.0.0.1")[0] == 400
    assert api._MUSE_LIMIT._running == set() and len(api._MUSE_LIMIT._starts["10.0.0.1"]) == 1


def test_the_key_never_appears_in_any_response(muse):
    text = json.dumps([ask("10.0.0.1"), call("GET", "/api/samples")[2]])
    assert "sentinel-key-value" not in text
    assert b"sentinel-key-value" not in api.handle("GET", "/api/samples", b"", base_path="/")[2]


def test_idle_clients_are_forgotten_so_the_table_does_not_grow(muse):
    for n in range(20):
        ask(f"10.0.1.{n}")
    muse.now += 120
    ask("10.0.2.1")
    assert set(api._MUSE_LIMIT._starts) == {"10.0.2.1"}


@pytest.mark.parametrize("peer,forwarded,expected", [
    ("127.0.0.1", "203.0.113.9", "203.0.113.9"),
    ("127.0.0.1", "198.51.100.1, 203.0.113.9", "203.0.113.9"),   # the last hop is the one the gateway wrote
    ("127.0.0.1", "not an address", "127.0.0.1"),
    ("127.0.0.1", None, "127.0.0.1"),
    ("192.0.2.7", "203.0.113.9", "192.0.2.7"),                  # a direct caller cannot name itself
    ("::1", "2001:db8::1", "2001:db8::1"),
    (None, None, "local"),
])
def test_client_key_trusts_forwarded_for_only_from_this_machine(peer, forwarded, expected):
    assert api.client_key(peer, forwarded) == expected


# ----------------------------------------------------------------------------- base path

@pytest.mark.parametrize("given,expected", [("", "/"), ("/", "/"), ("/simon-part-5", "/simon-part-5/"),
                                            ("/simon-part-5/", "/simon-part-5/"), ("a/b", "/a/b/")])
def test_normalise_base_path(given, expected):
    assert api.normalise_base_path(given) == expected


@pytest.mark.parametrize("bad", ["/a b/", "/../x/", "/a//b/", "/x?y=1", "/x#"])
def test_normalise_base_path_refuses_odd_paths(bad):
    with pytest.raises(ValueError, match="base path"):
        api.normalise_base_path(bad)
