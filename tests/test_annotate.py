import json
import threading
import urllib.error
import urllib.request

import pytest

from part2 import annotate, frames
from part2.eval_reproj import evaluate
from part2.joints import CANONICAL


@pytest.fixture
def frames_dir(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    for i in range(30):
        (src / f"{i:03d}.jpg").write_bytes(b"\xff\xd8img%d" % i)
    out = tmp_path / "frames"
    frames.ingest(src, out, fps=10)
    return out


def test_pick_frames_spreads_over_clip(frames_dir):
    recs = frames.load(frames_dir)
    picked = annotate.pick_frames(recs, 5)
    assert picked[0] == 0 and picked[-1] == 29 and len(picked) == 5
    assert annotate.pick_frames(recs, 50) == list(range(30))


def test_keyframes_every_second(frames_dir):
    assert annotate.keyframes(frames.load(frames_dir), 1.0) == [0, 10, 20]


def test_joints_state_prefills_largest_person(frames_dir, tmp_path):
    body3d = {"frames": [{"frame": 0, "people": [
        {"id": 0, "bbox": [0, 0, 10, 10], "kp2d": {j: [1, 1] for j in CANONICAL}},
        {"id": 1, "bbox": [0, 0, 50, 90], "kp2d": {j: [7, 8] for j in CANONICAL}}]}]}
    (tmp_path / "b.json").write_text(json.dumps(body3d))
    st = annotate.build_state("joints", frames_dir, tmp_path / "labels.json", prefill=tmp_path / "b.json", count=4)
    assert [f["frame"] for f in st["frames"]] == [0, 10, 19, 29]
    assert st["hints"]["0"]["nose"] == [7, 8]


def test_validate_joints_drops_empty_frames_and_rejects_bad_input():
    doc = {"frames": [{"frame": 3, "view": "side", "joints": {"nose": [1.234, 5], "left_ankle": None}},
                      {"frame": 1, "view": "front", "joints": {}}]}
    out = annotate.validate("joints", doc)
    assert [f["frame"] for f in out["frames"]] == [3]
    assert out["frames"][0]["joints"]["nose"] == [1.2, 5.0] and out["frames"][0]["joints"]["right_hip"] is None
    with pytest.raises(ValueError, match="unknown joints"):
        annotate.validate("joints", {"frames": [{"frame": 0, "view": "front", "joints": {"nosee": [1, 1]}}]})
    with pytest.raises(ValueError, match="view"):
        annotate.validate("joints", {"frames": [{"frame": 0, "view": "top", "joints": {"nose": [1, 1]}}]})


def test_validate_ids_rejects_duplicates_and_empty_boxes():
    ok = annotate.validate("ids", {"frames": [{"frame": 0, "people": [{"id": "2", "bbox": [1, 2, 3, 4]}]}]})
    assert ok == {"keyframes_only": True, "frames": [{"frame": 0, "people": [{"id": 2, "bbox": [1.0, 2.0, 3.0, 4.0]}]}]}
    with pytest.raises(ValueError, match="twice"):
        annotate.validate("ids", {"frames": [{"frame": 0, "people": [{"id": 1, "bbox": [0, 0, 5, 5]}] * 2}]})
    with pytest.raises(ValueError, match="empty box"):
        annotate.validate("ids", {"frames": [{"frame": 0, "people": [{"id": 1, "bbox": [0, 0, 0, 5]}]}]})
    for bbox in ([0, 0, float("nan"), 5], [0, float("inf"), 5, 5], [0, 0, 5]):
        with pytest.raises(ValueError):
            annotate.validate("ids", {"frames": [{"frame": 0, "people": [{"id": 1, "bbox": bbox}]}]})
    with pytest.raises(ValueError, match="whole number"):
        annotate.validate("ids", {"frames": [{"frame": 0, "people": [{"id": 2.7, "bbox": [0, 0, 5, 5]}]}]})
    empty = annotate.validate("ids", {"frames": [{"frame": 3, "people": []}]})
    assert empty["frames"] == [{"frame": 3, "people": []}]  # visited-but-empty keyframes are kept


def test_validate_joints_rejects_nonfinite_and_wrong_length():
    for uv in ([float("nan"), 1], [1, float("inf")], [1], [1, 2, 3]):
        with pytest.raises(ValueError):
            annotate.validate("joints", {"frames": [{"frame": 0, "view": "front", "joints": {"nose": uv}}]})
    with pytest.raises(ValueError, match="not one of"):
        annotate.validate("joints", {"frames": [{"frame": 5, "view": "front", "joints": {"nose": [1, 1]}}]}, {0, 1})


def _serve(state, frames_dir, out):
    server = annotate.make_server(state, frames_dir, out, port=0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def _post(url, doc, token):
    req = urllib.request.Request(url, data=json.dumps(doc).encode(),
                                 headers={"Content-Type": "application/json", "X-Token": token})
    return json.loads(urllib.request.urlopen(req).read())


def _get(url, token=None):
    return urllib.request.urlopen(urllib.request.Request(url, headers={"X-Token": token} if token else {})).read()


def test_server_roundtrip_writes_labels_that_eval_reads(frames_dir, tmp_path):
    out = tmp_path / "labels_2d.json"
    state = annotate.build_state("joints", frames_dir, out, count=3)
    server, url = _serve(state, frames_dir, out)
    tok = server.token
    try:
        assert b"<canvas" in _get(url + "/?t=" + tok)
        assert json.loads(_get(url + "/api/state", tok))["mode"] == "joints"
        assert _get(url + "/img/000000.jpg") == b"\xff\xd8img0"
        for path, token in [("/img/../frames.json", None), ("/api/state", None), ("/api/state", "wrong")]:
            with pytest.raises(urllib.error.HTTPError) as e:  # whitelist of frames; api needs the token
                _get(url + path, token)
            assert e.value.code in (403, 404)
        for bad, token in [({"frames": [{"frame": 0, "view": "top", "joints": {"nose": [1, 1]}}]}, tok),
                           ({"frames": [{"frame": 0, "view": "side", "joints": {"nose": [1]}}]}, tok),
                           ({"frames": [{"frame": 99999, "view": "side", "joints": {"nose": [1, 1]}}]}, tok),
                           ({"frames": [{"frame": 0, "view": "side", "joints": {"nose": [1, 1]}}]}, "forged")]:
            with pytest.raises(urllib.error.HTTPError) as e:
                _post(url + "/api/save", bad, token)
            assert e.value.code in (400, 403) and not out.exists()
        joints = {j: [100.0, 50.0 + 10 * i] for i, j in enumerate(CANONICAL)}
        assert _post(url + "/api/save", {"frames": [{"frame": 0, "view": "side", "joints": joints}]}, tok)["saved"] == 1
    finally:
        server.shutdown()
        server.server_close()
    labels = json.loads(out.read_text())
    assert labels["frames"][0]["view"] == "side"
    # the eval accepts the file as-is (one labelled frame -> fails only on frame count)
    pose3d = {"frames": []}
    camera = {"K": [[1, 0, 0], [0, 1, 0], [0, 0, 1]], "frames": []}
    m = evaluate(pose3d, camera, labels)
    assert m["n_frames"] == 1 and m["n_side_frames"] == 1
    # resuming loads what was saved
    assert annotate.build_state("joints", frames_dir, out, count=3)["saved"] == labels["frames"]
