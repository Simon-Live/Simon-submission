"""The life-size AR take: rig, GLB, USDZ and routes (docs/specs/take-ar.md; TICKET-282 AC-1, AC-3 server part, AC-4)."""

from __future__ import annotations

import math
import re
import struct
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any, Callable

import pytest

from part7 import jobs, take_ar, take_glb, take_load, take_rig, take_usdz
from support import Api
from take_fixture import N_FRAMES, STEP_MS, write_person

ENTRY = "lateral-raise-0f13199f"
DASHES = ("\u2014", "\u2013")


@pytest.fixture()
def person(tmp_path: Path) -> take_rig.Figure:
    write_person(tmp_path / "p")
    fig = take_load.load_figure(tmp_path / "p", "you")
    assert fig is not None
    return fig


def accessor(doc: dict[str, Any], blob: bytes, index: int) -> list[float]:
    """The values of a float or ubyte accessor, flat."""
    a = doc["accessors"][index]
    v = doc["bufferViews"][a["bufferView"]]
    width = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}[a["type"]]
    code = {5126: "f", 5121: "B", 5123: "H", 5125: "I"}[a["componentType"]]
    return list(struct.unpack_from(f"<{a['count'] * width}{code}", blob, v["byteOffset"]))


# ---- the rig (AC-1: joints) ------------------------------------------------------------------------------------


def test_rig_has_seventeen_bones_in_parent_first_order() -> None:
    assert len(take_rig.NAMES) == 17 and take_rig.NAMES[0] == "hips"
    assert all(p < i for i, p in enumerate(take_rig.PARENT) if p >= 0) and take_rig.PARENT.count(-1) == 1


def test_bind_frame_reproduces_the_measured_mesh(person: take_rig.Figure) -> None:
    rest = 0  # the fixture's arms are straight at frame 0
    posed = take_rig.pose_vertices(person, rest)
    shift = (0.0, -person.ground[rest], 0.0)
    worst = max(take_rig.norm(take_rig.sub(a, take_rig.add(b, shift))) for a, b in zip(posed, person.measured[rest]))
    assert worst < 1e-4
    assert all(abs(q[3]) > 0.9999 for q in person.rotations[rest])  # identity at bind


def test_forearm_rotation_follows_the_measured_bend(person: take_rig.Figure) -> None:
    lower = take_rig.INDEX["rightLowerArm"]
    last = person.rotations[-1][lower]
    angle = math.degrees(2 * math.acos(min(1.0, abs(last[3]))))
    expected = math.degrees(0.26 * (N_FRAMES - 1))
    assert abs(angle - expected) < 1.0


def test_figure_stands_on_the_floor(person: take_rig.Figure) -> None:
    for k in range(len(person.times)):
        ys = [v[1] for v in take_rig.pose_vertices(person, k)]
        assert abs(min(ys)) < 0.05


def test_skin_weights_are_two_bones_summing_to_one(person: take_rig.Figure) -> None:
    assert all(abs(w0 + w1 - 1) < 1e-9 for w0, w1 in person.weights)
    assert all(0 <= b < 17 for pair in person.bones for b in pair)


def test_fit_error_is_small_on_the_fixture(person: take_rig.Figure) -> None:
    assert take_rig.fit_error_m(person)["worst_frame_mean"] < 0.03


# AC-PS17 of person-skin.md: the rig's weights come from the take's motion, as the browser's person skin's do
STAND = {"nose": (0, 0.666, 0.097), "left_eye": (0.031, 0.71, 0.068), "right_eye": (-0.031, 0.71, 0.068),
         "left_ear": (0.064, 0.7, 0), "right_ear": (-0.064, 0.7, 0), "left_shoulder": (0.18, 0.5, 0),
         "right_shoulder": (-0.18, 0.5, 0), "left_elbow": (0.2, 0.22, 0), "right_elbow": (-0.2, 0.22, 0),
         "left_wrist": (0.2, -0.04, 0), "right_wrist": (-0.2, -0.04, 0), "left_hip": (0.09, 0, 0), "right_hip": (-0.09, 0, 0),
         "left_knee": (0.09, -0.42, 0), "right_knee": (-0.09, -0.42, 0), "left_ankle": (0.09, -0.84, 0),
         "right_ankle": (-0.09, -0.84, 0)}


def test_a_waist_vertex_beside_the_hanging_forearm_follows_the_torso_once_the_arm_rises() -> None:
    raised = {**STAND, "left_elbow": (0.46, 0.5, 0), "left_wrist": (0.72, 0.5, 0)}
    rest = [(0.12, 0.2, 0.0), (0.2, 0.09, 0.03), (0.09, -0.9, 0.08)]  # waist, forearm, left foot
    moved = [(0.12, 0.2, 0.0), (0.59, 0.5, 0.03), (0.09, -0.9, 0.08)]
    bones, weights = take_rig.motion_weights([(rest, take_rig.derive(STAND)), (moved, take_rig.derive(raised))])
    name = [take_rig.NAMES[b0] for b0, _ in bones]
    assert name[0] in ("hips", "spine", "chest") and name[1] == "leftLowerArm"
    w_arm = [w for (b, w) in zip(bones[0], weights[0]) if take_rig.NAMES[b].endswith("Arm")]
    assert sum(w_arm) < 0.2
    assert all(not take_rig.NAMES[b].startswith("right") for b in bones[2])  # a foot never shares the other shin
    assert all(abs(sum(w) - 1) < 1e-9 for w in weights)


def test_the_rig_weighs_up_to_motion_max_frames_and_always_the_bind_frame() -> None:
    assert take_rig.motion_sample(10, 3) == list(range(10))
    big = take_rig.motion_sample(200, 5)  # every 4th frame: 5 is not one, so it is added first
    assert big[0] == 5 and big[1:] == list(range(0, 200, 4)) and len(big) <= take_rig.MOTION_MAX + 1


def test_a_mesh_without_vertex_joint_labels_still_rigs(tmp_path: Path) -> None:
    import json

    write_person(tmp_path / "p")
    hdr = json.loads((tmp_path / "p/mesh3d.json").read_text())
    del hdr["vertex_joint"]  # the weights come from the take's motion; the labels are not read
    (tmp_path / "p/mesh3d.json").write_text(json.dumps(hdr))
    fig = take_load.load_figure(tmp_path / "p", "you")
    assert fig is not None and len(fig.bones) == hdr["vertex_count"]


# ---- loading ---------------------------------------------------------------------------------------------------


def test_frames_without_a_pose_are_left_out(tmp_path: Path) -> None:
    write_person(tmp_path, drop=(2, 3))
    fig = take_load.load_figure(tmp_path, "you")
    assert fig is not None and len(fig.times) == N_FRAMES - 2
    assert fig.times[-1] == pytest.approx((N_FRAMES - 1) * STEP_MS / 1000)


def test_a_take_with_one_usable_frame_is_refused(tmp_path: Path) -> None:
    write_person(tmp_path, drop=tuple(range(1, N_FRAMES)))
    assert take_load.load_figure(tmp_path, "you") is None


def test_truncated_bin_and_missing_files_give_none(tmp_path: Path) -> None:
    write_person(tmp_path)
    (tmp_path / "mesh3d.bin").write_bytes((tmp_path / "mesh3d.bin").read_bytes()[:200])
    assert take_load.load_figure(tmp_path, "you") is None
    assert take_load.load_figure(tmp_path / "nope", "you") is None


def test_mirrored_clip_swaps_sides(tmp_path: Path) -> None:
    write_person(tmp_path / "a")
    write_person(tmp_path / "b", mirrored=True)
    plain, mirror = take_load.load_figure(tmp_path / "a", "x"), take_load.load_figure(tmp_path / "b", "x")
    assert plain is not None and mirror is not None
    assert mirror.rest_joints["left_shoulder"][0] == pytest.approx(-plain.rest_joints["right_shoulder"][0])
    assert mirror.rest_joints["left_shoulder"][0] > 0  # the subject's left stays on +X


# ---- the GLB (AC-1, AC-4) ---------------------------------------------------------------------------------------


def test_glb_joint_count_animation_length_and_size(person: take_rig.Figure) -> None:
    data = take_glb.build_glb([person])
    doc, blob = take_glb.read_glb(data)
    assert len(doc["skins"]) == 1 and len(doc["skins"][0]["joints"]) == 17
    anim = doc["animations"][0]
    assert anim["name"] == "take" and len(anim["channels"]) == 17 + 1  # a rotation per joint and the hips position
    ends = {accessor(doc, blob, s["input"])[-1] for s in anim["samplers"]}
    assert all(e == pytest.approx((N_FRAMES - 1) * STEP_MS / 1000, abs=1e-4) for e in ends)
    assert len(data) < take_ar.MAX_BYTES
    assert doc["asset"]["extras"]["duration_s"] == pytest.approx(person.duration_s, abs=1e-3)


def test_glb_animation_values_match_the_figure(person: take_rig.Figure) -> None:
    doc, blob = take_glb.read_glb(take_glb.build_glb([person]))
    anim = doc["animations"][0]
    names = {n["name"]: i for i, n in enumerate(doc["nodes"])}
    ch = next(c for c in anim["channels"] if c["target"]["node"] == names["hips"] and c["target"]["path"] == "translation")
    got = accessor(doc, blob, anim["samplers"][ch["sampler"]]["output"])
    assert got[3:6] == pytest.approx(list(person.hips[1]), abs=1e-5)


def test_glb_bind_accessors_are_consistent(person: take_rig.Figure) -> None:
    doc, blob = take_glb.read_glb(take_glb.build_glb([person]))
    prim = doc["meshes"][0]["primitives"][0]
    n = doc["accessors"][prim["attributes"]["POSITION"]]["count"]
    assert n == len(person.positions)
    weights = accessor(doc, blob, prim["attributes"]["WEIGHTS_0"])
    assert all(abs(sum(weights[4 * i:4 * i + 4]) - 1) < 1e-5 for i in range(n))
    joints = accessor(doc, blob, prim["attributes"]["JOINTS_0"])
    assert max(joints) < 17
    assert max(accessor(doc, blob, prim["indices"])) < n


def test_glb_carries_no_image_texture_or_uv_from_the_video(person: take_rig.Figure) -> None:
    doc, blob = take_glb.read_glb(take_glb.build_glb([person]))
    for key in ("images", "textures", "samplers", "cameras", "extensionsUsed"):
        assert key not in doc, key
    for mesh in doc["meshes"]:
        for prim in mesh["primitives"]:
            assert not [a for a in prim["attributes"] if a.startswith(("TEXCOORD", "COLOR"))]
    for mat in doc["materials"]:
        assert set(mat) <= {"name", "pbrMetallicRoughness", "alphaMode"}
        assert set(mat["pbrMetallicRoughness"]) == {"baseColorFactor", "metallicFactor", "roughnessFactor"}
    assert not re.search(rb"\x89PNG|\xff\xd8\xff|RIFF|ftyp", blob)  # no embedded picture or video data


def test_ghost_adds_a_second_see_through_figure(person: take_rig.Figure, tmp_path: Path) -> None:
    write_person(tmp_path / "g")
    ghost = take_load.load_figure(tmp_path / "g", "ghost")
    assert ghost is not None
    doc, _ = take_glb.read_glb(take_glb.build_glb([person, ghost]))
    assert [len(s["joints"]) for s in doc["skins"]] == [17, 17]
    assert len(doc["animations"]) == 1 and len(doc["animations"][0]["channels"]) == 36
    assert doc["materials"][1]["alphaMode"] == "BLEND" and "alphaMode" not in doc["materials"][0]
    names = [n["name"] for n in doc["nodes"]]
    assert len(names) == len(set(names)) and "ghost_hips" in names
    targets = {c["target"]["node"] for c in doc["animations"][0]["channels"]}
    assert all(0 <= t < len(names) for t in targets)


def test_glb_refuses_zero_or_three_figures(person: take_rig.Figure) -> None:
    for figs in ([], [person, person, person]):
        with pytest.raises(take_rig.RigError):
            take_glb.build_glb(figs)


def test_long_takes_lose_frames_not_the_end(person: take_rig.Figure) -> None:
    full = take_ar.make("glb", [person], {})
    small = take_ar.make("glb", [person], {}, max_bytes=len(full) - 100)
    doc, blob = take_glb.read_glb(small)
    t = accessor(doc, blob, doc["animations"][0]["samplers"][0]["input"])
    assert len(small) < len(full) and t[-1] == pytest.approx(person.duration_s, abs=1e-4) and len(t) < N_FRAMES


# ---- the USDZ (AC-1 for iOS, AC-4) ------------------------------------------------------------------------------


def test_usdz_is_a_stored_aligned_package_of_one_layer(person: take_rig.Figure) -> None:
    data = take_usdz.build_usdz([person])
    with zipfile.ZipFile(BytesIO(data)) as z:
        assert z.namelist() == ["take.usda"] and z.testzip() is None
        info = z.infolist()[0]
        assert info.compress_type == zipfile.ZIP_STORED
        text = z.read("take.usda").decode()
    extra_len = struct.unpack_from("<H", data, info.header_offset + 28)[0]
    assert (info.header_offset + 30 + len(info.filename) + extra_len) % 64 == 0
    assert text.startswith("#usda 1.0") and 'defaultPrim = "Take"' in text and 'upAxis = "Y"' in text
    assert text.count("SkelAnimation") == 1 and "UsdPreviewSurface" in text


def test_usdz_has_seventeen_joints_the_take_length_and_no_picture(person: take_rig.Figure) -> None:
    text = take_usda(person)
    joints = re.search(r'uniform token\[\] joints = \[([^\]]*)\]', text)
    assert joints is not None and len(joints.group(1).split(",")) == 17
    assert f"endTimeCode = {take_usdz._f(person.duration_s * take_usdz.FPS)}" in text
    assert not re.search(r"@[^@]*\.(png|jpe?g|webp|mp4|mov|exr)@|inputs:file|UsdUVTexture|primvars:st", text, re.I)
    with zipfile.ZipFile(BytesIO(take_usdz.build_usdz([person]))) as z:
        assert [i.filename for i in z.infolist() if not i.filename.endswith(".usda")] == []


def take_usda(*figs: take_rig.Figure) -> str:
    return take_usdz.build_usda(list(figs))


def test_usdz_ghost_is_a_second_skel_root_with_opacity(person: take_rig.Figure) -> None:
    text = take_usda(person, person)
    assert text.count("def SkelRoot") == 2 and 'SkelRoot "Ghost"' in text and "inputs:opacity = 0.45" in text


def test_user_facing_text_has_no_dash_the_writer_bans(person: take_rig.Figure) -> None:
    for text in (take_usda(person), take_glb.LICENCE, take_ar.MSG_GONE):
        assert not any(d in text for d in DASHES)


# ---- the routes (AC-1 endpoint; AC-3 negative: no mesh, no button) ----------------------------------------------


def finished(api: Api, kind: str, fill: Callable[[Path], None]) -> str:
    def fn(ctx: jobs.JobContext) -> dict[str, Any]:
        fill(ctx.dir)
        return {"result": {"entry_id": ENTRY}}

    rec = api.app.queue.submit(kind, fn, entry_id=ENTRY)
    assert api.app.queue.wait(rec["id"], 10)["status"] == "done"
    return rec["id"]


def with_people(api: Api, trainer: bool = True, you: bool = True) -> str:
    finished(api, "trainer", (lambda d: write_person(d / "work" / "trainer" / "part2")) if trainer else (lambda d: None))
    return finished(api, "follow", (lambda d: write_person(d / "work" / "follower" / "part2")) if you else (lambda d: None))


def test_index_lists_files_for_people_with_a_mesh(api: Api) -> None:
    jid = with_people(api)
    status, doc = api.json("GET", f"api/results/{jid}/take-ar.json")
    base = f"api/results/{jid}/take"
    assert status == 200 and doc["schema"] == take_ar.SCHEMA
    assert doc["trainer"] == {"glb": f"{base}/trainer.glb", "usdz": f"{base}/trainer.usdz", "duration_s": 0.5,
                              "glb_ghost": f"{base}/trainer.glb?ghost=1", "usdz_ghost": f"{base}/trainer.usdz?ghost=1"}
    assert doc["you"]["glb"] == f"{base}/you.glb"


def test_job_without_a_mesh_has_no_ar_entry_and_no_file(api: Api) -> None:
    jid = with_people(api, trainer=False, you=False)
    assert api.json("GET", f"api/results/{jid}/take-ar.json") == (200, {"schema": take_ar.SCHEMA, "trainer": None, "you": None})
    for who in ("trainer", "you"):
        for kind in ("glb", "usdz"):
            assert api.request("GET", f"api/results/{jid}/take/{who}.{kind}")[0] == 404


def test_only_the_person_with_a_mesh_gets_an_entry(api: Api) -> None:
    jid = with_people(api, trainer=False)
    _, doc = api.json("GET", f"api/results/{jid}/take-ar.json")
    assert doc["trainer"] is None and doc["you"]["glb"] and "glb_ghost" not in doc["you"]
    assert api.request("GET", f"api/results/{jid}/take/you.glb?ghost=1")[0] == 404


def test_glb_endpoint_serves_a_valid_rigged_animated_file(api: Api) -> None:
    jid = with_people(api)
    status, headers, body = api.request("GET", f"api/results/{jid}/take/trainer.glb")
    assert status == 200 and headers["content-type"] == "model/gltf-binary" and len(body) < take_ar.MAX_BYTES
    doc, _ = take_glb.read_glb(body)
    assert len(doc["skins"][0]["joints"]) == 17 and doc["animations"][0]["name"] == "take"
    assert doc["asset"]["extras"]["job"] == jid and "images" not in doc
    assert 'filename="simon-trainer-' in headers["content-disposition"]


def test_ghost_and_usdz_endpoints(api: Api) -> None:
    jid = with_people(api)
    status, _, body = api.request("GET", f"api/results/{jid}/take/trainer.glb?ghost=1")
    assert status == 200 and len(take_glb.read_glb(body)[0]["skins"]) == 2
    status, headers, body = api.request("GET", f"api/results/{jid}/take/you.usdz")
    assert status == 200 and headers["content-type"] == "model/vnd.usdz+zip" and body[:2] == b"PK"
    assert api.request("HEAD", f"api/results/{jid}/take/you.usdz")[0] == 200


def test_second_request_is_served_from_the_cache(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    jid = with_people(api)
    first = api.request("GET", f"api/results/{jid}/take/you.glb")[2]
    monkeypatch.setattr(take_load, "load_figure", lambda *a, **k: pytest.fail("rebuilt"))
    assert api.request("GET", f"api/results/{jid}/take/you.glb")[2] == first


def test_routes_refuse_other_jobs_names_and_formats(api: Api) -> None:
    jid = with_people(api)
    tid = finished(api, "trainer", lambda d: write_person(d / "work" / "trainer" / "part2"))
    paths = [f"api/results/{jid}/take/coach.glb", f"api/results/{jid}/take/you.obj", f"api/results/{jid}/take/you",
             "api/results/ffffffffffff/take-ar.json", "api/results/NOTANID/take-ar.json",
             f"api/results/{jid}/take/..%2Fjob.json"]
    paths += [f"api/results/{tid}/take-ar.json", f"api/results/{tid}/take/trainer.glb"]  # a trainer job is not a follow job
    for path in paths:
        assert api.request("GET", path)[0] == 404, path


def test_unreadable_mesh_is_404_not_a_crash(api: Api) -> None:
    def broken(d: Path) -> None:
        write_person(d / "work" / "follower" / "part2")
        (d / "work" / "follower" / "part2" / "mesh3d.bin").write_bytes(b"\0" * 10)

    jid = finished(api, "follow", broken)
    assert api.request("GET", f"api/results/{jid}/take/you.glb")[0] == 404


def test_symlinked_files_are_not_used(tmp_path: Path) -> None:
    d = tmp_path / "aaaaaaaaaaa1"
    folder = d / "work" / "follower" / "part2"
    write_person(tmp_path / "real")
    folder.mkdir(parents=True)
    (d / "job.json").write_text('{"kind": "follow", "status": "done"}', encoding="utf-8")
    for n in ("mesh3d.json", "mesh3d.bin", "pose3d.json"):
        (folder / n).symlink_to(tmp_path / "real" / n)
    assert take_ar.index(tmp_path, "aaaaaaaaaaa1") == {"schema": take_ar.SCHEMA, "trainer": None, "you": None}
    assert take_ar.render(tmp_path, "aaaaaaaaaaa1", "you", "glb", False) is None


# ---- signed links (owner only, short lived, one take) ----------------------------------------------------------


def link(api: Api, jid: str, who: str = "you", kind: str = "glb", extra: str = "") -> tuple[int, Any]:
    return api.json("GET", f"api/results/{jid}/take-ar-url?who={who}&kind={kind}{extra}")


def test_link_serves_only_that_take_with_nosniff_and_type(api: Api) -> None:
    jid = with_people(api)
    status, doc = link(api, jid, "trainer", "usdz")
    assert status == 200 and doc["url"].startswith("api/take-ar/") and doc["expires_utc"].endswith("Z")
    status, headers, body = api.request("GET", doc["url"])
    assert status == 200 and headers["content-type"] == "model/vnd.usdz+zip" and body[:2] == b"PK"
    assert headers["x-content-type-options"] == "nosniff" and "no-store" in headers["cache-control"]
    assert body == api.request("GET", f"api/results/{jid}/take/trainer.usdz")[2]
    glb = api.request("GET", link(api, jid, "you", "glb", "&ghost=1")[1]["url"])
    assert glb[0] == 200 and glb[1]["content-type"] == "model/gltf-binary" and len(take_glb.read_glb(glb[2])[0]["skins"]) == 2


def test_expired_and_tampered_links_are_refused(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    from part7 import take_ar_url
    jid = with_people(api)
    url = link(api, jid)[1]["url"]
    token = url.rsplit("/", 1)[1]
    assert api.request("GET", url)[0] == 200
    body, mac = token.split(".")
    flipped = mac[:-1] + ("A" if mac[-1] != "A" else "B")
    other = take_ar_url._b64(f"{jid}|trainer|glb|0|{4_000_000_000}".encode())
    for bad in (f"{body}.{flipped}", f"{other}.{mac}", "garbage", f"{body}.{mac[:-3]}"):
        assert api.request("GET", f"api/take-ar/{bad}")[0] == 404, bad
    real = take_ar_url.CLOCK
    monkeypatch.setattr(take_ar_url, "CLOCK", lambda: real() + take_ar_url.TTL_S + 1)
    assert api.request("GET", url)[0] == 404


def test_link_is_minutes_long_and_names_one_file(api: Api) -> None:
    from part7 import take_ar_url
    jid = with_people(api)
    token = link(api, jid)[1]["url"].rsplit("/", 1)[1]
    got = take_ar_url.verify(api.app.state, token)
    assert got == (jid, "you", "glb", False) and 0 < take_ar_url.TTL_S <= 600


def test_link_for_a_job_without_a_mesh_or_bad_query_is_404(api: Api) -> None:
    jid = with_people(api, trainer=False, you=False)
    assert link(api, jid)[0] == 404
    jid2 = with_people(api, trainer=False)
    assert link(api, jid2, "trainer")[0] == 404 and link(api, jid2, "you", "glb", "&ghost=1")[0] == 404
    for who, kind in (("coach", "glb"), ("you", "obj"), ("", "")):
        assert link(api, jid2, who, kind)[0] == 404
    assert api.json("GET", "api/results/NOTANID/take-ar-url?who=you&kind=glb")[0] == 404


def test_a_non_owner_gets_404_for_link_and_files(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    from part7 import auth
    jid = with_people(api)
    monkeypatch.setattr("part7.identity.owner_of_job", lambda state, job: "u-owner")
    monkeypatch.setattr(auth, "current_user", lambda h: "u-other")
    assert link(api, jid)[0] == 404
    assert api.request("GET", f"api/results/{jid}/take/you.glb")[0] == 404
    assert api.request("GET", f"api/results/{jid}/take-ar.json")[0] == 404
    monkeypatch.setattr(auth, "current_user", lambda h: None)
    assert link(api, jid)[0] == 404
    monkeypatch.setattr(auth, "current_user", lambda h: "u-owner")
    status, doc = link(api, jid)
    assert status == 200 and api.request("GET", doc["url"])[0] == 200


def test_mesh_index_names_the_link_requests_only_when_files_exist(api: Api) -> None:
    jid = with_people(api)
    _, doc = api.json("GET", f"api/results/{jid}/mesh.json")
    assert doc["glb"]["you"] == f"api/results/{jid}/take-ar-url?who=you&kind=glb" and doc["usdz"]["trainer"]


def test_mesh_index_has_no_link_keys_without_files(api: Api) -> None:
    bare = with_people(api, trainer=False, you=False)  # one test, one trainer job: the trainer lookup cannot pick another
    assert api.json("GET", f"api/results/{bare}/mesh.json")[1] == {"trainer": None, "you": None}
