"""Heat on your own body (docs/specs/heat.md; TICKET-274 AC-1 and the route). Meshes here are synthetic."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

import pytest

from heat_support import STAND, replay, raise_knee, shape, write_pair
from part7 import heat, heat_rig as rig, jobs
from support import Api

ENTRY = "knee-raise-01904695"
FOLLOWER = [STAND, STAND, None]


def build(follower: list, trainer: list) -> dict[str, Any]:
    folder = Path(pytest.importorskip("tempfile").mkdtemp())
    write_pair(folder, follower)
    mesh = heat.read_mesh(json.loads((folder / "mesh3d.json").read_text()), (folder / "mesh3d.bin").read_bytes())
    built = heat.build(mesh, json.loads((folder / "pose3d.json").read_text()), replay(trainer))
    assert built is not None
    return built


def rows(built: dict[str, Any]) -> list[list[int]]:
    return heat.decode_bin(built["doc"], built["bin"])


def test_take_against_itself_has_zero_heat_on_every_vertex() -> None:  # AC-1
    built = build(FOLLOWER, [STAND] * 3)
    assert all(v == 0 for r in rows(built) for v in r)
    assert built["meta"]["worst"]["peak_m"] == 0.0 and built["doc"]["max_m"] == heat.MIN_SCALE_M


@pytest.mark.parametrize("k", [0.8, 1.15])
def test_two_body_shapes_in_the_same_pose_stay_under_a_millimetre(k: float) -> None:  # AC-1
    built = build(FOLLOWER, [shape(STAND, k)] * 3)
    peaks = [f["peak_m"] for f in built["meta"]["frames"] if f["valid"]]
    assert max(peaks) < 0.001  # the stated threshold: 1 mm, float noise only; body shape is normalised away


def test_a_raised_knee_heats_that_leg_and_not_the_other() -> None:
    built = build(FOLLOWER, [raise_knee(STAND, "right")] * 3)
    doc = built["meta"]
    assert doc["worst"]["region"] in ("right_shin", "right_thigh")
    assert doc["worst"]["joints"][0].startswith("right_")
    left = [v[0] for r, v in doc["mean_by_region_m"].items() if r.startswith("left_")]
    right = max(v[0] for r, v in doc["mean_by_region_m"].items() if r.startswith("right_"))
    assert right > 0.2 and left and max(left) < 0.2 * right  # only mesh smoothing leaks across (the synthetic faces join joints)


def test_hands_and_feet_are_masked_and_cold() -> None:
    built = build(FOLLOWER, [raise_knee(STAND, "right")] * 3)
    table, mask = rows(built), built["mask"]
    assert (len(mask), len(table)) == (51, 3) and sum(mask) == 12  # 4 labels x 3 vertices
    assert all(table[0][i] == 0 for i in range(51) if mask[i]) and max(table[0]) > 0
    assert set(built["meta"]["masked_regions"]) == set(heat.MASKED)


def test_frame_without_a_person_is_invalid_and_cold() -> None:
    built = build(FOLLOWER, [raise_knee(STAND)] * 3)
    last = built["meta"]["frames"][2]
    assert last["valid"] is False and not any(rows(built)[2])
    assert built["meta"]["worst"]["index"] in (0, 1)


def test_scale_covers_the_peak_and_heat_is_smooth_across_faces() -> None:
    built = build(FOLLOWER, [raise_knee(STAND)] * 3)
    table = rows(built)
    assert max(table[0]) == 255 and built["doc"]["max_m"] >= built["meta"]["worst"]["peak_m"]


def test_retarget_is_identity_for_equal_directions_and_follows_a_turned_limb() -> None:
    same = rig.retarget(STAND, shape(STAND, 0.7))
    assert all(abs(rig.norm(rig.sub(t[2], t[0]))) < 1e-12 and all(c == pytest.approx(r) for c, r in zip(t[1], rig.IDENTITY)) for t in same.values())
    turned = rig.retarget(STAND, raise_knee(STAND))
    pivot, rot, new = turned["right_thigh"]
    assert rig.apply(rot, (0, -0.45, 0)) == pytest.approx((0, 0, 0.45))
    assert rig.arc((0, 1, 0), (0, -1, 0)) != rig.IDENTITY and rig.arc((0, 0, 0), (1, 0, 0)) == rig.IDENTITY


def test_bad_bin_is_refused() -> None:
    with pytest.raises(ValueError):
        heat.decode_bin({"vertex_count": 4, "frames": [{}], "bin_bytes": 4}, b"XX")
    assert heat.read_mesh({"vertex_count": 3}, b"") is None


def put(api: Api, kind: str, fill: Callable[[Path], None]) -> str:
    def fn(ctx: jobs.JobContext) -> dict[str, Any]:
        fill(ctx.dir)
        return {"result": {"entry_id": ENTRY}}

    rec = api.app.queue.submit(kind, fn, entry_id=ENTRY)
    assert api.app.queue.wait(rec["id"], 10)["status"] == "done"
    return rec["id"]


def follow(api: Api, mirrored: bool = False, with_replay: bool = True) -> str:
    def fill(d: Path) -> None:
        f = d / "work" / "follower"
        write_pair(f / "part2", FOLLOWER)
        if with_replay:
            (f / "replay.json").write_text(json.dumps(replay([raise_knee(STAND)] * 3)))
        (f / "follower.json").write_text(json.dumps({"mirror": {"applied": mirrored}}))

    return put(api, "follow", fill)


def test_route_serves_heat_for_a_meshed_job_and_caches_it(api: Api) -> None:
    put(api, "trainer", lambda d: write_pair(d / "work" / "trainer" / "part2", FOLLOWER))
    jid = follow(api)
    status, doc = api.json("GET", f"api/results/{jid}/heat.json")
    assert status == 200 and doc["format"] == "part7.heat/1" and doc["masked_labels"] == heat.MASKED_LABELS
    status, headers, body = api.request("GET", f"api/results/{jid}/heat.bin")
    assert status == 200 and len(body) == doc["bin_bytes"] and headers["content-type"].startswith("application/octet-stream")
    assert api.json("GET", f"api/results/{jid}/mesh.json")[1]["heat"] == f"api/results/{jid}/heat.json"  # contract H1 optional field
    cached = api.app.queue.job_dir(jid) / "work" / "follower" / "heat" / "heat.bin"
    stamp = cached.stat().st_mtime_ns
    assert api.request("GET", f"api/results/{jid}/heat.bin")[2] == body and cached.stat().st_mtime_ns == stamp


def test_mesh_index_has_no_heat_given_only_the_follower_has_a_mesh(api: Api) -> None:
    # TICKET-375: mesh.json now names a lone follower's mesh (for Person); heat lives in the side-by-side mesh view, which
    # needs both people, so the field stays off until the trainer has a mesh too
    put(api, "trainer", lambda d: (d / "work" / "trainer" / "part2").mkdir(parents=True))
    jid = follow(api)
    status, doc = api.json("GET", f"api/results/{jid}/mesh.json")
    assert status == 200 and doc["trainer"] is None and doc["you"] == f"api/results/{jid}/mesh/you/mesh3d.json"
    assert "heat" not in doc


@pytest.mark.parametrize("case", ["no_mesh", "no_replay", "mirrored", "trainer_job", "bad_id"])
def test_route_is_404_without_a_mesh_or_replay_or_for_other_jobs(api: Api, case: str) -> None:  # AC-3 negative: no Heat control
    if case == "no_mesh":
        jid = put(api, "follow", lambda d: (d / "work" / "follower").mkdir(parents=True))
    elif case == "trainer_job":
        jid = put(api, "trainer", lambda d: write_pair(d / "work" / "trainer" / "part2", FOLLOWER))
    elif case == "bad_id":
        jid = "NOTANID"
    else:
        jid = follow(api, mirrored=case == "mirrored", with_replay=case != "no_replay")
    for name in ("heat.json", "heat.bin"):
        assert api.request("GET", f"api/results/{jid}/{name}")[0] == 404


def test_delete_take_removes_its_heat(api: Api) -> None:
    jid = follow(api)
    assert api.json("GET", f"api/results/{jid}/heat.json")[0] == 200
    folder = api.app.queue.job_dir(jid)
    assert (folder / "work" / "follower" / "heat").is_dir()
    assert api.json("POST", f"api/jobs/{jid}/delete", {})[0] == 200
    assert not folder.exists() and api.request("GET", f"api/results/{jid}/heat.bin")[0] == 404


def test_agreement_and_drop_scripts(api: Api, capsys: pytest.CaptureFixture[str]) -> None:  # AC-2 and AC-5 tooling
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
    import heat_agreement
    import heat_drop

    jid = follow(api)
    root = api.app.queue.job_dir(jid).parent
    row = heat_agreement.check(root, jid)
    assert row["heat"] and row["agrees"] is False and row["why"] == "no Part 5 fault"  # no fault file: listed as a failure
    assert row["opens"]["source"] == "heat" and row["opens"]["index"] in (0, 1)  # no fault: the hottest valid frame
    assert heat_agreement.limb("left_elbow") == "left_arm" and heat_agreement.limb("nose") == "head" and heat_agreement.limb("left_shoulder") == "torso"
    assert heat_drop.main([str(root), jid, jid]) == 3  # no improvement: motif dropped
    cool = heat_drop.compare({"a": 0.2, "b": 0.1}, {"a": 0.1, "b": 0.1})
    assert cool["improved"] and cool["regions"]["a"]["drop_m"] == 0.1
    assert heat_drop.main([str(root), jid, "ffffffffffff"]) == 1


READER = Path("/home/gingy/simon-part-7-worktrees/rubric-f/web/heat/heat-data.js")  # the web lane's reader (contract H1)


def test_output_matches_contract_h1_and_parses_with_the_web_readers_rules(api: Api, tmp_path: Path) -> None:
    jid = follow(api)
    _, doc = api.json("GET", f"api/results/{jid}/heat.json")
    _, _, body = api.request("GET", f"api/results/{jid}/heat.bin")
    assert list(doc) == ["format", "vertex_count", "max_m", "frames", "bin", "bin_bytes", "masked_labels"]  # the fixture's keys and order
    assert doc["bin"] == "heat.bin" and "/" not in doc["bin"] and doc["max_m"] > 0
    assert all(list(f) == ["t_ms"] for f in doc["frames"]) and len(body) == len(doc["frames"]) * doc["vertex_count"] == doc["bin_bytes"]
    if not READER.is_file():
        pytest.skip("the web lane's heat-data.js is not on this host")
    import shutil
    import subprocess
    node = shutil.which("node")
    if node is None:
        pytest.skip("node missing")
    (tmp_path / "heat.json").write_text(json.dumps(doc))
    (tmp_path / "heat.bin").write_bytes(body)
    script = (f'import {{parseHeat}} from {json.dumps(READER.as_uri())}; import fs from "node:fs";'
              f'const h=JSON.parse(fs.readFileSync({json.dumps(str(tmp_path / "heat.json"))},"utf8"));'
              f'const b=fs.readFileSync({json.dumps(str(tmp_path / "heat.bin"))});'
              f'const p=parseHeat(h,b.buffer.slice(b.byteOffset,b.byteOffset+b.length),h.vertex_count);'
              f'console.log(JSON.stringify({{n:p.vertexCount,t:p.times.length,m:p.masked.length}}))')
    out = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout) == {"n": doc["vertex_count"], "t": len(doc["frames"]), "m": 4}


def _meta(regions: list[str | None], means: list[float], step_ms: float = 100.0) -> dict[str, Any]:
    """A synthetic heat.meta.json: frame i at i * step_ms, `None` region marks an invalid frame."""
    frames = [{"frame": i, "t_ms": i * step_ms, "valid": r is not None, **({"region": r, "region_mean_m": m} if r else {})}
              for i, (r, m) in enumerate(zip(regions, means))]
    return {"frames": frames}


def test_view_opens_on_part5_lead_fault_not_on_the_hottest_frame() -> None:  # AC-H4 (coordinator ruling 2026-11-02)
    meta = _meta(["left_shin", "right_thigh", "left_forearm", "right_shin"], [0.1, 0.2, 0.05, 0.9])
    analysis = {"faults": [{"measure": "elbow_flexion", "at_s": 0.21, "joints": ["left_elbow"]},
                           {"measure": "knee_flexion", "at_s": 0.3, "joints": ["right_knee"]}]}
    got = heat.open_moment(meta, analysis)
    assert got == {"index": 2, "frame": 2, "t_ms": 200.0, "region": "left_forearm", "source": "fault",
                   "fault": {"measure": "elbow_flexion", "at_s": 0.21, "joints": ["left_elbow"]}}


def _build_with(follower: list, rp: dict[str, Any]) -> dict[str, Any]:
    folder = Path(pytest.importorskip("tempfile").mkdtemp())
    write_pair(folder, follower)
    mesh = heat.read_mesh(json.loads((folder / "mesh3d.json").read_text()), (folder / "mesh3d.bin").read_bytes())
    built = heat.build(mesh, json.loads((folder / "pose3d.json").read_text()), rp)
    assert built is not None
    return built


def test_frames_past_the_aligned_part_are_unaligned_cold_and_never_opened() -> None:  # aligned-part rule (Part 5, 2026-11-02)
    rp = replay([raise_knee(STAND)] * 4)
    rp["exp_to_fol"] = [0, 1, 1, 1]  # the path's last follower frame is 1 (0.1 s): frames 2 and 3 are unaligned
    built = _build_with([STAND] * 4, rp)
    frames, table = built["meta"]["frames"], rows(built)
    assert built["meta"]["aligned_until_s"] == 0.1
    assert [f["valid"] for f in frames] == [True, True, False, False]
    assert [bool(f.get("unaligned")) for f in frames] == [False, False, True, True]
    assert not any(table[2]) and not any(table[3]) and max(table[0]) > 0
    assert built["meta"]["worst"]["index"] in (0, 1)
    late = {"faults": [{"measure": "knee_flexion", "at_s": 0.3, "joints": ["right_knee"]}]}
    got = heat.open_moment(built["meta"], late)  # the fault sits in the unaligned part: frame 1 is the nearest valid one
    assert got is not None and got["index"] == 1 and got["source"] == "fault"
    assert heat.open_moment(built["meta"], {"faults": []})["index"] in (0, 1)


def test_aligned_until_s_wins_over_the_path_when_part5_writes_it() -> None:  # Part 5 1.14.0, TICKET-085
    rp = replay([raise_knee(STAND)] * 4)
    assert heat.aligned_until(rp) == pytest.approx(0.3)  # identity path: every frame aligned
    rp["aligned_until_s"] = 0.2
    assert heat.aligned_until(rp) == 0.2
    frames = _build_with([STAND] * 4, rp)["meta"]["frames"]
    assert [bool(f.get("unaligned")) for f in frames] == [False, False, False, True]
    assert heat.aligned_until({"exp_to_fol": []}) is None


def test_an_old_cached_meta_without_the_aligned_rule_is_rebuilt(api: Api) -> None:
    jid = follow(api)
    assert api.request("GET", f"api/results/{jid}/heat.json")[0] == 200
    meta_p = api.app.queue.job_dir(jid) / "work" / "follower" / "heat" / heat.META
    old = json.loads(meta_p.read_text())
    old.pop("meta_version")
    meta_p.write_text(json.dumps(old))  # a cache written before the aligned-part rule
    assert api.request("GET", f"api/results/{jid}/heat.json")[0] == 200
    assert json.loads(meta_p.read_text())["meta_version"] == heat.META_VERSION


def test_a_fault_with_no_valid_heat_frame_nearby_falls_back_to_heat() -> None:  # AC-H4
    meta = _meta(["left_shin", None, None, None, None, None, "right_shin"], [0.4, 0, 0, 0, 0, 0, 0.1])
    assert heat.nearest_valid(meta, 0.3) is None and heat.nearest_valid(meta, 0.2) == 0
    got = heat.open_moment(meta, {"faults": [{"measure": "x", "at_s": 0.3, "joints": ["left_knee"]}]})
    assert got is not None and got["source"] == "heat" and got["index"] == 0


def test_agreement_tool_keeps_the_measured_tail_rule_and_needs_every_fault_to_match(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # AC-2 rule
    import importlib.util
    spec = importlib.util.spec_from_file_location("heat_agreement", Path(__file__).resolve().parents[2] / "tools" / "heat_agreement.py")
    tool = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(tool)
    folder = tmp_path / "job1" / "work" / "follower" / "heat"
    folder.mkdir(parents=True)
    (folder / heat.META).write_text(json.dumps(_meta(["right_shin"] * 10 + ["left_forearm"] * 2, [0.1] * 12)))
    (folder / "heat.json").write_text("{}")
    (folder.parent / "follower.json").write_text(json.dumps({"duration_s": 1.1}))
    faults = [{"measure": "knee", "at_s": 0.3, "joints": ["right_knee"]}, {"measure": "hip", "at_s": 0.5, "joints": ["right_hip"]},
              {"measure": "arm", "at_s": 1.0, "joints": ["right_elbow"]}]  # 1.0 > 1.1 - 0.5: excluded
    (folder.parent / "analysis.json").write_text(json.dumps({"faults": faults}))
    monkeypatch.setattr(tool.heat, "files", lambda root, job: (folder / "heat.json", folder / "heat.bin"))
    got = tool.check(tmp_path, "job1")
    assert (got["scored"], got["excluded"], got["matched"], got["agrees"], got["lead_fault_match"]) == (2, 1, 2, True, True)
    faults[1]["joints"] = ["left_hip"]
    (folder.parent / "analysis.json").write_text(json.dumps({"faults": faults}))
    assert tool.check(tmp_path, "job1")["agrees"] is False
    (folder.parent / "analysis.json").write_text(json.dumps({"faults": []}))
    assert tool.check(tmp_path, "job1")["agrees"] is False  # no fault: listed as not agreeing, not skipped


# AC-H7: regions from the take's motion (TICKET-332), not from Part 2's nearest-joint label
REGION_POINTS = [  # (point at rest, its nearest-joint label, the region it belongs to); a T-pose, every label right
    ((0.0, 0.25, 0.08), "left_shoulder", "torso"), ((0.0, 0.05, -0.08), "left_hip", "torso"), ((0.0, 0.66, 0.0), "nose", "head"),
    ((0.33, 0.5, 0.04), "left_shoulder", "left_upper_arm"), ((0.62, 0.5, 0.04), "left_elbow", "left_forearm"),
    ((-0.33, 0.5, 0.04), "right_shoulder", "right_upper_arm"), ((-0.62, 0.5, 0.04), "right_elbow", "right_forearm"),
    ((0.1, -0.2, 0.06), "left_hip", "left_thigh"), ((0.1, -0.68, 0.05), "left_knee", "left_shin"),
    ((-0.1, -0.2, 0.06), "right_hip", "right_thigh"), ((-0.1, -0.68, 0.05), "right_knee", "right_shin"),
    ((0.82, 0.5, 0.0), "left_wrist", "left_hand"), ((-0.82, 0.5, 0.0), "right_wrist", "right_hand"),
    ((0.1, -0.94, 0.08), "left_ankle", "left_foot"), ((-0.1, -0.94, 0.08), "right_ankle", "right_foot"),
]
T_POSE = {**STAND, "left_shoulder": (0.2, 0.5, 0), "right_shoulder": (-0.2, 0.5, 0), "left_elbow": (0.47, 0.5, 0),
          "right_elbow": (-0.47, 0.5, 0), "left_wrist": (0.77, 0.5, 0), "right_wrist": (-0.77, 0.5, 0)}


def region_mesh(points: list[tuple[Any, str, str]]) -> heat.Mesh:
    names = list(heat.mesh_files.JOINTS)
    return heat.Mesh(names, [names.index(lab) for _, lab, _ in points], [], [], "")


def test_regions_are_unchanged_where_the_label_rule_was_already_right() -> None:
    # a still take: no motion to tell anything apart, so the regions rest on the T-pose alone, where the labels are right
    frames = [([p for p, _, _ in REGION_POINTS], T_POSE)] * 3
    assert heat.assign_regions(region_mesh(REGION_POINTS), frames) == [r for _, _, r in REGION_POINTS]


def test_a_waist_vertex_beside_a_hanging_forearm_is_torso_once_the_arm_rises() -> None:
    # arms down: the side of the waist is nearest the elbow, so Part 2 labels it left_elbow; the old rule made it arm
    points = [((0.12, 0.15, 0.0), "left_elbow", "torso"), ((0.2, 0.05, 0.03), "left_elbow", "left_forearm"),
              ((0.13, -0.08, 0.06), "left_wrist", "left_thigh")]  # the thigh under a hanging hand: heat, not a masked hand
    raised = {**STAND, "left_elbow": (0.5, 0.5, 0), "left_wrist": (0.8, 0.5, 0)}
    down = [p for p, _, _ in points]
    up = [down[0], (0.65, 0.5, 0.03), down[2]]  # the forearm vertex goes with the forearm; waist and thigh stay
    regions = heat.assign_regions(region_mesh(points), [(down, STAND), (up, raised), (down, STAND)])
    assert regions == [r for _, _, r in points]


def test_a_hand_stays_masked_only_while_it_follows_its_own_arm() -> None:
    points = [((0.2, -0.13, 0.0), "left_wrist", "left_hand")]
    raised = {**STAND, "left_elbow": (0.5, 0.5, 0), "left_wrist": (0.8, 0.5, 0)}
    assert heat.assign_regions(region_mesh(points), [([points[0][0]], STAND), ([(0.87, 0.5, 0.0)], raised)]) == ["left_hand"]
