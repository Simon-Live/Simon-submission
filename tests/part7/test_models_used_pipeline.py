"""Models-used rows for SAM 3D Objects, MHR, Muse Glimmer, Muse Image and MMS-TTS (TICKET-300)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from part7 import models_used, muse_fix
from test_models_used import follower, job, rows, trainer, write

JOB = "bbbbbbbbbbb1"
USER = "u" + "1" * 15
OWNER_ONLY = {"image3d", "muse-image", "avatar", "spark-history"}


def setup(tmp_path: Path, **kw: Any) -> Path:
    trainer(tmp_path, "")
    d = job(tmp_path, JOB, **kw.pop("record", {}))
    follower(d, **kw)
    return d


def collect(tmp_path: Path, **kw: Any) -> dict[str, dict[str, Any]]:
    return rows(models_used.collect(tmp_path, JOB, **kw))


def mine(tmp_path: Path) -> dict[str, dict[str, Any]]:
    return collect(tmp_path, state=tmp_path / "state", owner=USER)


def picture_model(state: Path, backend: str = "sam3do", status: str = "ready", model_id: str = "c" * 32) -> None:
    write(state / "models" / model_id / "status.json", {"id": model_id, "status": status, "owner": USER, "created_at": "x"})
    write(state / "models" / model_id / "character.json",
          {"kind": "generated", "generated": {"schema": "simon.avatar.v1", "kind": "image3d", "backend": {"backend": backend}}})


def fix_record(d: Path, status: str, name: str = "run-1-0.json", **extra: Any) -> None:
    write(d / "work" / "muse-fix" / name, {"schema": muse_fix.SCHEMA, "job_id": JOB, "status": status,
                                            "model": "muse-image-1.0", "cost_usd": 0.01, **extra})


def glimmer(faults: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    return {"phrasing": {"requested": "local-llm", "backend": "local-llm", "faults": faults, **extra}}


# ----- SAM 3D Objects: the viewer's picture models -----------------------------------------------------------------
def test_image3d_live_from_a_ready_picture_model_made_by_sam3do(tmp_path: Path) -> None:
    setup(tmp_path)
    picture_model(tmp_path / "state")
    r = mine(tmp_path)["image3d"]
    assert (r["status"], r["model"], r["maker"], r["clip"], r["facts"]["pictures"]) == \
        ("live", "SAM 3D Objects", "Meta", "account", 1)
    av = mine(tmp_path)["avatar"]  # the picture model was rigged by SAM 3D Body on the MHR body
    assert (av["status"], av["facts"]["from_picture"]) == ("live", 1)


def test_image3d_not_run_without_a_ready_picture_model_and_fallback_after_trellis(tmp_path: Path) -> None:
    setup(tmp_path)
    state = tmp_path / "state"
    r = mine(tmp_path)["image3d"]
    assert (r["status"], r["facts"]["reason"]) == ("not_run", "no_picture_model")
    picture_model(state, status="failed")
    assert mine(tmp_path)["image3d"]["status"] == "not_run"
    picture_model(state, backend="trellis", model_id="d" * 32)
    r = mine(tmp_path)["image3d"]
    assert (r["status"], r["facts"]["ran"], r["facts"]["reason"]) == ("fallback", "trellis", "sam3do_unavailable")


# ----- MHR: the rig in the pose provenance --------------------------------------------------------------------------
def test_mhr_live_when_the_pose_provenance_names_the_rig_beside_sam_3d_body(tmp_path: Path) -> None:
    d = setup(tmp_path)
    write(d / "steps" / "part7.log", "x INFO job bbbbbbbbbbb1: part 2 exit 0 in 85.5 s (part2.log)\n")
    r = collect(tmp_path)["mhr-you"]
    assert (r["status"], r["model"], r["clip"], r["seconds"], r["facts"]["frames"]) == ("live", "MHR", "you", 85.5, 1)


def test_mhr_never_live_without_its_record(tmp_path: Path) -> None:
    setup(tmp_path, models=[{"name": "sam-3d-body-dinov3"}])
    assert (collect(tmp_path)["mhr-you"]["status"], collect(tmp_path)["mhr-you"]["facts"]["reason"]) == \
        ("unknown", "no_rig_record")
    setup(tmp_path, models=[{"name": "mhr"}], lifter="motionbert")  # no SAM 3D Body: the rig was not used
    r = collect(tmp_path)["mhr-you"]
    assert (r["status"], r["facts"]["reason"]) == ("not_run", "no_body_model")
    (tmp_path / JOB / "work" / "follower" / "part2" / "pose3d.json").unlink()
    assert collect(tmp_path)["mhr-you"]["status"] == "unknown"


# ----- Muse Glimmer: private wording -------------------------------------------------------------------------------
def test_glimmer_live_when_part5_phrased_with_the_local_glimmer(tmp_path: Path) -> None:
    d = setup(tmp_path, record={"private": True})
    write(d / "work" / "follower" / "analysis.json",
          glimmer([{"backend": "local-llm", "model": "muse-glimmer:30b"}, {"backend": "template", "model": None}],
                  fallback_reason="local-llm: timed out"))
    r = collect(tmp_path)
    g = r["glimmer-phrasing"]
    assert (g["status"], g["model"], g["facts"]["model_id"], g["facts"]["lines_live"], g["facts"]["lines"]) == \
        ("live", "Muse Glimmer", "muse-glimmer:30b", 1, 2)
    assert g["facts"]["reason"] == "local-llm: timed out"
    assert (r["spark-phrasing"]["status"], r["spark-phrasing"]["facts"]["reason"]) == ("not_run", "private_mode")


def test_glimmer_not_live_off_private_mode_or_when_it_fell_back(tmp_path: Path) -> None:
    d = setup(tmp_path)
    r = collect(tmp_path)["glimmer-phrasing"]
    assert (r["status"], r["facts"]["reason"]) == ("not_run", "private_mode_off")
    setup(tmp_path, record={"private": True})  # asked, but Part 7 sent the template plan (no GPU room, no model)
    r = collect(tmp_path)["glimmer-phrasing"]
    assert (r["status"], r["facts"]["ran"], r["facts"]["reason"]) == ("fallback", "template", "private_mode_unavailable")
    analysis = d / "work" / "follower" / "analysis.json"
    write(analysis, glimmer([{"backend": "template"}], fallback_reason="local-llm: unreachable"))
    r = collect(tmp_path)["glimmer-phrasing"]
    assert (r["status"], r["facts"]["ran"], r["facts"]["reason"]) == ("fallback", "template", "local-llm: unreachable")
    write(analysis, glimmer([{"backend": "local-llm", "model": "llama3:8b"}]))
    r = collect(tmp_path)["glimmer-phrasing"]
    assert (r["status"], r["facts"]["ran"], r["facts"]["reason"]) == ("fallback", "llama3:8b", "other_local_model")
    write(analysis, glimmer([]))
    assert collect(tmp_path)["glimmer-phrasing"]["facts"]["reason"] == "no_faults"


# ----- Muse Image: the corrected picture, owner only ---------------------------------------------------------------
def test_muse_image_live_from_the_takes_run_records(tmp_path: Path) -> None:
    d = setup(tmp_path)
    fix_record(d, "shown")
    fix_record(d, "missed", name="run-2-0.json")
    r = mine(tmp_path)["muse-image"]
    assert (r["status"], r["model"], r["clip"], r["facts"]["model_id"], r["facts"]["pictures"], r["facts"]["shown"]) == \
        ("live", "Muse Image", "you", "muse-image-1.0", 2, 1)
    assert "cost_usd" not in json.dumps(r)


def test_muse_image_not_run_without_records_and_fallback_when_every_call_failed(tmp_path: Path) -> None:
    d = setup(tmp_path)
    r = mine(tmp_path)["muse-image"]
    assert (r["status"], r["facts"]["reason"]) == ("not_run", "no_corrected_picture")
    write(d / "work" / "muse-fix" / "run-0-0.json", {"schema": "someone-else", "status": "shown"})
    assert mine(tmp_path)["muse-image"]["status"] == "not_run"
    fix_record(d, "failed", reason="no key")
    r = mine(tmp_path)["muse-image"]
    assert (r["status"], r["facts"]["ran"], r["facts"]["reason"]) == ("fallback", "measured_faults", "no key")


# ----- MMS-TTS: the job's cached spoken lines ----------------------------------------------------------------------
def test_mms_live_from_the_cached_wavs_of_this_job(tmp_path: Path) -> None:
    d = setup(tmp_path)
    write(d / "speech" / "0-eng-0123456789.wav", "RIFF")
    write(d / "speech" / "1-spa-abcdef0123.wav", "RIFF")
    write(d / "speech" / "2-eng-abcdef0123.part.wav", "RIFF")  # a synthesis still running is not a spoken line
    r = collect(tmp_path)["mms-tts"]
    assert (r["status"], r["model"], r["facts"]["spoken"], r["facts"]["languages"]) == ("live", "MMS-TTS", 2, ["eng", "spa"])


def test_mms_not_run_without_a_wav_and_fallback_after_a_logged_failure(tmp_path: Path) -> None:
    d = setup(tmp_path)
    r = collect(tmp_path)["mms-tts"]
    assert (r["status"], r["facts"]["reason"]) == ("not_run", "no_spoken_lines")
    write(d / "speech" / "0-eng-0123456789.wav", "")  # an empty file is no spoken line
    assert collect(tmp_path)["mms-tts"]["status"] == "not_run"
    write(d / "steps" / "part7.log", "x WARNING speech: eng line 0 failed, exit 1: boom\n")
    r = collect(tmp_path)["mms-tts"]
    assert (r["status"], r["facts"]["ran"], r["facts"]["reason"]) == ("fallback", "browser_voice", "speech_failed")


# ----- who sees what, and the order --------------------------------------------------------------------------------
def test_owner_only_rows_are_hidden_from_a_stranger(tmp_path: Path) -> None:
    d = setup(tmp_path)
    picture_model(tmp_path / "state")
    fix_record(d, "shown")
    assert not OWNER_ONLY & set(collect(tmp_path, state=tmp_path / "state"))  # signed out or not the owner
    assert {"mhr-you", "glimmer-phrasing", "mms-tts"} <= set(collect(tmp_path))
    assert OWNER_ONLY <= set(mine(tmp_path))


def test_order_tells_the_pipeline_story(tmp_path: Path) -> None:
    setup(tmp_path)
    order = models_used.ORDER
    assert order.index("image3d") < order.index("avatar") < order.index("sam3d-you") < order.index("mhr-you") \
        < order.index("spark-phrasing") < order.index("mms-tts")
    assert len(set(order)) == len(order)
    ids = [m["id"] for m in models_used.collect(tmp_path, JOB, state=tmp_path / "state", owner=USER)["models"]]
    assert ids == list(order)
