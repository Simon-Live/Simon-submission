"""serverless-compute.md AC-SC20: a model made from a picture runs on the operator's Modal workspace, never on this machine,
counted and capped as a take is. Part 2 is replaced at `_run_part2`; the client has its own tests in test_serverless_client.py."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from part7 import auth, avatar_jobs as aj, model_import, modules, picture_kind, prod_mode, quota, serverless_route

ROOT = Path(__file__).resolve().parents[2]
JPEG = b"\xff\xd8\xff\xe0" + b"\0" * 64


@pytest.fixture
def mode(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setenv("SIMON7_COMPUTE", "serverless")
    monkeypatch.setenv("SIMON7_SERVERLESS_IMAGE3D", "1")
    monkeypatch.delenv("FIRM_ENV", raising=False)
    monkeypatch.setattr(aj, "CHECK_HOLD_S", 0)
    monkeypatch.setattr(modules, "load", lambda: SimpleNamespace(sha=lambda part: "c" * 40))
    return tmp_path


def queued(root: Path, kind: str = "image") -> Path:
    folder = root / "models" / "m1"
    (folder / "in").mkdir(parents=True)
    (folder / "in" / "image-1.jpg").write_bytes(JPEG)
    (folder / aj.JOB_FILE).write_text(json.dumps({"kind": kind, "inputs": ["image-1.jpg"], "owner": "u:a"}))
    (folder / aj.STATUS_FILE).write_text(json.dumps({"id": "m1", "status": "queued", "owner": "u:a"}))
    return folder


def status(folder: Path) -> dict:
    return json.loads((folder / aj.STATUS_FILE).read_text())


def run_part2_stub(monkeypatch: pytest.MonkeyPatch, code: int, seen: list | None = None) -> None:
    def fake(argv: list[str], cwd: Path, env: dict, model_dir: Path, timeout_s: float) -> int:
        if seen is not None:
            seen.append(argv)
        if code == 0:
            out = model_dir / "out"
            out.mkdir()
            (out / "model.glb").write_bytes(b"glTF")
            kind = argv[argv.index("--") + 1]
            (out / "avatar.json").write_text(json.dumps({"schema": aj.AVATAR_SCHEMA, "kind": {"avatar": "image"}.get(kind, kind)}))
        return code

    monkeypatch.setattr(aj, "_run_part2", fake)


def test_photo_picture_and_mesh_are_all_offered(mode: Path) -> None:
    assert aj.available("image") and aj.available("image3d") and aj.available("autorig")
    assert model_import._generator("image") is aj and model_import._generator("image3d") is aj
    assert model_import._generator("autorig") is aj


def test_the_client_sends_a_mesh_to_the_volume_as_it_sends_a_photo() -> None:
    spec = importlib.util.spec_from_file_location("p2_client_test", aj.config.REPO_ROOT / "deploy/serverless/p2_client.py")
    client = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(client)
    argv, files, out = client._store_files(["autorig", "--out", "/w/out", "/w/in/upload.glb"])
    assert argv == ["autorig", "--out", "{out}", "{in}/upload.glb"] and files == {"upload.glb": Path("/w/in/upload.glb")}
    assert out == Path("/w/out")


def test_an_unrigged_glb_counts_as_a_job(mode: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list = []
    monkeypatch.setattr(model_import, "read_report", lambda path: SimpleNamespace(has_skin=False))
    monkeypatch.setattr(model_import, "_dispatch_counted", lambda *a: seen.append(a))
    folder = queued(mode)
    model_import._dispatch_glb(object(), folder, "m1", folder / "in" / "image-1.jpg", {})
    assert len(seen) == 1, "a mesh takes the counted road, as a photo does"


def test_a_rig_after_a_conversion_counts_and_no_count_refuses_it(mode: Path) -> None:
    folder = queued(mode)
    assert model_import._count_rig(folder) is None
    assert quota.Quota(mode).gpu_jobs_today() == 1


def test_a_picture_is_refused_until_its_app_is_switched_on(mode: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIMON7_SERVERLESS_IMAGE3D", "0")
    assert aj.available("image") and not aj.available("image3d") and model_import._generator("image3d") is None
    assert picture_kind.intake("/api/models?kind=object", "jpeg", {}, 10, 100, lambda: None)[1] == (415, picture_kind.MSG_UNAVAILABLE)


def test_outside_serverless_nothing_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SIMON7_COMPUTE", raising=False)
    assert not aj.on_modal("image") and not aj.on_modal("image3d")


@pytest.mark.parametrize("kind, sub", [("image", "avatar"), ("image3d", "image3d"), ("autorig", "autorig")])
def test_a_job_calls_modal_and_starts_nothing_here(mode: Path, monkeypatch: pytest.MonkeyPatch, kind: str, sub: str) -> None:
    seen: list[list[str]] = []
    run_part2_stub(monkeypatch, 0, seen)
    finished: list = []
    monkeypatch.setattr(aj, "_finalize_fn", lambda: lambda folder, glb, extra: finished.append(extra) or {"ok": True})
    folder = queued(mode, kind)
    aj._run_job(folder)
    argv = seen[0]
    assert "--serverless" in argv and "--secrets-dir" in argv and str(aj.config.REPO_ROOT / "deploy/serverless/p2_client.py") in argv
    assert argv[argv.index("--") + 1:argv.index("--") + 3] == [sub, "--out"] and argv[argv.index("--job") + 1] == "m1"
    assert argv[-1].endswith("image-1.jpg") and "c" * 40 in argv
    assert finished[0]["source_kind"] == kind and status(folder)["status"] == "ready"
    assert not (folder / "in").exists(), "the photo goes on every end"


@pytest.mark.parametrize("code, message", [(serverless_route.BUSY_EXIT, aj.MSG_SERVERLESS_BUSY), (serverless_route.STOPPED_EXIT, aj.MSG_SERVERLESS_STOPPED),
                                           (3, aj.MSG_NO_PERSON["image"])])
def test_a_call_that_fails_says_why_and_removes_the_photo(mode: Path, monkeypatch: pytest.MonkeyPatch, code: int, message: str) -> None:
    run_part2_stub(monkeypatch, code)
    folder = queued(mode)
    aj._run_job(folder)
    assert status(folder)["status"] == "failed" and status(folder)["error"] == message and not (folder / "in").exists()


def test_a_busy_container_is_not_tried_again_on_the_operators_money(mode: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list = []
    run_part2_stub(monkeypatch, 4, seen)
    aj._run_job(queued(mode))
    assert len(seen) == 1


def test_a_deleted_model_ends_its_call(mode: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(aj, "FOLLOW_S", 0.01)
    ended = []
    folder = queued(mode)
    with aj._cond:
        aj._proc = SimpleNamespace(terminate=lambda: ended.append(True))  # type: ignore[assignment]
    try:
        with aj._following_call(folder):
            (folder / aj.STATUS_FILE).unlink()
            aj.time.sleep(0.2)
    finally:
        with aj._cond:
            aj._proc = None
    assert ended == [True]


def test_the_call_state_moves_the_status_from_waiting_to_making(mode: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(aj, "FOLLOW_S", 0.01)
    folder = queued(mode)
    (folder / "steps").mkdir()
    path = folder / "steps" / serverless_route.STATUS_FILE
    with aj._following_call(folder):
        path.write_text(json.dumps({"state": "queued"}))
        aj.time.sleep(0.1)
        assert status(folder)["waiting"] == aj.MSG_WAITING_GPU
        path.write_text(json.dumps({"state": "running"}))
        aj.time.sleep(0.1)
        assert status(folder)["status"] == "converting" and status(folder)["step"] == "making"


def test_a_job_a_restart_left_queued_runs_again_with_no_new_count(mode: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list = []
    monkeypatch.setattr(aj, "_submit", lambda kind, folder, files, owner: seen.append(kind))
    assert aj._requeue(queued(mode, "image3d")) is True and seen == ["image3d"]


def handler(root: Path) -> SimpleNamespace:
    made = []
    h = SimpleNamespace(app=SimpleNamespace(state=root, quota=quota.Quota(root)), _visitor=lambda: "198.51.100.7",
                        _json=lambda status, doc: made.append((status, doc)), _error=lambda status, msg, **kw: made.append((status, msg)))
    h.made = made
    return h


def count_job(root: Path, h: SimpleNamespace) -> None:
    folder = root / "models" / f"m{len(list((root / 'models').glob('*'))) if (root / 'models').is_dir() else 0}"
    (folder / "in").mkdir(parents=True)
    (folder / aj.STATUS_FILE).write_text(json.dumps({"id": folder.name, "status": "queued", "owner": "u:a"}))
    model_import._dispatch_counted(h, folder, folder.name, lambda: None)


def test_the_stop_switch_stops_a_model_too(mode: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth, "current_user", lambda h: "a")
    h = handler(mode)
    (mode / quota.STOP_FILE).write_text("")
    with pytest.raises(model_import.ImportRefused) as err:
        count_job(mode, h)
    assert err.value.message == quota.STOPPED_MESSAGE


def test_a_job_that_never_starts_gives_its_count_back(mode: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth, "current_user", lambda h: "a")
    h = handler(mode)
    folder = mode / "models" / "m1"
    (folder / "in").mkdir(parents=True)
    (folder / aj.STATUS_FILE).write_text(json.dumps({"id": "m1", "status": "queued", "owner": "u:a"}))

    def refuse() -> None:
        raise aj.QueueFull(aj.MSG_QUEUE_FULL)

    model_import._dispatch_counted(h, folder, "m1", refuse)
    assert h.made[0] == (429, aj.MSG_QUEUE_FULL) and h.app.quota.gpu_jobs_today() == 0


def test_a_real_person_cannot_pass_as_an_object_while_face_copy_is_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(prod_mode, "policy", lambda name: False)
    gen = lambda: object()  # noqa: E731
    for answer in ("self", "consented"):
        subject, refusal = picture_kind.intake("/api/models?kind=object", "jpeg", {"consent": answer}, 10, 100, gen)
        assert subject == picture_kind.OBJECT and refusal == (403, picture_kind.MSG_REAL_PERSON_OFF)
    assert picture_kind.field_of(picture_kind.MSG_REAL_PERSON_OFF) == "consent"
    assert picture_kind.intake("/api/models?kind=object", "jpeg", {"consent": "fiction"}, 10, 100, gen)[1] is None
    assert picture_kind.intake("/api/models?kind=object", "jpeg", {}, 10, 100, gen)[1] is None, "the question comes next"


def test_the_picture_app_runs_one_command_on_one_backend_at_one_container() -> None:
    source = (ROOT / "deploy/serverless/image3d_app.py").read_text(encoding="utf-8")
    assert "max_containers=1" in source and 'BACKEND = "image3d", "sam3do"' in source
    assert 'argv[:1] != [SUBCOMMAND] or "--backend" in argv' in source
    assert "jetjodh/sam-3d-objects" in source and "f29e43c151f2d1a390ce560fa4e439ede44ee801" in source
    assert "libegl1" in source, "TICKET-391: the first real build failed on libEGL.so.1 when SAM 3D Objects loaded"
