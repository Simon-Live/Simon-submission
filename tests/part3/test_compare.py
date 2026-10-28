"""Compare mode: the logic of 2 to 6 runs and the agreement by the done-check's own functions (docs/specs/compare-mode.md
AC-M04, AC-M07), then the run options and `api/compare` over HTTP (AC-M01, AC-M02, AC-M04)."""

import copy
import itertools
import json
import threading
import time

import numpy as np
import pytest

from part3 import cli, compare, metrics, runapi, server
from part3.align import frame_map, phase_signal, sample
from test_server import BASE, answer, post_head, serving

TAKES = (1, 2, 3, 4)
BAD_ANGLE = "frame 1 holds an angle that is not a number from -1000 to 1000 or null."


@pytest.fixture(scope="module")
def angles():
    """The angle series a run returns, for the four takes, the mirrored take and the arm raise."""
    out = {}
    for sample_id in ("take-1", "take-2", "take-3", "take-4", "take-1-mirrored", "armraise-control", "part2-squat"):
        status, body = runapi.handle(sample_id, "auto", None, b"")
        assert status == 200
        out[sample_id] = body["angles"]
    return out


@pytest.fixture(scope="module")
def check_3(tmp_path_factory):
    """(metrics, detail) of `make check-3`, written below a temp folder and not out/."""
    return metrics.compute(out_dir=str(tmp_path_factory.mktemp("check-3")))


def request(*series, labels=None):
    labels = labels or [f"input {k + 1}" for k in range(len(series))]
    return json.dumps({"inputs": [{"label": label, "angles": rows} for label, rows in zip(labels, series)]}).encode()


def failure(raw, code, message=None):
    status, body = compare.handle(raw)
    assert (status, body["ok"]) == (400, False) and list(body["error"]) == ["code", "field", "message"]
    assert body["error"]["code"] == code
    if message is not None:
        assert body["error"]["message"] == message
    return body["error"]["message"]


# ---- AC-M04: the answer ------------------------------------------------------------------------

def test_the_answer_has_the_documented_shape(angles):
    status, body = compare.handle(request(angles["take-1"], angles["take-2"]))
    assert status == 200 and list(body) == ["ok", "agreement", "alignment"] and body["ok"] is True
    assert list(body["agreement"]) == ["p95_deg", "pass", "per_pair"]
    assert body["agreement"]["per_pair"][0].keys() == {"a", "b", "p95_deg", "pass"}
    assert body["alignment"]["reference"] == 0 and len(body["alignment"]["maps"]) == 2
    json.dumps(body, allow_nan=False)


@pytest.mark.parametrize("count", [2, 3, 4, 5, 6])
def test_two_to_six_inputs_give_one_map_per_input_and_every_pair(angles, count):
    series = [angles[f"take-{1 + k % 4}"] for k in range(count)]
    status, body = compare.handle(request(*series))
    assert status == 200
    pairs = body["agreement"]["per_pair"]
    assert [(p["a"], p["b"]) for p in pairs] == list(itertools.combinations(range(count), 2))
    maps = body["alignment"]["maps"]
    assert len(maps) == count and all(len(m) == len(series[0]) for m in maps)  # on the reference timeline
    assert maps[0] == [float(i) for i in range(len(series[0]))]
    assert all(0 <= v <= len(series[k]) - 1 for k, m in enumerate(maps) for v in m)


def test_the_four_takes_give_the_figure_make_check_3_prints(angles, check_3):
    status, body = compare.handle(request(*(angles[f"take-{k}"] for k in TAKES)))
    done_check = check_3[0]["thresholds"]["joint_angle_agreement_p95_deg"]["value"]
    assert status == 200
    assert body["agreement"]["p95_deg"] == pytest.approx(done_check, abs=0.0005)
    assert round(done_check, 3) == body["agreement"]["p95_deg"] == 7.42
    assert body["agreement"]["pass"] is True


def test_the_maps_are_the_done_checks_alignment_maps(angles, check_3):
    _, body = compare.handle(request(*(angles[f"take-{k}"] for k in TAKES)))
    for ours, theirs in zip(body["alignment"]["maps"], (take["map"] for take in check_3[1]["takes"])):
        assert np.allclose(ours, theirs, atol=0.0006)


def test_a_pair_with_the_reference_is_the_done_check_function_on_the_two_series(angles):
    status, body = compare.handle(request(*(angles[f"take-{k}"] for k in TAKES)))
    for pair in body["agreement"]["per_pair"]:
        if pair["a"] != 0:
            continue
        series = [np.array(angles[f"take-{1 + pair['a']}"], dtype=float), np.array(angles[f"take-{1 + pair['b']}"], dtype=float)]
        direct = metrics.spread_stats(metrics.dtw_samples(series)[0])["p95"]
        assert pair["p95_deg"] == round(direct, 3)


def test_a_pair_is_read_off_the_shared_timeline_and_no_pair_beats_the_overall_figure(angles):
    _, body = compare.handle(request(*(angles[f"take-{k}"] for k in TAKES)))
    overall = body["agreement"]["p95_deg"]
    assert all(pair["p95_deg"] <= overall for pair in body["agreement"]["per_pair"])
    series = [np.array(angles[f"take-{k}"], dtype=float) for k in TAKES]
    signals = [phase_signal(a) for a in series]
    aligned = [sample(a, np.arange(len(signals[0])) if k == 0 else frame_map(signals[0], signals[k]))
               for k, a in enumerate(series)]
    two_three = metrics.spread_stats([aligned[1], aligned[2]])["p95"]
    assert [p["p95_deg"] for p in body["agreement"]["per_pair"] if (p["a"], p["b"]) == (1, 2)] == [round(two_three, 3)]


def test_the_same_input_twice_agrees_exactly(angles):
    status, body = compare.handle(request(angles["take-2"], angles["take-2"]))
    assert status == 200
    assert body["agreement"]["p95_deg"] == 0 and body["agreement"]["pass"] is True
    assert body["agreement"]["per_pair"] == [{"a": 0, "b": 1, "p95_deg": 0, "pass": True}]
    first, second = body["alignment"]["maps"]
    assert max(abs(a - b) for a, b in zip(first, second)) < 0.5  # the 3-frame smoothing moves only the two end frames
    assert first[2:-2] == second[2:-2]


def test_the_same_sample_three_times_is_zero_everywhere(angles):
    _, body = compare.handle(request(*([angles["take-3"]] * 3)))
    assert body["agreement"]["p95_deg"] == 0 and {p["p95_deg"] for p in body["agreement"]["per_pair"]} == {0}


def test_inputs_that_do_not_agree_fail_at_ten_degrees(angles):
    status, body = compare.handle(request(angles["take-1"], angles["armraise-control"]))
    assert status == 200 and body["agreement"]["p95_deg"] > metrics.AGREEMENT_MAX_DEG
    assert body["agreement"]["pass"] is False and body["agreement"]["per_pair"][0]["pass"] is False


def test_the_mirrored_take_run_with_mirror_on_agrees_with_take_1(angles):
    runs = runapi.handle("take-1-mirrored", "on", None, b"")[1]["angles"]
    _, body = compare.handle(request(angles["take-1"], runs))
    assert body["agreement"]["p95_deg"] < 0.01 and body["agreement"]["pass"] is True


def test_the_order_of_inputs_only_changes_the_reference(angles):
    _, forward = compare.handle(request(angles["take-1"], angles["take-3"]))
    _, backward = compare.handle(request(angles["take-3"], angles["take-1"]))
    assert forward["alignment"]["reference"] == backward["alignment"]["reference"] == 0
    assert len(forward["alignment"]["maps"][0]) == len(angles["take-1"])
    assert len(backward["alignment"]["maps"][0]) == len(angles["take-3"])


# ---- edge cases --------------------------------------------------------------------------------

def test_inputs_with_very_few_frames_still_get_an_answer():
    rows = [[90.0 + k] * 9 for k in range(3)]
    status, body = compare.handle(request(rows, rows[:2], rows[:1]))
    assert status == 200 and len(body["alignment"]["maps"]) == 3
    assert [len(m) for m in body["alignment"]["maps"]] == [3, 3, 3]


def test_a_single_frame_each_is_enough():
    status, body = compare.handle(request([[90.0] * 9], [[95.0] * 9]))
    assert status == 200 and body["agreement"]["p95_deg"] == 5 and body["agreement"]["pass"] is True


def test_null_rows_are_frames_without_a_person(angles):
    holes = [list(row) for row in angles["take-2"]]
    for i in (3, 4, 5):
        holes[i] = [None] * 9
    status, body = compare.handle(request(angles["take-1"], holes))
    assert status == 200 and isinstance(body["agreement"]["p95_deg"], float)


def test_an_input_with_no_person_at_all_has_no_figure_and_does_not_pass(angles):
    status, body = compare.handle(request(angles["take-1"], [[None] * 9] * 20))
    assert status == 200
    assert body["agreement"]["p95_deg"] is None and body["agreement"]["pass"] is False
    assert body["agreement"]["per_pair"][0]["p95_deg"] is None
    json.dumps(body, allow_nan=False)


def test_integers_and_floats_are_both_angles():
    status, _ = compare.handle(request([[90] * 9, [91.5] * 9], [[90.0] * 9, [91] * 9]))
    assert status == 200


# ---- AC-M04: refusals --------------------------------------------------------------------------

@pytest.mark.parametrize("count", [0, 1, 7, 12])
def test_fewer_than_two_or_more_than_six_inputs_is_compare_count(count):
    rows = [[90.0] * 9] * 4
    failure(request(*([rows] * count)), "compare_count", "Compare needs 2 to 6 inputs.")


@pytest.mark.parametrize("raw", [
    b"", b"not json", b"\xff\xfe", b"[]", b"null", b"3", b'{"inputs": "x"}', b"{}", b'{"inputs": null}',
    b"[" * 100000, b'{"inputs": {"a": 1}}'])
def test_a_body_that_is_not_a_compare_request_is_compare_shape(raw):
    failure(raw, "compare_shape", 'The compare request must be a JSON object with an "inputs" list.')


@pytest.mark.parametrize("entry, message", [
    ("text", "Input 2: must be an object with a label and angles."),
    ({"angles": [[1] * 9]}, "Input 2: label must be text."),
    ({"label": 5, "angles": [[1] * 9]}, "Input 2: label must be text."),
    ({"label": "x"}, "Input 2: angles must be a list of frames."),
    ({"label": "x", "angles": "no"}, "Input 2: angles must be a list of frames."),
    ({"label": "x", "angles": {"0": [1] * 9}}, "Input 2: angles must be a list of frames."),
    ({"label": "x", "angles": []}, "Input 2: angles has no frames."),
    ({"label": "x", "angles": [[1] * 9, "row"]}, "Input 2: frame 2 must be a list of 9 angles."),
    ({"label": "x", "angles": [[1] * 8]}, "Input 2: frame 1 must be a list of 9 angles."),
    ({"label": "x", "angles": [[1] * 10]}, "Input 2: frame 1 must be a list of 9 angles."),
    ({"label": "x", "angles": [None]}, "Input 2: frame 1 must be a list of 9 angles."),
    ({"label": "x", "angles": [[1] * 8 + ["90"]]}, f"Input 2: {BAD_ANGLE}"),
    ({"label": "x", "angles": [[1] * 8 + [True]]}, f"Input 2: {BAD_ANGLE}"),
    ({"label": "x", "angles": [[1] * 8 + [[1]]]}, f"Input 2: {BAD_ANGLE}"),
    ({"label": "x", "angles": [[1] * 8 + [1000.5]]}, f"Input 2: {BAD_ANGLE}"),
    ({"label": "x", "angles": [[-1001] + [1] * 8]}, f"Input 2: {BAD_ANGLE}"),
])
def test_a_bad_shape_names_the_input_and_the_problem(entry, message):
    body = json.dumps({"inputs": [{"label": "ok", "angles": [[1] * 9]}, entry]}).encode()
    failure(body, "compare_shape", message)


@pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity", "1e999"])
def test_a_non_finite_angle_is_refused(token):
    row = ",".join(["1"] * 8 + [token])
    raw = ('{"inputs": [{"label": "a", "angles": [[%s]]}, {"label": "b", "angles": [[1,1,1,1,1,1,1,1,1]]}]}' % row).encode()
    failure(raw, "compare_shape", f"Input 1: {BAD_ANGLE}")


def test_the_first_bad_input_is_the_one_named():
    good = {"label": "a", "angles": [[1] * 9]}
    raw = json.dumps({"inputs": [good, good, {"label": "c", "angles": 4}, {"label": "d", "angles": 5}]}).encode()
    failure(raw, "compare_shape", "Input 3: angles must be a list of frames.")


def test_a_series_over_the_frame_cap_is_compare_size():
    rows = [[90.0] * 9] * (compare.MAX_FRAMES + 1)
    message = failure(request(rows, [[90.0] * 9]), "compare_size")
    assert message == f"Input 1: more than {compare.MAX_FRAMES} frames. Compare handles up to {compare.MAX_FRAMES}."


def test_a_series_at_the_frame_cap_is_accepted():
    rows = [[90.0 + (i % 7)] * 9 for i in range(compare.MAX_FRAMES)]
    status, body = compare.handle(request(rows, rows[:50]))
    assert status == 200 and len(body["alignment"]["maps"][0]) == compare.MAX_FRAMES


def test_the_caps_are_the_documented_ones():
    assert (compare.MIN_INPUTS, compare.MAX_INPUTS, compare.MAX_LABEL) == (2, 6, 80)
    assert compare.MAX_FRAMES <= 20000  # the spec's ceiling; lower because the DTW matrix grows with frames squared


def test_a_label_over_80_characters_is_compare_size_and_80_is_fine():
    rows = [[90.0] * 9]
    failure(request(rows, rows, labels=["x" * 81, "b"]), "compare_size", "Input 1: the label is over 80 characters.")
    assert compare.handle(request(rows, rows, labels=["x" * 80, "é" * 80]))[0] == 200


def test_the_number_check_is_the_one_in_part3_schema():
    """Review B5: no private copy of the helper."""
    from part3 import schema
    assert compare.is_number is schema.is_number and not hasattr(compare, "_is_number")
    failure(request([[True] * 9], [[1] * 9]), "compare_shape")  # a boolean is not an angle
    assert compare.handle(request([[1] * 9], [[1.5] * 9]))[0] == 200


def test_the_413_text_names_the_compare_request_not_a_pose3d_file():
    assert compare.TOO_LARGE == "This compare request is over 16 MB."
    assert "pose3d" not in compare.TOO_LARGE and "file" not in compare.TOO_LARGE


def test_every_message_is_plain_ascii_with_no_dash_variants():
    for message in (*(runapi.ERRORS[code][1] for code in ("compare_count", "compare_shape", "compare_size")),
                    compare.TOO_LARGE):
        assert message.isascii() and "\u2014" not in message and "\u2013" not in message
    for raw in (b"", request([[1] * 9]), request([[1] * 9], [[1] * 8])):
        message = compare.handle(raw)[1]["error"]["message"]
        assert message.isascii() and "Traceback" not in message and "Error" not in message


def test_compare_never_raises_on_hostile_json():
    hostile = [b'{"inputs": [{"label": "a", "angles": [[1,2,3,4,5,6,7,8,9]]}, 7]}',
               b'{"inputs": [[], []]}', b'{"inputs": [null, null]}', b'{"inputs": [{}, {}]}',
               b'{"inputs": [{"label": "a", "angles": [[1e308, -1e308, 0, 0, 0, 0, 0, 0, 0]]}, '
               b'{"label": "b", "angles": [[0, 0, 0, 0, 0, 0, 0, 0, 0]]}]}']
    for raw in hostile:
        status, body = compare.handle(raw)
        assert status in (200, 400) and "ok" in body
        json.dumps(body, allow_nan=False)


@pytest.fixture(scope="module")
def real():
    with serving() as client:
        yield client


@pytest.fixture
def clip(real_doc):
    doc = copy.deepcopy(real_doc)
    doc["frames"] = doc["frames"][:40]
    return doc


# ---- AC-M03, AC-NFR-M1: a 16 MiB upload

def pose3d_of_bytes(real_doc, size):
    """A pose3d.json of exactly `size` bytes: the Part 2 squat repeated with rising frame and t_ms, then blank padding."""
    base = real_doc["frames"]
    step = base[1]["t_ms"] - base[0]["t_ms"]

    def dump(obj):
        return json.dumps(obj, separators=(",", ":"))

    count = int(0.995 * size * len(base) / sum(len(dump(frame)) for frame in base))
    frames = [{**base[i % len(base)], "frame": i, "t_ms": round(i * step, 3)} for i in range(count)]
    excess = len(dump({**real_doc, "frames": frames})) - size
    while excess > 0:
        excess -= len(dump(frames.pop())) + 1
    text = dump({**real_doc, "frames": frames})
    return (text + " " * (size - len(text))).encode(), len(frames)


@pytest.fixture(scope="module")
def sixteen_mib(real_doc):
    return pose3d_of_bytes(real_doc, server.MAX_BODY)


def test_a_16_mib_pose3d_runs_inside_the_run_timeout(real, sixteen_mib):
    """AC-NFR-M1: a real upload of exactly 16 MiB (about 15,700 frames) runs, and well inside RUN_TIMEOUT_S."""
    raw, frames = sixteen_mib
    assert len(raw) == server.MAX_BODY
    started = time.perf_counter()
    reply = real.run("flip=auto&name=sixteen.json", raw)
    seconds = time.perf_counter() - started
    body = reply.json()
    assert reply.status == 200 and body["ok"] is True
    assert body["metrics"]["frames"] == len(body["angles"]) == frames and body["source"]["bytes"] == server.MAX_BODY
    assert seconds < server.RUN_TIMEOUT_S / 2, seconds
    assert body["metrics"]["bone_length_variation_output"] < 0.02


@pytest.mark.parametrize("query", ["fps=30", "fps=60", "view=part4", "body=measured&view=part4&fps=60"])
def test_a_16_mib_pose3d_with_a_frame_rate_is_refused_by_the_frame_cap_not_run_to_a_timeout(real, sixteen_mib, query):
    """Review residual 7: this clip spans about 1,046 s, so 30 per second is over 31,000 frames. The reviewer measured
    22.5 s, 1.2 GiB and a timeout for the part4 and 60 per second case; the cap answers it before it runs."""
    raw, _ = sixteen_mib
    started = time.perf_counter()
    reply = real.run(f"flip=auto&name=sixteen.json&{query}", raw)
    assert (reply.status, reply.error_code()) == (400, "too_long")
    assert time.perf_counter() - started < server.RUN_TIMEOUT_S / 4



# ---- AC-M01, AC-M02: the run options over HTTP -------------------------------------------------

def test_the_run_options_default_and_are_echoed(real):
    body = real.run("sample=take-1").json()
    assert body["options"] == {"body": "simon-standard", "stature": None, "view": "native", "fps": None}
    assert body["output_name"] == "skeleton.json" and body["output_text"] == body["skeleton_text"]
    page_query = real.run("sample=take-1&flip=auto&body=simon-standard&stature=&view=native&fps=").json()
    assert page_query["options"] == body["options"] and page_query["skeleton_text"] == body["skeleton_text"]


@pytest.mark.parametrize("query, code, field", [
    ("sample=take-1&body=file:/etc/passwd", "bad_body", "body"),
    ("sample=take-1&body=file:part3/standard_body.json", "bad_body", "body"),
    ("sample=take-1&body=other", "bad_body", "body"),
    ("sample=take-1&view=part6", "bad_view", "view"),
    ("sample=take-1&fps=45", "bad_fps", "fps"),
    ("sample=take-1&stature=9", "bad_stature", "stature"),
    ("sample=take-1&stature=abc", "bad_stature", "stature"),
])
def test_a_bad_option_is_400_naming_the_field(real, query, code, field):
    reply = real.run(query)
    assert reply.status == 400 and reply.error_code() == code and reply.json()["error"]["field"] == field
    assert b"Traceback" not in reply.body and b"/etc/passwd" not in reply.body


def test_a_bad_option_is_answered_before_the_body_is_read_and_takes_no_run_slot(monkeypatch):
    monkeypatch.setattr(server, "MAX_RUNS", 1)
    with serving() as client:
        conn = post_head(client, ("Content-Length", "500"), query="?body=file:/etc/passwd")  # no body is ever sent
        status, code, _ = answer(conn)
        assert (status, code) == (400, "bad_body")
        conn.close()
        assert client.run("sample=take-1").status == 200  # the single run slot was never held


def test_a_bad_option_on_an_upload_is_refused_without_running_it(real, clip, monkeypatch):
    monkeypatch.setattr(cli, "process", lambda *args, **kwargs: pytest.fail("the pipeline ran"))
    reply = real.run("name=a.json&view=nope", json.dumps(clip).encode())
    assert (reply.status, reply.error_code()) == (400, "bad_view")


def test_the_body_and_view_switches_reach_the_real_pipeline(real):
    standard = real.run("sample=take-1").json()
    switched = real.run("sample=take-1&body=measured&view=part4&fps=30").json()
    assert switched["options"] == {"body": "measured", "stature": None, "view": "part4", "fps": 30}
    assert json.loads(switched["skeleton_text"])["body"]["profile"] == "measured"
    assert json.loads(switched["output_text"])["format"] == "simon.skeleton.v1"
    assert (json.loads(switched["skeleton_text"])["bone_lengths_m"]
            != json.loads(standard["skeleton_text"])["bone_lengths_m"])
    assert switched["output_name"] == "skeleton.json" and switched["output_text"] != switched["skeleton_text"]
    part5 = real.run("sample=take-1&view=part5").json()
    assert part5["output_name"] == "skeleton.part5.json"


# ---- AC-M04: POST api/compare ------------------------------------------------------------------

@pytest.fixture(scope="module")
def two_takes(real):
    return [real.run(f"sample=take-{k}").json()["angles"] for k in (1, 2)]


def compare_body(*series, label="input"):
    return json.dumps({"inputs": [{"label": f"{label} {k}", "angles": rows} for k, rows in enumerate(series, 1)]}).encode()


def test_compare_over_http_answers_what_the_pure_logic_answers(real, two_takes):
    raw = compare_body(*two_takes)
    reply = real.post("api/compare", raw, headers={"Content-Type": "application/json"})
    assert reply.status == 200 and reply.headers["content-type"] == "application/json"
    assert reply.json() == compare.handle(raw)[1]
    assert reply.json()["agreement"]["pass"] is True and reply.headers["cache-control"] == "no-store"


def test_compare_errors_over_http(real, two_takes):
    cases = [(compare_body(two_takes[0]), 400, "compare_count"), (b"nope", 400, "compare_shape"),
             (b"", 400, "compare_shape"), (compare_body(two_takes[0], [[1, 2]]), 400, "compare_shape"),
             (compare_body(two_takes[0], two_takes[1], label="x" * 90), 400, "compare_size")]
    for raw, status, code in cases:
        reply = real.post("api/compare", raw)
        assert (reply.status, reply.error_code()) == (status, code)
        assert reply.json()["error"]["message"] and b"Traceback" not in reply.body
    assert real.post("api/compare", compare_body(two_takes[0])).json()["error"]["message"] == "Compare needs 2 to 6 inputs."


def test_compare_keeps_every_post_guard(real, two_takes):
    raw = compare_body(*two_takes)
    refused = real.post("api/compare", raw, headers={"Sec-Fetch-Site": "cross-site"})
    assert (refused.status, refused.error_code()) == (403, "cross_site")
    assert real.post("api/compare", raw, headers={"Sec-Fetch-Site": "same-origin"}).status == 200
    conn = real.connect()
    conn.putrequest("POST", BASE + "api/compare")
    conn.endheaders()
    response = conn.getresponse()
    assert (response.status, json.loads(response.read())["error"]["code"]) == (411, "length_required")
    conn.close()
    for value in ("abc", "-5", "1e3"):
        conn = real.connect()
        conn.putrequest("POST", BASE + "api/compare")
        conn.putheader("Content-Length", value)
        conn.endheaders()
        assert answer(conn)[:2] == (400, "bad_request")
        conn.close()


def test_compare_takes_a_run_slot_before_its_body_is_read(monkeypatch):
    monkeypatch.setattr(server, "MAX_RUNS", 1)
    monkeypatch.setattr(server, "BODY_TIMEOUT_S", 1.5)
    with serving() as client:
        slow = post_head(client, ("Content-Length", "500"))  # holds the only slot while its body is awaited
        slow.send(b"{")
        time.sleep(0.2)
        busy = client.post("api/compare", b"{}")
        assert (busy.status, busy.error_code()) == (503, "busy")
        slow.close()


def test_a_compare_past_the_timeout_is_503_and_a_failure_is_500_without_a_traceback(monkeypatch, capsys):
    monkeypatch.setattr(server, "RUN_TIMEOUT_S", 0.3)
    gate = threading.Event()
    monkeypatch.setattr(compare, "handle", lambda raw: (gate.wait(5), (200, {"ok": True}))[1])
    with serving() as client:
        slow = client.post("api/compare", b"{}")
        assert (slow.status, slow.error_code()) == (503, "timeout")
        gate.set()

    def explode(raw):
        raise RuntimeError("secret detail at /home/someone/file.py")
    monkeypatch.setattr(compare, "handle", explode)
    with serving() as client:
        reply = client.post("api/compare", b"{}")
        assert (reply.status, reply.error_code()) == (500, "internal")
        for leaked in (b"Traceback", b"RuntimeError", b"secret", b"/home/"):
            assert leaked not in reply.body
    assert "Traceback" in capsys.readouterr().err


def test_the_compare_log_line_has_the_size_and_hash_but_not_the_labels(real, two_takes, capsys):
    capsys.readouterr()
    real.post("api/compare", compare_body(*two_takes, label="PRIVATE-LABEL"))
    line = [row for row in capsys.readouterr().err.splitlines() if row.strip()][-1]
    assert line.split()[1:4] == ["POST", BASE + "api/compare", "200"]
    assert "compare=" in line and "sha256=" in line and "PRIVATE-LABEL" not in line and "angles" not in line


def test_a_run_and_a_compare_run_one_after_another_like_the_page_does(real):
    runs = [real.run(f"sample=take-{k}&body=simon-standard&stature=&view=native&fps=").json() for k in (1, 2, 3, 4)]
    reply = real.post("api/compare", compare_body(*(run["angles"] for run in runs)))
    assert reply.status == 200 and reply.json()["agreement"]["p95_deg"] == 7.42


def test_a_request_never_reads_the_servers_environment_or_config_file(real, monkeypatch, tmp_path):
    """compare-mode.md AC-M02: no env, no config file and no server path from a request."""
    monkeypatch.setenv("PART3_BODY", "measured")
    (tmp_path / "part3.toml").write_text('[body]\nprofile = "part4-rig"\n')
    monkeypatch.chdir(tmp_path)
    body = json.loads(real.run("sample=take-1").json()["skeleton_text"])["body"]
    assert (body["profile"], body["selected_by"]) == ("simon-standard", "default")
    chosen = json.loads(real.run("sample=take-1&body=part4-rig").json()["skeleton_text"])["body"]
    assert (chosen["profile"], chosen["selected_by"]) == ("part4-rig", "flag")
