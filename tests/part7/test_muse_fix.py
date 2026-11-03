"""TICKET-280 AC-1 to AC-5 (model side): control render, measure gate, ledger, blind referee. Fake transport; no network."""

from __future__ import annotations

import base64
import json
import math
from pathlib import Path
import struct
from typing import Any

import pytest

from part7 import history_api, muse_fix, muse_fix_api, muse_fix_geom as geom, muse_fix_measure, muse_fix_render as render, muse_referee

JOINTS = ["nose", "left_eye", "right_eye", "left_ear", "right_ear", "left_shoulder", "right_shoulder", "left_elbow",
          "right_elbow", "left_wrist", "right_wrist", "left_hip", "right_hip", "left_knee", "right_knee", "left_ankle", "right_ankle"]
JPG = b"\xff\xd8\xff\xe0" + b"frame" * 8
PNG = render.png_gray(4, 4, bytearray(range(16)))
REAL_COMPOSITE = render.composite


def points(deg: float) -> dict[str, list[float]]:
    a = math.radians(deg)
    knee = [0.0, -0.4, 0.0]
    return {"right_hip": [0.0, 0.0, 0.0], "right_knee": knee, "right_ankle": [0.4 * math.sin(a), -0.4 + 0.4 * math.cos(a), 0.0]}


def replay_doc(follower_deg: list[float], expected_deg: list[float]) -> dict[str, Any]:
    def track(degs: list[float]) -> list[list[list[float]]]:
        rows = []
        for d in degs:
            p = points(d)
            rows.append([p.get(n, [0.0, 0.0, 0.0]) for n in JOINTS])
        return rows
    return {"format": "simon.replay.v1", "joints": JOINTS, "follower": track(follower_deg), "expected": track(expected_deg),
            "exp_to_fol": list(range(len(expected_deg))), "follower_t": [i * 0.1 for i in range(len(follower_deg))]}


def build_job(root: Path, *, name: str = "job1", follower: list[float] | None = None, expected: list[float] | None = None) -> Path:
    follower, expected = follower or [100.0, 60.0, 100.0], expected or [100.0, 150.0, 100.0]
    job = root / name
    part2 = job / "work" / "follower" / "part2"
    (part2 / "frames").mkdir(parents=True)
    (job / "job.json").write_text(json.dumps({"id": name, "kind": "follow", "status": "done", "person_id": "0"}))
    fault = {"measure": "knee_flexion", "joint": "right_knee", "body_part": "legs", "side": "right", "magnitude_deg": 90.0,
             "follower_frames": [0, 2]}
    (job / "work" / "follower" / "analysis.json").write_text(json.dumps({"faults": [fault]}))
    (job / "work" / "follower" / "replay.json").write_text(json.dumps(replay_doc(follower, expected)))
    # mesh: one vertex cluster per joint label, a few triangles
    pts = points(follower[1])
    names = ["right_hip", "right_knee", "right_ankle"]
    verts, labels, faces = [], [], []
    for i, n in enumerate(names):
        x, y, z = pts[n]
        for dx, dy in ((0.0, 0.0), (0.06, 0.0), (0.0, 0.06)):
            verts.append((x + dx, y + dy, z))
            labels.append(JOINTS.index(n))
        faces.append((3 * i, 3 * i + 1, 3 * i + 2))
    faces.append((0, 3, 6))
    faces.append((3, 6, 7))
    blob = struct.pack(f"<{len(faces) * 3}H", *[i for f in faces for i in f])
    label_at = len(blob)
    blob += bytes(labels)
    offsets = []
    for _ in range(3):
        offsets.append(len(blob))
        blob += struct.pack(f"<{len(verts) * 3}h", *[round(c / 0.0001) for v in verts for c in v])
    (part2 / "mesh3d.bin").write_bytes(blob)
    (part2 / "mesh3d.json").write_text(json.dumps({
        "bin": "mesh3d.bin", "vertex_count": len(verts), "face_count": len(faces), "faces": {"offset": 0, "dtype": "uint16"},
        "vertices": {"dtype": "int16", "unit_m": 0.0001}, "vertex_joint": {"offset": label_at, "names": JOINTS},
        "frames": [{"frame": i, "t_ms": i * 100.0, "people": [{"id": 0, "offset": offsets[i]}]} for i in range(3)]}))
    k = [[300.0, 0, 64], [0, 300.0, 64], [0, 0, 1]]
    (part2 / "camera.json").write_text(json.dumps({"K": k, "image_size": [128, 128], "frames": [
        {"frame": i, "people": [{"id": 0, "R": [[1, 0, 0], [0, -1, 0], [0, 0, 1]], "t": [0.0, 0.4, 3.0]}]} for i in range(3)]}))
    (part2 / "pose3d.json").write_text(json.dumps({"frames": [
        {"frame": i, "people": [{"id": 0, "joints": {n: {"x": p[0], "y": p[1], "z": p[2], "conf": 1.0} for n, p in points(follower[i]).items()}}]}
        for i in range(3)]}))
    for i in range(3):
        (part2 / "frames" / f"{i:06d}.jpg").write_bytes(JPG)
    return job


@pytest.fixture(autouse=True)
def fake_compositor(monkeypatch: pytest.MonkeyPatch) -> None:
    """The fixture frames are not real JPEGs: the compositor hands back the overlay, which is a PNG of the frame's size."""
    monkeypatch.setattr(render, "composite", lambda frame, overlay: overlay)


class Fake:
    """Stands in for the Meta transport: records calls, returns a canned image or answer."""

    def __init__(self, *, image: bytes = PNG, letter: str | None = "A", fail: bool = False, url: bool = False):
        self.image, self.letter, self.fail, self.url = image, letter, fail, url
        self.edits: list[tuple[str, bytes]] = []
        self.bodies: list[dict[str, Any]] = []

    def edit(self, prompt: str, frame: bytes) -> dict[str, Any]:
        self.edits.append((prompt, frame))
        if self.fail:
            raise history_api.HistoryError("HTTP 500 on image edit")
        return {"data": [{"url": "https://x/y.png"}]} if self.url else {"data": [{"b64_json": base64.b64encode(self.image).decode()}]}

    def respond(self, body: dict[str, Any]) -> dict[str, Any]:
        self.bodies.append(body)
        text = json.dumps({"choice": self.letter}) if self.letter else "no idea"
        return {"output": [{"type": "message", "content": [{"text": text}]}],
                "usage": {"input_tokens": 5000, "output_tokens": 20, "input_tokens_details": {"cached_tokens": 0}}}


def measurer_at(deg: float | None):
    seen: list[Path] = []

    def measure(path: Path) -> dict[str, Any] | None:
        seen.append(path)
        assert path.is_file()
        return None if deg is None else {n: {"x": p[0], "y": p[1], "z": p[2]} for n, p in points(deg).items()}
    measure.seen = seen  # type: ignore[attr-defined]
    return measure


def ledger_rows(state: Path) -> list[dict[str, Any]]:
    return history_api.read_ledger(history_api.ledger_path(state))


# ---- geometry and render ----------------------------------------------------------------------------------

def test_angle_and_chain() -> None:
    assert geom.angle_deg((0, 1, 0), (0, 0, 0), (1, 0, 0)) == pytest.approx(90.0)
    assert geom.angle_deg((0, 0, 0), (0, 0, 0), (1, 0, 0)) is None
    assert geom.chain("right_knee") == ("right_hip", "right_knee", "right_ankle")
    assert geom.chain("nose") is None and geom.chain("spine") is None
    assert geom.joint_angle(points(77.0), "right_knee") == pytest.approx(77.0, abs=1e-6)
    assert geom.joint_angle({"right_hip": [0, 0, 0]}, "right_knee") is None


def test_choose_moment_takes_the_frame_furthest_from_the_trainer() -> None:
    m = geom.choose_moment(replay_doc([100.0, 60.0, 100.0], [100.0, 150.0, 100.0]), "right_knee", [0, 2])
    assert m["follower_frame"] == 1 and m["follower_deg"] == pytest.approx(60.0, abs=1e-6)
    assert m["target_deg"] == pytest.approx(150.0, abs=1e-6) and m["t_s"] == pytest.approx(0.1)
    assert geom.choose_moment(replay_doc([100.0], [100.0]), "nose", [0, 0]) is None
    assert geom.choose_moment({}, "right_knee", [0, 2]) is None


@pytest.mark.parametrize("target", [30.0, 90.0, 170.0])
def test_bend_limb_reaches_the_target_angle(target: float) -> None:
    p = points(60.0)
    names = ["right_hip", "right_knee", "right_ankle"]
    verts = [tuple(p[n]) for n in names]
    out = geom.bend_limb(verts, names, p, "right_knee", target)
    assert out is not None
    assert geom.angle_deg(out[0], out[1], out[2]) == pytest.approx(target, abs=1e-6)
    assert out[0] == verts[0]  # the thigh stays


def test_bend_limb_refuses_a_missing_point() -> None:
    assert geom.bend_limb([(0, 0, 0)], ["x"], {"right_hip": [0, 0, 0]}, "right_knee", 90.0) is None


def test_png_is_a_valid_grey_png() -> None:
    import zlib
    assert PNG[:8] == b"\x89PNG\r\n\x1a\n"
    w, h = struct.unpack(">II", PNG[16:24])
    assert (w, h) == (4, 4)
    idat = PNG[PNG.index(b"IDAT") + 4: PNG.index(b"IEND") - 8]
    assert len(zlib.decompress(idat)) == 4 * (4 + 1)


def test_control_render_draws_the_bent_mesh(tmp_path: Path) -> None:
    job = build_job(tmp_path)
    part2 = job / "work" / "follower" / "part2"
    joints = json.loads((part2 / "pose3d.json").read_text())["frames"][1]["people"][0]["joints"]
    a = render.control_render(part2, 1, "right_knee", 150.0, joints)
    b = render.control_render(part2, 1, "right_knee", 60.0, joints)
    assert a[:8] == b"\x89PNG\r\n\x1a\n" and a != b
    with pytest.raises(render.RenderError):
        render.control_render(part2, 99, "right_knee", 150.0, joints)
    with pytest.raises(render.RenderError):
        render.control_render(tmp_path, 1, "right_knee", 150.0, joints)


# ---- the gate (AC-1, AC-2) ---------------------------------------------------------------------------------

def test_ac1_a_picture_that_misses_is_rejected_and_never_written(tmp_path: Path) -> None:
    job, state, fake = build_job(tmp_path / "jobs"), tmp_path / "state", Fake()
    meas = measurer_at(150.0 - 8.5)  # 8.5 degrees off the target of 150
    out = muse_fix.run(job, consent=True, transport=fake, measurer=meas, state=state)
    assert out["status"] == "missed" and out["error_deg"] == 8.5 and out["target_deg"] == 150.0
    assert not list(muse_fix.folder(job).glob("corrected*")), "a rejected image must not be written"
    assert muse_fix.latest_card(job) == {"status": "missed", "message": "The image model missed the pose."}
    assert meas.seen and not meas.seen[0].exists()  # the scratch copy is gone too


def test_ac2_a_shown_picture_has_its_label_error_model_and_cost(tmp_path: Path) -> None:
    job, state, fake = build_job(tmp_path / "jobs"), tmp_path / "state", Fake()
    out = muse_fix.run(job, consent=True, transport=fake, measurer=measurer_at(150.0 - 7.9), state=state)
    assert out["status"] == "shown" and out["error_deg"] == 7.9
    assert (muse_fix.folder(job) / out["image"]).read_bytes() == PNG
    card = muse_fix.latest_card(job)
    assert card["label"] == "AI-generated illustration"
    assert card["error_text"] == "Measured error: 7.9 degrees from the target pose."
    rec = muse_fix.records(job)[-1]
    assert rec["model"] == "muse-image-1.0" and rec["cost_usd"] == 0.01 and rec["error_deg"] == 7.9
    assert rec["threshold_deg"] == 8.0 and rec["joint"] == "right_knee"
    prompt, frame = fake.edits[0]
    assert frame[:8] == b"\x89PNG\r\n\x1a\n" and len(fake.edits) == 1
    assert "right leg" in prompt and "Stop the shin exactly at the yellow ankle dot" in prompt and "pointing" in prompt
    rows = ledger_rows(state)
    assert [r["kind"] for r in rows] == ["reserve", "settle"]
    assert {r["feature"] for r in rows} == {"muse-fix-image"} and rows[0]["model"] == "muse-image-1.0"
    assert rows[0]["prompt_version"] == "muse-fix-image.v3"


def test_a_person_the_model_cannot_find_is_a_miss(tmp_path: Path) -> None:
    job = build_job(tmp_path / "jobs")
    out = muse_fix.run(job, consent=True, transport=Fake(), measurer=measurer_at(None), state=tmp_path / "s")
    assert out["status"] == "missed" and out["error_deg"] is None
    assert not list(muse_fix.folder(job).glob("corrected*"))


def test_a_failed_call_is_recorded_and_shows_no_picture(tmp_path: Path) -> None:
    job = build_job(tmp_path / "jobs")
    out = muse_fix.run(job, consent=True, transport=Fake(fail=True), measurer=measurer_at(150.0), state=tmp_path / "s")
    assert out["status"] == "failed" and "HTTP 500" in out["reason"]
    assert muse_fix.latest_card(job)["message"] == "Simon could not draw the picture this time."


def test_a_returned_link_is_never_fetched(tmp_path: Path) -> None:
    with pytest.raises(history_api.HistoryError, match="link"):
        muse_fix_api.edit_image(JPG, 'p', transport=Fake(url=True), state=tmp_path)
    with pytest.raises(history_api.HistoryError):
        muse_fix_api.edit_image(JPG, 'p', transport=Fake(image=b"not an image"), state=tmp_path)


def test_a_feature_cap_stops_the_call_before_it_is_made(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIMON7_HISTORY_MUSE_FIX_IMAGE_CALL_MAX_USD", "0.001")
    fake = Fake()
    with pytest.raises(history_api.HistoryError, match="per-call limit"):
        muse_fix_api.edit_image(JPG, 'p', transport=fake, state=tmp_path)
    assert fake.edits == [] and ledger_rows(tmp_path) == []


def test_spend_caps_are_off_by_default_and_spend_is_logged(tmp_path: Path) -> None:
    for _ in range(3):
        muse_fix_api.edit_image(JPG, 'p', transport=Fake(), state=tmp_path)
    assert history_api.spent_by_feature(history_api.ledger_path(tmp_path)) == {"muse-fix-image": 0.03}


def test_unsupported_or_unfinished_takes_send_nothing(tmp_path: Path) -> None:
    job, fake = build_job(tmp_path / "jobs"), Fake()
    analysis = job / "work" / "follower" / "analysis.json"
    analysis.write_text(json.dumps({"faults": [{"joint": "nose", "follower_frames": [0, 1]}]}))
    assert muse_fix.run(job, consent=True, transport=fake, state=tmp_path / "s")["status"] == "not_available"
    assert muse_fix.run(tmp_path / "nope", consent=True, transport=fake, state=tmp_path / "s")["status"] == "not_available"
    assert fake.edits == []


# ---- AC-5 negative assertion ---------------------------------------------------------------------------------

def test_ac5_with_consent_off_no_call_is_made_and_no_card_appears(tmp_path: Path) -> None:
    job, state, fake = build_job(tmp_path / "jobs"), tmp_path / "state", Fake()
    meas = measurer_at(150.0)
    assert muse_fix.run(job, consent=False, transport=fake, measurer=meas, state=state) == {"status": "no_consent"}
    assert muse_fix.run(job, consent=None, transport=fake, measurer=meas, state=state) == {"status": "no_consent"}  # type: ignore[arg-type]
    pics = [b"x"]
    assert muse_fix.referee(job, *pics * 3, consent=False, transport=fake, state=state) == {"status": "no_consent"}
    assert fake.edits == [] and fake.bodies == [] and meas.seen == []
    assert muse_fix.latest_card(job) is None and not muse_fix.folder(job).exists() and not state.exists()


def test_delete_removes_pictures_and_records_with_the_take(tmp_path: Path) -> None:
    job = build_job(tmp_path / "jobs")
    muse_fix.run(job, consent=True, transport=Fake(), measurer=measurer_at(150.0), state=tmp_path / "s")
    assert muse_fix.delete(job) is True and not muse_fix.folder(job).exists() and muse_fix.delete(job) is False


# ---- AC-3 report ----------------------------------------------------------------------------------------------

def test_report_counts_real_runs_with_job_ids(tmp_path: Path) -> None:
    root = tmp_path / "jobs"
    for name, deg in (("a1", 150.0), ("b2", 100.0), ("c3", 149.0)):
        muse_fix.run(build_job(root, name=name), consent=True, transport=Fake(), measurer=measurer_at(deg), state=tmp_path / "s")
    rep = muse_fix.report(root)
    assert rep["takes"] == 3 and rep["scored"] == 3 and rep["shown"] == 2 and rep["pass_rate"] == pytest.approx(0.667)
    assert {r["job_id"]: r["status"] for r in rep["runs"]} == {"a1": "shown", "b2": "missed", "c3": "shown"}
    (tmp_path / "empty").mkdir()
    assert muse_fix.report(tmp_path / "empty")["pass_rate"] is None


# ---- AC-4 blind referee ---------------------------------------------------------------------------------------

def test_ac4_order_comes_from_the_stored_seed_and_is_balanced() -> None:
    assert [muse_referee.corrected_letter(s) for s in range(5)] == [muse_referee.corrected_letter(s) for s in range(5)]
    letters = [muse_referee.corrected_letter(s) for s in range(400)]
    assert 140 < letters.count("A") < 260 and set(letters) == {"A", "B"}


def test_ac4_the_key_is_never_sent(tmp_path: Path) -> None:
    fake = Fake(letter="A")
    ref, orig, corr = JPG + b"ref", JPG + b"orig", JPG + b"corr"
    for seed in (987654321, 987654322, 987654323, 987654324):
        t = muse_referee.trial(ref, orig, corr, seed=seed, transport=fake, state=tmp_path)
        key = muse_referee.corrected_letter(seed)
        body = json.dumps(fake.bodies[-1])
        for word in ("corrected", "original", "key", str(seed), "trainer", "student"):
            assert word not in body.replace("simon_muse_fix_referee", "")
        urls = [c["image_url"] for c in fake.bodies[-1]["input"][0]["content"] if c["type"] == "input_image"]
        decode = [base64.b64decode(u.split(",", 1)[1]) for u in urls]
        assert decode[0] == ref
        assert decode[1:] == ([corr, orig] if key == "A" else [orig, corr])
        assert t["picked_corrected"] is (key == "A") and t["key"] == key and t["seed"] == seed


def test_referee_ledger_line_has_its_own_feature(tmp_path: Path) -> None:
    muse_referee.trial(JPG, JPG, JPG, seed=1, transport=Fake(), state=tmp_path)
    rows = ledger_rows(tmp_path)
    assert [r["kind"] for r in rows] == ["reserve", "settle"] and {r["feature"] for r in rows} == {"muse-fix-referee"}
    assert rows[1]["usd"] == history_api.price(5000, 20) and rows[1]["model"] == "muse-spark-1.3"


def test_a_reply_with_no_letter_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(history_api.HistoryError, match="no letter"):
        muse_referee.trial(JPG, JPG, JPG, seed=1, transport=Fake(letter=None), state=tmp_path)
    assert muse_fix.referee(tmp_path, JPG, JPG, JPG, consent=True, transport=Fake(letter=None), state=tmp_path)["status"] == "failed"


def test_binomial_p_and_badge_threshold() -> None:
    assert muse_referee.binomial_p(5, 5) == pytest.approx(1 / 32)
    assert muse_referee.binomial_p(4, 5) == pytest.approx(6 / 32)
    assert muse_referee.binomial_p(0, 5) == 1.0 and muse_referee.binomial_p(1, 0) == 1.0 and muse_referee.binomial_p(6, 5) == 0.0
    five = [{"picked_corrected": True}] * 5
    assert muse_referee.summary(five) == {"n": 5, "k": 5, "p": 0.03125, "badge": True}
    assert muse_referee.summary(five[:4] + [{"picked_corrected": False}])["badge"] is False
    assert muse_referee.summary([]) == {"n": 0, "k": 0, "p": 1.0, "badge": False}
    boundary = [{"picked_corrected": True}] * 9 + [{"picked_corrected": False}] * 2  # p(9 of 11) = 67/2048 = 0.0327
    assert muse_referee.summary(boundary)["badge"] is True
    assert muse_referee.summary([{"picked_corrected": True}] * 8 + [{"picked_corrected": False}] * 3)["badge"] is False


def test_referee_stores_records_beside_the_take_and_aggregates(tmp_path: Path) -> None:
    root = tmp_path / "jobs"
    job = build_job(root)
    for seed in range(5):
        out = muse_fix.referee(job, JPG, JPG + b"o", JPG + b"c", consent=True, seed=seed, transport=Fake(letter=muse_referee.corrected_letter(seed)), state=tmp_path / "s")
        assert out["status"] == "ok"
    assert out["summary"] == {"n": 5, "k": 5, "p": 0.03125, "badge": True}
    stored = (muse_fix.folder(job) / "referee.json").read_text()
    assert "seed" in stored and JPG.hex() not in stored  # the key's seed is kept, the pictures are not
    assert muse_fix.report(root)["referee"]["badge"] is True
    muse_fix.delete(job)
    assert muse_fix.report(root)["referee"]["n"] == 0


# ---- measure wrapper and CLI -----------------------------------------------------------------------------------

def test_read_joints_reads_the_first_person(tmp_path: Path) -> None:
    (tmp_path / "pose3d.json").write_text(json.dumps({"frames": [{"people": [{"id": 0, "joints": {"nose": {"x": 0, "y": 0, "z": 0}}}]}]}))
    assert muse_fix_measure.read_joints(tmp_path) == {"nose": {"x": 0, "y": 0, "z": 0}}
    (tmp_path / "pose3d.json").write_text(json.dumps({"frames": [{"people": []}]}))
    assert muse_fix_measure.read_joints(tmp_path) is None
    assert muse_fix_measure.read_joints(tmp_path / "none") is None


def test_measure_is_none_when_part2_is_not_set_up(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIMON7_PART2_GPU_VENV", str(tmp_path / "no-venv"))
    img = tmp_path / "a.png"
    img.write_bytes(PNG)
    assert muse_fix_measure.measure(img) is None


def test_cli_report(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "jobs").mkdir()
    assert muse_fix.main(["report", str(tmp_path)]) == 0
    assert json.loads(capsys.readouterr().out)["pass_rate"] is None
    assert muse_fix.main(["run", str(tmp_path), "nojob"]) == 1  # no --consent: nothing happens


# ---- the request shape (TICKET-343) -------------------------------------------------------------------------

def test_prompt_names_the_limb_the_guide_and_the_turn_in_plain_words() -> None:
    text = muse_fix_api.edit_prompt("right_elbow", 77.9, 131.2)
    assert "right arm" in text and "red guide" in text and "yellow dots at the shoulder, the elbow and the wrist" in text
    assert "opens from about 78 to about 131 degrees" in text and "Remove the guide" in text
    assert "closes from about 150 to about 60 degrees" in muse_fix_api.edit_prompt("left_knee", 150.0, 60.0)
    assert "left leg" in muse_fix_api.edit_prompt("left_knee", 150.0, 60.0)
    with pytest.raises(history_api.HistoryError):
        muse_fix_api.edit_prompt("neck", 1.0, 2.0)


def test_the_body_sends_one_frame_and_high_reasoning_and_no_control_picture() -> None:
    body = muse_fix_api.edit_body("p", PNG)
    assert len(body["images"]) == 1 and body["reasoning_strength"] == "high" and body["output_format"] == "png"


def test_guide_overlay_draws_a_red_line_and_yellow_dots_on_a_transparent_picture() -> None:
    import zlib
    png = render.guide_overlay(200, 100, [(20.0, 20.0), (60.0, 50.0), (30.0, 90.0)])
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    idat = png[png.index(b"IDAT") + 4: png.index(b"IEND") - 8]
    rows = zlib.decompress(idat)
    def px(x: int, y: int) -> tuple[int, ...]:
        at = y * (200 * 4 + 1) + 1 + x * 4
        return tuple(rows[at: at + 4])

    assert px(60, 50) == (255, 255, 0, 255) and px(40, 35)[:3] == (255, 0, 0) and px(150, 10) == (0, 0, 0, 0)


def test_guide_frame_puts_the_joint_where_the_target_angle_puts_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    job = build_job(tmp_path)
    part2 = job / "work" / "follower" / "part2"
    joints = json.loads((part2 / "pose3d.json").read_text())["frames"][1]["people"][0]["joints"]
    a = render.guide_frame(part2, 1, JPG, "right_knee", 150.0, joints)
    b = render.guide_frame(part2, 1, JPG, "right_knee", 60.0, joints)
    assert a[:8] == b"\x89PNG\r\n\x1a\n" and a != b
    with pytest.raises(render.RenderError):
        render.guide_frame(part2, 99, JPG, "right_knee", 150.0, joints)
    with pytest.raises(render.RenderError):
        render.guide_frame(part2, 1, JPG, "right_knee", 150.0, {})


def test_composite_with_real_ffmpeg_lays_the_overlay_on_a_real_jpeg(tmp_path: Path) -> None:
    import shutil
    import subprocess
    if shutil.which("ffmpeg") is None:
        pytest.skip("no ffmpeg")
    jpg = tmp_path / "f.jpg"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=blue:s=64x48", "-frames:v", "1", str(jpg)], check=True)
    out = REAL_COMPOSITE(jpg.read_bytes(), render.guide_overlay(64, 48, [(5.0, 5.0), (50.0, 40.0)]))
    assert out[:8] == b"\x89PNG\r\n\x1a\n"
    with pytest.raises(render.RenderError):
        REAL_COMPOSITE(b"not a picture", render.guide_overlay(64, 48, [(5.0, 5.0), (50.0, 40.0)]))


@pytest.mark.parametrize("joint,segment,end,dot", [("left_elbow", "forearm", "wrist", "wrist"), ("right_knee", "shin", "ankle", "ankle"),
                                                   ("left_shoulder", "upper arm", "elbow", "elbow"), ("right_hip", "thigh", "knee", "knee")])
def test_every_supported_joint_gets_its_segment_direction_and_a_stop_at_the_dot(joint: str, segment: str, end: str, dot: str) -> None:
    text = muse_fix_api.edit_prompt(joint, 80.0, 130.0, (485.0, 281.0), (535.0, 231.0))
    assert f"The {segment} ends pointing down and to the left of the picture, about 45 degrees below level." in text
    assert f"Stop the {segment} exactly at the yellow {dot} dot, no further." in text and f"the {end}" in text


def test_direction_words_cover_level_straight_and_tilted_segments() -> None:
    d = geom.direction_words
    assert d((0, 0), (-50, 60)) == "pointing down and to the left of the picture, about 50 degrees below level"
    assert d((0, 0), (40, -40)) == "pointing up and to the right of the picture, about 45 degrees above level"
    assert d((0, 0), (3, 80)) == "pointing straight down" and d((0, 0), (0, -9)) == "pointing straight up"
    assert d((0, 0), (80, 4)) == "held level, pointing to the right of the picture"
    assert d((5, 5), (5, 5)) is None


def test_the_prompt_without_points_omits_the_direction_sentence() -> None:
    assert " ends " not in muse_fix_api.edit_prompt("right_elbow", 78.0, 131.0)


def test_one_image_a_call_because_two_cost_twice_as_much() -> None:
    assert muse_fix_api.edit_body("p", PNG)["n"] == 1 and muse_fix_api.IMAGE_USD == 0.01


# ---- one retry on a miss (TICKET-343) -----------------------------------------------------------------------

def sequence(*degs: float | None):
    """A measurer that reads the next angle on each call (the knee target in build_job is 150)."""
    left, seen = list(degs), []

    def measure(path: Path) -> dict[str, Any] | None:
        seen.append(path)
        deg = left.pop(0)
        return None if deg is None else {n: {"x": p[0], "y": p[1], "z": p[2]} for n, p in points(deg).items()}
    measure.seen = seen  # type: ignore[attr-defined]
    return measure


def test_a_first_picture_that_passes_makes_one_call(tmp_path: Path) -> None:
    job, state, fake = build_job(tmp_path / "jobs"), tmp_path / "state", Fake()
    out = muse_fix.run(job, consent=True, transport=fake, measurer=sequence(148.0), state=state)
    assert out["status"] == "shown" and len(fake.edits) == 1 and out["cost_usd"] == 0.01
    assert [a["error_deg"] for a in out["attempts"]] == [2.0]
    assert [r["kind"] for r in ledger_rows(state)] == ["reserve", "settle"]


def test_a_miss_then_a_pass_shows_the_second_picture_and_records_both(tmp_path: Path) -> None:
    job, state, fake = build_job(tmp_path / "jobs"), tmp_path / "state", Fake()
    out = muse_fix.run(job, consent=True, transport=fake, measurer=sequence(120.0, 146.0), state=state)
    assert out["status"] == "shown" and len(fake.edits) == 2 and out["cost_usd"] == 0.02
    assert [a["error_deg"] for a in out["attempts"]] == [30.0, 4.0] and out["error_deg"] == 4.0 and out["measured_deg"] == 146.0
    assert out["attempts"][0]["reason"] == "the joint is outside the threshold" and out["attempts"][1]["reason"] is None
    assert out["call"] == out["attempts"][1]["call"] != out["attempts"][0]["call"]
    assert len(list(muse_fix.folder(job).glob("corrected*"))) == 1
    rows = ledger_rows(state)
    assert [r["kind"] for r in rows] == ["reserve", "settle", "reserve", "settle"]
    assert [r["call"] for r in rows[:2]] == [out["attempts"][0]["call"]] * 2 and {r["feature"] for r in rows} == {"muse-fix-image"}
    assert len(muse_fix.records(job)) == 1 and muse_fix.records(job)[0]["attempts"] == out["attempts"]


def test_two_misses_are_missed_with_both_attempts_and_nothing_written(tmp_path: Path) -> None:
    job, state, fake = build_job(tmp_path / "jobs"), tmp_path / "state", Fake()
    out = muse_fix.run(job, consent=True, transport=fake, measurer=sequence(120.0, None), state=state)
    assert out["status"] == "missed" and len(fake.edits) == 2 and out["cost_usd"] == 0.02
    assert out["reason"] == "no person found in the picture" and out["error_deg"] is None
    assert [a["error_deg"] for a in out["attempts"]] == [30.0, None]
    assert not list(muse_fix.folder(job).glob("corrected*"))
    assert len(ledger_rows(state)) == 4
    assert muse_fix.latest_card(job) == {"status": "missed", "message": "The image model missed the pose."}
    assert muse_fix.report(tmp_path / "jobs")["runs"][0]["cost_usd"] == 0.02


def test_a_failed_first_call_is_not_retried(tmp_path: Path) -> None:
    job, fake = build_job(tmp_path / "jobs"), Fake(fail=True)
    out = muse_fix.run(job, consent=True, transport=fake, measurer=sequence(), state=tmp_path / "s")
    assert out["status"] == "failed" and len(fake.edits) == 1


def test_a_cap_that_fits_one_call_refuses_the_retry_and_the_miss_stands(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(history_api.CAP_ENV, "0.015")
    job, state, fake = build_job(tmp_path / "jobs"), tmp_path / "state", Fake()
    out = muse_fix.run(job, consent=True, transport=fake, measurer=sequence(120.0), state=state)
    assert out["status"] == "missed" and len(fake.edits) == 1 and out["cost_usd"] == 0.01
    assert out["attempts"][1]["call"] is None and out["attempts"][1]["reason"]
    assert [r["kind"] for r in ledger_rows(state)] == ["reserve", "settle"]


def test_a_call_that_raised_after_its_reserve_records_the_reserved_amount(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    job, state = build_job(tmp_path / "jobs"), tmp_path / "state"
    out = muse_fix.run(job, consent=True, transport=Fake(fail=True), measurer=sequence(), state=state)
    assert out["status"] == "failed" and out["cost_usd"] == 0.01
    assert [r["kind"] for r in ledger_rows(state)] == ["reserve"]
    # a call stopped before the reserve (feature per-call limit) holds nothing
    monkeypatch.setenv("SIMON7_HISTORY_MUSE_FIX_IMAGE_CALL_MAX_USD", "0.001")
    out = muse_fix.run(job, consent=True, transport=Fake(), measurer=sequence(), state=tmp_path / "s2")
    assert out["status"] == "failed" and out["cost_usd"] == 0.0 and ledger_rows(tmp_path / "s2") == []


def test_a_retry_that_fails_after_its_reserve_records_the_second_reserve(tmp_path: Path) -> None:
    class Second(Fake):
        def edit(self, prompt: str, frame: bytes) -> dict[str, Any]:
            self.fail = bool(self.edits)
            return super().edit(prompt, frame)
    job, state = build_job(tmp_path / "jobs"), tmp_path / "state"
    out = muse_fix.run(job, consent=True, transport=Second(), measurer=sequence(120.0), state=state)
    assert out["status"] == "missed" and out["cost_usd"] == 0.02
    assert [a["cost_usd"] for a in out["attempts"]] == [0.01, 0.01] and out["attempts"][1]["call"] is None
    assert [r["kind"] for r in ledger_rows(state)] == ["reserve", "settle", "reserve"]


def test_no_person_in_the_first_picture_is_retried_on_purpose(tmp_path: Path) -> None:
    """The model may have drawn the person off-frame; a second picture is worth $0.01 (spec 4a)."""
    job, state, fake = build_job(tmp_path / "jobs"), tmp_path / "state", Fake()
    out = muse_fix.run(job, consent=True, transport=fake, measurer=sequence(None, 149.0), state=state)
    assert out["status"] == "shown" and len(fake.edits) == 2
    assert out["attempts"][0]["reason"] == "no person found in the picture" and out["attempts"][0]["measured_deg"] is None


def test_the_features_total_cap_refuses_the_retry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIMON7_HISTORY_MUSE_FIX_IMAGE_CAP_USD", "0.015")
    job, state, fake = build_job(tmp_path / "jobs"), tmp_path / "state", Fake()
    out = muse_fix.run(job, consent=True, transport=fake, measurer=sequence(120.0), state=state)
    assert out["status"] == "missed" and len(fake.edits) == 1 and out["cost_usd"] == 0.01
    assert out["attempts"][1]["call"] is None and out["attempts"][1]["cost_usd"] == 0.0
    assert [r["kind"] for r in ledger_rows(state)] == ["reserve", "settle"]


def jpeg_of(width: int, height: int) -> bytes:
    return b"\xff\xd8\xff\xc0" + struct.pack(">HBHHB", 11, 8, height, width, 1) + b"\x01\x11\x00" + b"\xff\xd9"


def test_image_size_reads_png_and_jpeg_headers() -> None:
    assert render.image_size(jpeg_of(64, 48)) == (64, 48) and render.image_size(PNG) == (4, 4)
    assert render.image_size(JPG) is None and render.image_size(b"") is None


def test_the_guide_is_scaled_when_the_frame_is_not_the_cameras_size(tmp_path: Path) -> None:
    job = build_job(tmp_path)  # the camera says 128 x 128
    part2 = job / "work" / "follower" / "part2"
    joints = json.loads((part2 / "pose3d.json").read_text())["frames"][1]["people"][0]["joints"]
    same, size = render.guide_points(part2, 1, "right_knee", 150.0, joints, 0, jpeg_of(128, 128))
    half, half_size = render.guide_points(part2, 1, "right_knee", 150.0, joints, 0, jpeg_of(64, 32))
    assert size == (128, 128) and half_size == (64, 32)
    assert [c for xy in half for c in xy] == pytest.approx([c for x, y in same for c in (x / 2, y / 4)])
    assert render.guide_points(part2, 1, "right_knee", 150.0, joints, 0, JPG)[1] == (128, 128)  # unreadable header: camera size
