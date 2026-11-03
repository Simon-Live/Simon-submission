"""Models and the account (docs/specs/model-import.md "Delete and export", intake fix 2): deleting one model clears an
account default that named it; "Delete my data" removes every model the person owns, files and spool entries included;
the download of my data lists them."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from auth_support import authenv, get, post, sign_in  # noqa: F401
from part7 import auth, model_store, profile
from support import Api

pytestmark = pytest.mark.usefixtures("authenv")
ADA, GRACE = "Ada.Lovelace@Example.com", "grace@example.com"


def seed_model(api: Api, owner: str, name: str = "Hero") -> str:
    """A ready, generated model with the files an import, a conversion and an avatar job leave, plus spool entries."""
    state = api.app.state
    mid, folder = model_store.create(state, owner, "ready")
    for rel in ("model.glb", "avatar-job.json", "avatar.log", "in/photo.png", "out/model.glb", "convert.log"):
        path = folder / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"data-of-" + mid.encode())
    model_store.write_manifest(folder, {"id": mid, "name": name, "kind": "generated", "licence": {"id": "own-work"}})
    model_store.write_meta(folder, {"name": name, "licence": "own-work"})
    model_store.write_status(folder, bytes=900)
    spool = state / "models-spool"
    for sub in ("queue", "running", "results"):
        (spool / sub).mkdir(parents=True, exist_ok=True)
        (spool / sub / f"{mid}.json").write_text(json.dumps({"id": mid}))
    (spool / "work" / mid / "in").mkdir(parents=True)
    (spool / "work" / mid / "in" / "x.fbx").write_bytes(b"x")
    return mid


def traces(root: Path, mid: str) -> list[Path]:
    """Every path under `root` named for the model or holding its id in its first bytes."""
    return [p for p in root.rglob("*") if mid in p.name or (p.is_file() and mid.encode() in p.read_bytes()[:4096])]


def delete_model(api: Api, mid: str, sid: str) -> int:
    hdr = {"Origin": f"http://127.0.0.1:{api.port}", "Cookie": f"{auth.COOKIE}={sid}"}
    return api.request("DELETE", f"api/models/{mid}", None, hdr)[0]


def test_deleting_the_default_model_clears_the_account_default(api: Api) -> None:
    sid = sign_in(api, ADA)
    store = auth.identity(api.app)
    uid = store.session_user(sid)
    keep, gone = seed_model(api, f"u:{uid}", "Keep"), seed_model(api, f"u:{uid}", "Gone")
    profile.update(store, uid, {"default_model_id": f"up:{gone}"})
    assert get(api, "api/me/profile", sid)[2]["default_model_id"] == f"up:{gone}"
    assert delete_model(api, keep, sid) == 200
    assert get(api, "api/me/profile", sid)[2]["default_model_id"] == f"up:{gone}", "negative: another model's delete leaves it"
    assert delete_model(api, gone, sid) == 200
    assert get(api, "api/me/profile", sid)[2]["default_model_id"] is None
    assert not traces(api.app.state, gone)


def test_delete_my_data_leaves_no_model_file_anywhere(api: Api) -> None:
    ada, grace = sign_in(api, ADA), sign_in(api, GRACE)
    store, state = auth.identity(api.app), api.app.state
    uid_a, uid_g = store.session_user(ada), store.session_user(grace)
    mine = [seed_model(api, f"u:{uid_a}", "One"), seed_model(api, f"u:{uid_a}", "Two")]
    theirs = seed_model(api, f"u:{uid_g}", "Grace")
    profile.update(store, uid_a, {"default_model_id": f"up:{mine[0]}"})
    status, _, body = post(api, "api/me/delete", {"confirm": "delete"}, cookie=ada)
    assert status == 200 and body["deleted"] is True
    for mid in mine:
        assert not (state / "models" / mid).exists()
        assert not traces(state, mid), f"a file or folder of {mid} is left"
    assert model_store.owned(state, f"u:{uid_a}") == []
    assert profile.get_profile(store, uid_a) is None, "the profile, with its default model, is gone"
    # negative: another person's model, folder and spool entries are untouched
    assert (state / "models" / theirs / "model.glb").is_file() and (state / "models-spool" / "queue" / f"{theirs}.json").is_file()


def test_delete_all_raises_when_a_folder_is_left(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    sid = sign_in(api, ADA)
    uid = auth.identity(api.app).session_user(sid)
    seed_model(api, f"u:{uid}")
    monkeypatch.setattr(model_store.shutil, "rmtree", lambda *a, **k: None)
    with pytest.raises(OSError):
        model_store.delete_all(api.app.state, f"u:{uid}")


def test_export_lists_my_models_and_nobody_elses(api: Api) -> None:
    ada, grace = sign_in(api, ADA), sign_in(api, GRACE)
    store = auth.identity(api.app)
    uid_a, uid_g = store.session_user(ada), store.session_user(grace)
    mine = seed_model(api, f"u:{uid_a}", "Hero")
    seed_model(api, f"u:{uid_g}", "Grace only")
    status, _, doc = get(api, "api/me/export", ada)
    assert status == 200
    assert [m["id"] for m in doc["models"]] == [mine]
    row = doc["models"][0]
    assert row["name"] == "Hero" and row["kind"] == "generated" and row["licence"] == "own-work" and row["status"] == "ready"
    assert "owner" not in row and "Grace only" not in json.dumps(doc) and uid_g not in json.dumps(doc)
