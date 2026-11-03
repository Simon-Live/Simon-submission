"""models-reskin: redo the limb split of generated models already stored (docs/specs/avatar-jobs.md AC-17, TICKET-333).

The orchestration runs with a stand-in for `part2 reskin`; the last test runs the real Part 2 module (modules/part-2)
with Part 2's venv on a synthetic arms-down figure whose left hand is fused to the left thigh, the failure the
operator's generated model had. No copyrighted asset is used."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "fixtures" / "models"))

import glbmaker  # noqa: E402
from part7 import cli, config, model_import, model_reskin, model_store  # noqa: E402

GOOD = glbmaker.humanoid(glbmaker.UE5)
REPORT = {"changed": True, "bridging_triangles_cut": 7, "triangles": 100,
          "stretch": {"before": {"arms": {"max": 20.0}}, "after": {"arms": {"max": 2.7}}}}


@pytest.fixture(autouse=True)
def _part2_sha(monkeypatch):
    """The Part 2 sha the marks record; a test moves it to stand for a Part 2 change."""
    sha = {"now": "part2-sha-1"}
    monkeypatch.setattr(model_reskin, "_part2_sha", lambda: sha["now"])
    return sha


def stored(state: Path, glb: bytes = GOOD, kind: str = "image3d", status: str = "ready", **generated) -> Path:
    """A model as the avatar job leaves it: finalize ran on `glb` with an avatar.json of `kind`."""
    mid, folder = model_store.create(state, "u:owner", status="converting")
    model_store.write_meta(folder, {"name": "Picture model", "kind": "generated", "licence": "personal-use-only",
                                    "format": "webp", "subject": "object"})
    src = folder / "out.glb"
    src.write_bytes(glb)
    extra = {"kind": "generated", "source_kind": kind, "preset": "simon-avatar",
             "avatar": {"schema": "simon.avatar.v1", "kind": kind, **generated}}
    assert model_import.finalize(folder, src, extra) is not None
    if status != "ready":
        model_store.write_status(folder, status=status)
    return folder


def runner(code: int = 0, out: bytes | None = GOOD, report: dict | None = REPORT, calls: list | None = None):
    def run(src: Path, dst: Path) -> tuple[int, str]:
        if calls is not None:
            calls.append((src, dst))
        if out is not None:
            dst.write_bytes(out)
        return code, json.dumps(report) if report is not None else "not json"
    return run


def snapshot(folder: Path) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in sorted(folder.iterdir()) if p.is_file()}


def test_candidates_are_ready_split_models_not_yet_reskinned(tmp_path):
    a = stored(tmp_path, kind="image3d")
    b = stored(tmp_path, kind="autorig")
    stored(tmp_path, kind="image")  # the MHR body avatar: its own skin, never split
    stored(tmp_path, kind="image3d", status="converting")
    stored(tmp_path, kind="image3d", reskin={"at": "earlier"})
    assert {p.name for p in model_reskin.candidates(tmp_path)} == {a.name, b.name}
    assert [p.name for p in model_reskin.candidates(tmp_path, only=a.name)] == [a.name]
    assert model_reskin.candidates(tmp_path / "nothing-here") == []


def test_dry_run_lists_and_writes_nothing(tmp_path):
    folder = stored(tmp_path)
    before, calls = snapshot(folder), []
    rows = model_reskin.run_all(tmp_path, apply=False, run=runner(calls=calls))
    assert rows == [{"id": folder.name, "result": "would reskin"}] and calls == [] and snapshot(folder) == before


def test_apply_installs_the_new_file_records_the_run_and_keeps_the_old(tmp_path):
    folder = stored(tmp_path)
    old = (folder / "model.glb").read_bytes()
    new = glbmaker.humanoid(glbmaker.UE5, unit=0.01)
    assert new != old
    [row] = model_reskin.run_all(tmp_path, apply=True, run=runner(out=new))
    assert row["result"] == "reskinned" and row["bridging_triangles_cut"] == 7
    assert (folder / "model.glb").read_bytes() == new and (folder / model_reskin.BACKUP).read_bytes() == old
    manifest = json.loads((folder / "character.json").read_text())
    assert manifest["file"]["sha256"] == model_import.sha256_of(folder / "model.glb")
    assert manifest["generated"]["reskin"]["bridging_triangles_cut"] == 7 and manifest["generated"]["kind"] == "image3d"
    assert manifest["name"] == "Picture model" and manifest["licence"]["id"] == "personal-use-only"
    assert model_store.read_status(folder)["status"] == "ready" and not (folder / model_reskin.NEW).exists()
    assert model_reskin.candidates(tmp_path) == []  # a second run skips it


@pytest.mark.parametrize("code,out,report", [(2, None, None), (0, GOOD, None), (0, None, REPORT), (1, GOOD, REPORT)])
def test_a_failed_part2_run_leaves_the_model_as_it_was_and_marks_the_refusal(tmp_path, code, out, report):
    folder = stored(tmp_path)
    before = snapshot(folder)
    [row] = model_reskin.run_all(tmp_path, apply=True, run=runner(code=code, out=out, report=report))
    assert row["result"] == "refused"
    assert_refused_only(folder, before, row["why"])


def assert_refused_only(folder, before, why):
    """Review R5: model.glb and status.json as they were; character.json only gains generated.reskin = {refused, why},
    so the next run (every deploy) skips the model."""
    after = snapshot(folder)
    old_bytes, new = before.pop("character.json"), json.loads(after.pop("character.json"))
    mark = new["generated"].pop("reskin")
    assert after == before and mark["why"] == why and mark["refused"] and mark["part2"] == "part2-sha-1"
    # review R2: the rest of the record keeps its bytes (written by the same writer as finalize)
    assert (json.dumps(new, indent=2, sort_keys=True) + "\n").encode() == old_bytes
    assert model_reskin.candidates(folder.parent.parent) == []


def assert_unmarked(folder, before):
    """Review R1: a refusal that may pass next time leaves every file byte for byte as it was."""
    assert snapshot(folder) == before and folder.name in {p.name for p in model_reskin.candidates(folder.parent.parent)}


def test_a_new_file_the_import_check_refuses_is_never_installed(tmp_path):
    folder = stored(tmp_path)
    before = snapshot(folder)
    [row] = model_reskin.run_all(tmp_path, apply=True, run=runner(out=glbmaker.humanoid(glbmaker.UE5, skin=False)))
    assert row["result"] == "refused" and "skeleton" in row["why"]
    assert_refused_only(folder, before, row["why"])


def test_a_finalize_refusal_restores_the_old_file_and_record(tmp_path, monkeypatch):
    folder = stored(tmp_path)
    before = snapshot(folder)

    def refuse(model_dir, glb_path, extra):
        (Path(model_dir) / "model.glb").write_bytes(b"half written")
        model_store.write_status(Path(model_dir), status="failed", error="no")
        return None

    monkeypatch.setattr(model_import, "finalize", refuse)
    [row] = model_reskin.run_all(tmp_path, apply=True, run=runner())
    assert row["result"] == "refused"
    assert snapshot(folder).pop(model_reskin.BACKUP) == before["model.glb"]
    (folder / model_reskin.BACKUP).unlink()
    assert_refused_only(folder, before, row["why"])


def test_restore_puts_the_old_file_back_and_a_later_run_skips_it(tmp_path, capsys):
    folder = stored(tmp_path)
    old = (folder / "model.glb").read_bytes()
    model_reskin.run_all(tmp_path, apply=True, run=runner(out=glbmaker.humanoid(glbmaker.UE5, unit=0.01)))
    assert cli.main(["models-reskin", "--state", str(tmp_path), "--id", folder.name, "--restore"]) == 0
    assert json.loads(capsys.readouterr().out)["result"] == "restored"
    manifest = json.loads((folder / "character.json").read_text())
    assert (folder / "model.glb").read_bytes() == old and not (folder / model_reskin.BACKUP).exists()
    assert manifest["file"]["sha256"] == model_import.sha256_of(folder / "model.glb") and "restored" in manifest["generated"]["reskin"]
    assert model_reskin.candidates(tmp_path) == [] and model_store.read_status(folder)["status"] == "ready"
    assert model_reskin.restore_one(tmp_path, folder.name)["result"] == "refused"  # nothing left to restore
    assert cli.main(["models-reskin", "--state", str(tmp_path), "--restore"]) == 2


def test_an_existing_backup_is_never_overwritten(tmp_path):
    """Review R1: the first original stays the backup."""
    folder = stored(tmp_path)
    (folder / model_reskin.BACKUP).write_bytes(b"the first original")
    model_reskin.run_all(tmp_path, apply=True, run=runner(out=glbmaker.humanoid(glbmaker.UE5, unit=0.01)))
    assert (folder / model_reskin.BACKUP).read_bytes() == b"the first original"
    assert not list(folder.glob("*.tmp")) and not (folder / (model_reskin.NEW + ".old")).exists()


def test_a_second_run_waits_for_nobody_and_writes_nothing_while_the_lock_is_held(tmp_path, capsys):
    """Review R3: one run at a time per state folder."""
    import fcntl

    folder = stored(tmp_path)
    before = snapshot(folder)
    with (tmp_path / model_reskin.LOCK).open("a") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        assert model_reskin.run_all(tmp_path, apply=True, run=runner())[0]["result"] == "busy"
        assert model_reskin.restore(tmp_path, folder.name)["result"] == "busy"
        assert cli.main(["models-reskin", "--state", str(tmp_path), "--apply"]) == 1
    assert snapshot(folder) == before
    assert model_reskin.run_all(tmp_path, apply=True, run=runner())[0]["result"] == "reskinned"


def test_a_model_that_stopped_being_ready_or_errs_is_refused_alone(tmp_path, monkeypatch):
    """Review R4: status is checked again when the model's turn comes; a file error refuses that model only."""
    a, b = stored(tmp_path), stored(tmp_path)
    first, second = sorted([a, b], key=lambda p: p.name)  # the order candidates() gives
    calls = []

    def run(src, dst):
        calls.append(src.parent.name)
        model_store.write_status(second, status="converting")  # re-queued while the first one ran
        raise PermissionError("disk")

    before = {f.name: snapshot(f) for f in (first, second)}
    rows = {r["id"]: r for r in model_reskin.run_all(tmp_path, apply=True, run=run)}
    assert rows[first.name]["result"] == "refused" and "file error" in rows[first.name]["why"]
    assert rows[second.name] == {"id": second.name, "result": "refused", "why": "the model is not ready any more"}
    assert_unmarked(first, before[first.name])  # a file error is never marked
    assert calls == [first.name]
    model_store.write_status(second, status="ready")
    before[second.name]["status.json"] = (second / "status.json").read_bytes()
    assert_unmarked(second, before[second.name])  # nor a model that was not ready


def test_a_timeout_or_a_command_that_cannot_start_is_never_marked(tmp_path):
    """Re-review 3 B2: part2_runner answers NOT_RUN for a timeout or an OSError; the next deploy tries again."""
    folder = stored(tmp_path)
    before = snapshot(folder)
    [row] = model_reskin.run_all(tmp_path, apply=True, run=runner(code=model_reskin.NOT_RUN, out=None, report=None))
    assert row["result"] == "refused" and "timed out" in row["why"]
    assert_unmarked(folder, before)


def test_the_real_runner_answers_not_run_on_a_timeout_and_a_missing_python(tmp_path, monkeypatch):
    venv = tmp_path / "venv"
    (venv / "bin").mkdir(parents=True)
    monkeypatch.setenv("SIMON7_PART2_GPU_VENV", str(venv))
    assert model_reskin.part2_runner(tmp_path / "a.glb", tmp_path / "b.glb") == (model_reskin.NOT_RUN, "")
    (venv / "bin" / "python").write_text("#!/bin/sh\nsleep 5\n")
    (venv / "bin" / "python").chmod(0o755)
    monkeypatch.setattr(model_reskin, "TIMEOUT_S", 0.2)
    assert model_reskin.part2_runner(tmp_path / "a.glb", tmp_path / "b.glb") == (model_reskin.NOT_RUN, "")


def test_a_refusal_is_tried_once_more_after_a_part2_change(tmp_path, _part2_sha):
    """Re-review 3 B2: the mark names the Part 2 that refused; a new Part 2 gets one try, then is marked in turn."""
    folder = stored(tmp_path)
    calls = []
    model_reskin.run_all(tmp_path, apply=True, run=runner(code=2, out=None, report=None, calls=calls))
    assert model_reskin.candidates(tmp_path) == [] and len(calls) == 1
    _part2_sha["now"] = "part2-sha-2"
    assert [p.name for p in model_reskin.candidates(tmp_path)] == [folder.name]
    [row] = model_reskin.run_all(tmp_path, apply=True, run=runner(code=2, out=None, report=None, calls=calls))
    assert row["result"] == "refused" and len(calls) == 2
    mark = json.loads((folder / "character.json").read_text())["generated"]["reskin"]
    assert mark["part2"] == "part2-sha-2" and model_reskin.candidates(tmp_path) == []
    _part2_sha["now"] = "part2-sha-3"
    assert model_reskin.run_all(tmp_path, apply=True, run=runner())[0]["result"] == "reskinned"


def test_a_reskinned_or_restored_model_is_never_tried_again_after_a_part2_change(tmp_path, _part2_sha):
    folder = stored(tmp_path)
    model_reskin.run_all(tmp_path, apply=True, run=runner(out=glbmaker.humanoid(glbmaker.UE5, unit=0.01)))
    _part2_sha["now"] = "part2-sha-2"
    assert model_reskin.candidates(tmp_path) == []
    assert model_reskin.restore(tmp_path, folder.name)["result"] == "restored"
    _part2_sha["now"] = "part2-sha-3"
    assert model_reskin.candidates(tmp_path) == []


def test_cli_exit_codes(tmp_path, capsys):
    stored(tmp_path)
    assert cli.main(["models-reskin", "--state", str(tmp_path)]) == 0
    assert json.loads(capsys.readouterr().out)["result"] == "would reskin"


# ---- the real Part 2 module on a synthetic fused figure --------------------------------------------------------

PART2 = config.REPO_ROOT / "modules" / "part-2"
PY = config.part2_gpu_venv_path() / "bin" / "python"
# Part 2's test module imports pytest for its fixtures; its venv has none, so a stand-in carries the decorators
NO_PYTEST = r'''
import sys, types
deco = lambda *a, **k: (lambda f: f)
sys.modules.setdefault("pytest", types.SimpleNamespace(fixture=deco, approx=None, raises=None,
                                                       mark=types.SimpleNamespace(parametrize=deco, skip=deco)))
'''
MAKE = NO_PYTEST + r'''
from test_autorig_contact import figure, bled_skin, written_glb
v, f, part = figure()
sys.stdout.buffer.write(written_glb(v, f, *bled_skin(v, part)))
'''
MEASURE = NO_PYTEST + r'''
import json
import numpy as np
from part2 import autorig_pose
from test_autorig_contact import figure, ARM, mass, swing, joints_down
from part2.autorig import MHR_INDEX
v, f, part = figure()
rig = autorig_pose.read_rig(open(sys.argv[1], "rb").read())
posed, hand_at = swing(rig)
hand = part == "hand"
off = np.linalg.norm(v[hand] - joints_down()[MHR_INDEX["leftHand"]], axis=1)
print(json.dumps({"hand_lag_m": float(np.abs(np.linalg.norm(posed[hand] - hand_at, axis=1) - off).max()),
                  "thigh_arm": float(mass(rig["idx"], rig["w"], ARM)[part == "thigh"].max()),
                  "triangles": int(len(rig["faces"]))}))
'''


def part2_python(code: str, *args: str) -> subprocess.CompletedProcess[bytes]:
    env = {k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "LANG")}
    env["PYTHONPATH"] = f"{PART2}{os.pathsep}{PART2 / 'tests'}"
    return subprocess.run([str(PY), "-c", code, *args], cwd=PART2, env=env, capture_output=True, timeout=120, check=True)


@pytest.mark.skipif(not (PY.is_file() and (PART2 / "part2" / "autorig_reskin.py").is_file()
                         and (PART2 / "tests" / "test_autorig_contact.py").is_file()),
                    reason="Part 2's venv or its TICKET-058 module is not here")
def test_real_part2_frees_a_hand_fused_to_the_thigh(tmp_path, monkeypatch):
    monkeypatch.setenv("SIMON7_MODULES_DIR", str(PART2.parent))
    fused = part2_python(MAKE).stdout
    folder = stored(tmp_path, glb=fused)
    before = json.loads(part2_python(MEASURE, str(folder / "model.glb")).stdout)
    [row] = model_reskin.run_all(tmp_path, apply=True)
    after = json.loads(part2_python(MEASURE, str(folder / "model.glb")).stdout)
    assert row["result"] == "reskinned", row
    assert before["hand_lag_m"] > 0.05 and after["hand_lag_m"] < 0.01  # the hand follows its arm now
    assert before["thigh_arm"] > 0.3 and after["thigh_arm"] <= 0.05      # and the thigh no longer follows the hand
    assert after["triangles"] < before["triangles"]
    manifest = json.loads((folder / "character.json").read_text())
    assert manifest["counts"]["triangles"] == after["triangles"] and manifest["generated"]["reskin"]["part2"]
