"""docs/specs/person-skin.md: the rest-joints route of mesh_files (AC-PS11 to AC-PS14), the node unit tests, the
browser drive and the text rules of web/skin/person-skin.js."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from part7 import mesh_files
from support import Api
from test_mesh_files import ENTRY, finished

ROOT = Path(__file__).resolve().parents[2]
REAL = Path(os.environ.get("SIMON_REAL_JOB", "/tmp/simon-demo-r17/state/jobs/4a946eb885b3")) / "work/follower/part2"
J = mesh_files.JOINTS
STRAIGHT = {"left_shoulder": (0.18, 0.5, 0), "left_elbow": (0.2, 0.22, 0), "left_wrist": (0.2, -0.04, 0),
            "right_shoulder": (-0.18, 0.5, 0), "right_elbow": (-0.2, 0.22, 0), "right_wrist": (-0.2, -0.04, 0)}
BENT = {"left_elbow": (0.2, 0.3, 0.1), "left_wrist": (0.2, 0.5, 0.35), "right_elbow": (-0.2, 0.3, 0.1), "right_wrist": (-0.2, 0.5, 0.35)}


def joints(**over: tuple[float, float, float]) -> dict[str, dict[str, float]]:
    base = {n: (0.01 * i, 0.02 * i, 0.0) for i, n in enumerate(J)}
    base.update(STRAIGHT)
    base.update(over)
    return {n: {"x": v[0], "y": v[1], "z": v[2], "conf": 1.0} for n, v in base.items()}


def pose3d(*frames: tuple[int, Any]) -> dict[str, Any]:
    return {"frames": [{"frame": f, "t_ms": f * 100.0, "people": [{"id": 0, "joints": j}]} for f, j in frames]}


def header(*frames: int | None) -> dict[str, Any]:
    return {"frames": [{"frame": i, "t_ms": i * 100.0, "people": [{"id": 0, "offset": 0}] if i in frames else []} for i in range(max(frames) + 2)]}


# AC-PS11
def test_rest_is_the_first_frame_with_a_person_and_both_elbows_under_30_degrees():
    doc = mesh_files.rest_frame(header(1, 2, 3), pose3d((1, joints(**BENT)), (2, joints()), (3, joints())))
    assert doc["schema"] == "simon.person-rest.v1"
    assert (doc["frame"], doc["index"], doc["straight"]) == (2, 2, True) and doc["bend_deg"] < 30
    assert set(doc["joints"]) == set(J) and doc["joints"]["left_wrist"] == [0.2, -0.04, 0.0]


def test_a_frame_without_a_person_in_the_mesh_is_skipped_even_when_pose3d_has_one():
    doc = mesh_files.rest_frame(header(3), pose3d((1, joints()), (3, joints(**BENT))))
    assert doc["frame"] == 3 and doc["straight"] is False


def test_with_no_straight_frame_the_straightest_wins_and_straight_is_false():
    half = {"left_elbow": (0.2, 0.3, 0.1), "left_wrist": (0.2, 0.2, 0.3)}
    doc = mesh_files.rest_frame(header(1, 2), pose3d((1, joints(**BENT)), (2, joints(**half, right_elbow=(-0.2, 0.3, 0.1), right_wrist=(-0.2, 0.2, 0.3)))))
    assert doc["frame"] == 2 and doc["straight"] is False and doc["bend_deg"] >= 30


# AC-PS17: the take's frames ride along for the weights
def test_rest_carries_every_usable_frame_as_motion_in_joint_order():
    doc = mesh_files.rest_frame(header(1, 2, 4), pose3d((1, joints(**BENT)), (2, joints()), (4, joints(**BENT))))
    assert [m["index"] for m in doc["motion"]] == [1, 2, 4]
    assert doc["motion"][1]["joints"] == [list(joints()[n][k] for k in "xyz") for n in J]
    assert doc["index"] == 2  # the rest pick is unchanged by walking every frame


def test_motion_is_capped_and_spread_over_the_whole_take():
    n = 3 * mesh_files.MOTION_MAX + 5
    doc = mesh_files.rest_frame(header(*range(n)), pose3d(*((i, joints()) for i in range(n))))
    idx = [m["index"] for m in doc["motion"]]
    assert len(idx) <= mesh_files.MOTION_MAX and idx[0] == 0 and idx[-1] > n - 5 and idx == sorted(idx)


def test_a_frame_with_an_unseen_joint_is_left_out_of_motion():
    low = joints()
    low["nose"]["conf"] = 0.1
    doc = mesh_files.rest_frame(header(1, 2), pose3d((1, joints()), (2, low)))
    assert [m["index"] for m in doc["motion"]] == [1]


# AC-PS12
@pytest.mark.parametrize("bad", [None, {}, {"frames": "x"}, {"frames": []}, {"frames": [{"frame": 1, "people": []}]}, {"frames": [{"frame": 9, "people": [{"id": 0, "joints": {}}]}]}])
def test_rest_is_none_for_a_missing_malformed_or_unmatched_pose3d(bad: Any):
    assert mesh_files.rest_frame(header(1), bad) is None


def test_rest_is_none_when_a_joint_is_unseen_non_finite_or_the_person_id_differs():
    low = joints()
    low["nose"]["conf"] = 0.1
    nan = joints()
    nan["nose"]["x"] = float("nan")
    assert mesh_files.rest_frame(header(1), pose3d((1, low))) is None
    assert mesh_files.rest_frame(header(1), pose3d((1, nan))) is None
    other = pose3d((1, joints()))
    other["frames"][0]["people"][0]["id"] = 5
    assert mesh_files.rest_frame(header(1), other) is None
    assert mesh_files.rest_frame(None, pose3d((1, joints()))) is None


# AC-PS13
def put(folder: Path, hdr: dict[str, Any] | None, pose: Any) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for name, body in (("mesh3d.json", hdr), ("pose3d.json", pose), ("mesh3d.bin", b"\0" * 16)):
        if body is not None:
            (folder / name).write_bytes(body if isinstance(body, bytes) else json.dumps(body).encode())


def test_the_route_answers_for_both_people_behind_the_done_job_gate(api: Api):
    finished(api, "trainer", lambda d: put(d / "work/trainer/part2", header(1), pose3d((1, joints()))))
    jid = finished(api, "follow", lambda d: put(d / "work/follower/part2", header(1), pose3d((1, joints(**BENT)))))
    for who in ("you", "trainer"):
        status, doc = api.json("GET", f"api/results/{jid}/mesh/{who}/rest.json")
        assert status == 200 and doc["frame"] == 1 and len(doc["joints"]) == 17, who
    status, headers, _ = api.request("GET", f"api/results/{jid}/mesh/you/rest.json")
    assert headers["content-type"].startswith("application/json")
    # the mesh index and the mesh files are unchanged by the new file
    assert api.json("GET", f"api/results/{jid}/mesh.json")[1]["you"] == f"api/results/{jid}/mesh/you/mesh3d.json"


def test_the_route_is_404_without_pose3d_without_the_mesh_for_other_jobs_people_and_paths(api: Api):
    tid = finished(api, "trainer", lambda d: put(d / "work/trainer/part2", header(1), pose3d((1, joints()))))
    nopose = finished(api, "follow", lambda d: put(d / "work/follower/part2", header(1), None))
    nomesh = finished(api, "follow", lambda d: put(d / "work/follower/part2", None, pose3d((1, joints()))))
    ok = finished(api, "follow", lambda d: put(d / "work/follower/part2", header(1), pose3d((1, joints()))))
    for path in (f"api/results/{nopose}/mesh/you/rest.json", f"api/results/{nomesh}/mesh/you/rest.json",
                 f"api/results/{tid}/mesh/trainer/rest.json", "api/results/ffffffffffff/mesh/you/rest.json",
                 "api/results/NOTANID/mesh/you/rest.json", f"api/results/{ok}/mesh/coach/rest.json",
                 f"api/results/{ok}/mesh/you/pose3d.json", f"api/results/{ok}/mesh/you/..%2Frest.json"):
        assert api.request("GET", path)[0] == 404, path
    assert api.request("POST", f"api/results/{ok}/mesh/you/rest.json")[0] != 200


def test_a_symlinked_pose3d_is_refused(api: Api, tmp_path: Path):
    secret = tmp_path / "elsewhere.json"
    secret.write_text(json.dumps(pose3d((1, joints()))))

    def fill(d: Path) -> None:
        put(d / "work/follower/part2", header(1), None)
        (d / "work/follower/part2/pose3d.json").symlink_to(secret)

    jid = finished(api, "follow", fill)
    assert api.request("GET", f"api/results/{jid}/mesh/you/rest.json")[0] == 404


# AC-PS14: the real take
@pytest.mark.skipif(not (REAL / "pose3d.json").is_file(), reason="the real job is not on this machine")
def test_the_real_take_gives_a_rest_frame_with_a_person():
    doc = mesh_files.rest_frame(json.loads((REAL / "mesh3d.json").read_text()), json.loads((REAL / "pose3d.json").read_text()))
    assert doc is not None and len(doc["joints"]) == 17
    hdr = json.loads((REAL / "mesh3d.json").read_text())
    assert hdr["frames"][doc["index"]]["frame"] == doc["frame"] and hdr["frames"][doc["index"]]["people"]
    assert doc["straight"] is False and doc["bend_deg"] < 90  # a knee raise: arms stay bent in every frame


def test_unit_tests_pass():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    r = subprocess.run([node, "--test", str(ROOT / "tests/part7/person-skin.unit.test.mjs")], capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0, r.stdout + r.stderr


def test_browser_drive_draws_the_skin():
    node, slot = shutil.which("node"), Path.home() / "claude-template/scripts/with-browser-slot.sh"
    pw = Path(os.environ.get("PLAYWRIGHT_DIR", ROOT / "node_modules"))
    if not node or not slot.is_file() or not (pw / "playwright").is_dir():
        pytest.skip("node, the browser slot script or playwright is not available")
    r = subprocess.run(["bash", str(slot), node, str(ROOT / "tests/part7/person-skin.browser.mjs")], capture_output=True, text=True,
                       cwd=ROOT, timeout=240, env={**os.environ, "PLAYWRIGHT_DIR": str(pw)})
    assert r.returncode == 0, r.stdout + r.stderr


def test_no_dash_no_absolute_url_and_only_result_urls_in_the_skin_source():
    for rel in ("web/skin/person-skin.js", "web/skin/motion-weights.js", "docs/specs/person-skin.md", "part7/mesh_files.py"):
        if not (ROOT / rel).is_file() and rel.startswith("docs/specs/"):
            continue  # docs/specs/ is not published to the client repo
        text = (ROOT / rel).read_text()
        assert "\u2014" not in text and "\u2013" not in text, rel
    src = (ROOT / "web/skin/person-skin.js").read_text()
    assert not re.search(r"""["'`](https?:)?//""", src)
    assert re.findall(r"api/results/", src) and ENTRY


# AC-PS18: the skin weights are computed once on the server and shipped in rest.json
VECTOR = json.loads((ROOT / "tests/part7/skin-weights-vector.json").read_text())


def test_the_server_rule_gives_the_shared_test_vector_bit_for_bit():
    from skin_weights_vector import inputs
    from part7 import take_rig

    bones, weights = take_rig.motion_weights(inputs(VECTOR))
    assert VECTOR["expected"]["bones"] == list(take_rig.NAMES)
    assert [b for pair in bones for b in pair] == VECTOR["expected"]["bone"]
    assert [w for pair in weights for w in pair] == VECTOR["expected"]["weight"]  # floats compared exactly


def vector_files(folder: Path) -> None:
    """The shared vector as Part 2 files: one int16 block per frame, pose3d with its joints; no vertex_joint labels."""
    import struct

    folder.mkdir(parents=True, exist_ok=True)
    blob, frames, poses = bytearray(), [], []
    for k, f in enumerate(VECTOR["frames"]):
        frames.append({"frame": k, "t_ms": k * 100.0, "people": [{"id": 0, "offset": len(blob)}]})
        blob += struct.pack(f"<{len(f['block'])}h", *f["block"])
        poses.append({"frame": k, "t_ms": k * 100.0, "people": [{"id": 0, "joints": {n: {"x": v[0], "y": v[1], "z": v[2], "conf": 1.0} for n, v in f["joints"].items()}}]})
    hdr = {"vertex_count": VECTOR["vertex_count"], "vertices": {"dtype": "int16", "unit_m": VECTOR["unit_m"]}, "frames": frames}
    (folder / "mesh3d.json").write_text(json.dumps(hdr))
    (folder / "mesh3d.bin").write_bytes(bytes(blob))
    (folder / "pose3d.json").write_text(json.dumps({"frames": poses}))


def test_rest_json_ships_the_weights_of_the_take_and_weighs_a_take_once(api: Api, monkeypatch: pytest.MonkeyPatch):
    from part7 import skin_weights

    calls = []
    real = skin_weights.compute
    monkeypatch.setattr(skin_weights, "compute", lambda *a: calls.append(1) or real(*a))
    finished(api, "trainer", lambda d: vector_files(d / "work/trainer/part2"))
    jid = finished(api, "follow", lambda d: vector_files(d / "work/follower/part2"))
    status, doc = api.json("GET", f"api/results/{jid}/mesh/you/rest.json")
    w = doc["weights"]
    assert status == 200 and w["schema"] == "simon.person-weights.v1" and w["bones"] == VECTOR["expected"]["bones"]
    assert w["bone"] == VECTOR["expected"]["bone"]  # every frame of the vector is a motion frame, the rest frame first
    assert w["weight"] == [round(x, 6) for x in VECTOR["expected"]["weight"][0::2]]
    assert api.json("GET", f"api/results/{jid}/mesh/you/rest.json")[1]["weights"] == w
    assert len(calls) == 1, "the second request is served from the cache"


def test_rest_json_has_no_weights_when_the_bin_does_not_hold_the_frames(api: Api):
    finished(api, "trainer", lambda d: put(d / "work/trainer/part2", header(1), pose3d((1, joints()))))
    jid = finished(api, "follow", lambda d: put(d / "work/follower/part2", header(1), pose3d((1, joints()))))
    status, doc = api.json("GET", f"api/results/{jid}/mesh/you/rest.json")
    assert status == 200 and "weights" not in doc and doc["motion"]  # the browser computes them from motion instead


# TICKET-323 review residuals R1 to R3 of part7.skin_weights
def _vector_doc(folder: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    vector_files(folder)
    hdr = json.loads((folder / "mesh3d.json").read_text())
    return hdr, mesh_files.rest_frame(hdr, json.loads((folder / "pose3d.json").read_text()))


def test_concurrent_cold_requests_compute_the_weights_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):  # R1
    import threading
    import time

    from part7 import skin_weights

    hdr, doc = _vector_doc(tmp_path / "p")
    calls = []
    real = skin_weights.compute
    monkeypatch.setattr(skin_weights, "compute", lambda *a: (calls.append(1), time.sleep(0.3), real(*a))[2])
    taken = skin_weights.stamp(tmp_path / "p")
    out: list[Any] = []
    threads = [threading.Thread(target=lambda: out.append(skin_weights.weights(tmp_path / "p", hdr, doc, taken))) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(calls) == 1 and len(out) == 4 and all(o is out[0] and o is not None for o in out)
    assert not skin_weights._inflight, "no gate is left behind"


def test_the_cache_stamp_is_taken_before_the_files_are_read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):  # R2
    from part7 import job_lookup, skin_weights

    folder = tmp_path / "p"
    _vector_doc(folder)
    order: list[str] = []
    real_stamp, real_read = skin_weights.stamp, job_lookup.read_json
    monkeypatch.setattr(skin_weights, "stamp", lambda f: (order.append("stamp"), real_stamp(f))[1])
    monkeypatch.setattr(job_lookup, "read_json", lambda p: (order.append(Path(p).name), real_read(p))[1])
    monkeypatch.setattr(mesh_files, "mesh_dir", lambda *a: folder)
    doc = mesh_files.rest(tmp_path, "aaaaaaaaaaaa", "you")
    assert doc is not None and "weights" in doc
    assert order[:3] == ["stamp", "mesh3d.json", "pose3d.json"]
    # a file replaced after the stamp: the next stamp differs, so the old result is not served for the new files
    taken = real_stamp(folder)
    (folder / "pose3d.json").write_text((folder / "pose3d.json").read_text() + " ")
    assert real_stamp(folder) != taken


def test_a_bin_gone_after_the_stamp_answers_none_instead_of_raising(tmp_path: Path):  # R3
    from part7 import skin_weights

    hdr, doc = _vector_doc(tmp_path / "p")
    taken = skin_weights.stamp(tmp_path / "p")
    (tmp_path / "p/mesh3d.bin").unlink()
    assert skin_weights.weights(tmp_path / "p", hdr, doc, taken) is None
    assert skin_weights.stamp(tmp_path / "p") is None and skin_weights.weights(tmp_path / "p", hdr, doc, None) is None
