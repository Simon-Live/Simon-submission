"""Routes of the home programme and the progress sheet, and its share kind (docs/specs/progress-sheet.md, TICKET-283 AC-2)."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

import pytest

from auth_support import authenv, get, origin, post, sign_in  # noqa: F401
from part7 import auth, history_store, identity, share
from progress_support import ENTRY, job_id, seed, seed_five
from support import Api

pytestmark = pytest.mark.usefixtures("authenv")
GRACE = "grace@example.com"
CATALOG_ENTRY = "lateral-raise"


def _owner(api: Api, email: str | None = None) -> tuple[str, str]:
    sid = sign_in(api, email) if email else sign_in(api)
    db = auth.identity(api.app)
    user = db.session_user(sid)
    db.set_consent(user, "v1", True)
    return sid, user


def _delete(api: Api, path: str, sid: str, same_origin: bool = True) -> tuple[int, Any]:
    hdr = {"Cookie": f"{auth.COOKIE}={sid}", **({"Origin": origin(api), "Content-Type": "application/json"} if same_origin else {})}
    status, _, data = api.request("DELETE", path, b"{}", hdr)
    return status, (json.loads(data) if data else None)


def _sheet_share(api: Api, sid: str) -> dict[str, Any]:
    status, _, doc = post(api, "api/shares", {"kind": "progress_sheet", "item_ref": ENTRY, "confirm": True, "days": 30}, cookie=sid)
    assert status == 201, doc
    return doc


def test_the_owner_reads_the_sheet_signed_out_is_401_and_another_person_404(api: Api) -> None:
    sid, user = _owner(api)
    jobs = seed_five(api.app.state, auth.identity(api.app), user)
    assert get(api, f"api/me/progress/{ENTRY}")[0] == 401
    status, _, doc = get(api, f"api/me/progress/{ENTRY}", cookie=sid)
    assert status == 200 and doc["sessions"] == 5 and [t["job_id"] for t in doc["takes"]] == jobs
    other, _ = _owner(api, GRACE)
    assert get(api, f"api/me/progress/{ENTRY}", cookie=other)[0] == 404
    assert get(api, "api/me/progress/..%2Fx", cookie=sid)[0] == 404
    assert post(api, f"api/me/progress/{ENTRY}", {}, cookie=sid)[0] == 405


def test_a_shared_sheet_holds_no_id_and_no_video_and_delete_removes_it(api: Api) -> None:
    sid, user = _owner(api)
    jobs = seed_five(api.app.state, auth.identity(api.app), user)
    made = _sheet_share(api, sid)
    assert made["id"] == share.token_hash(made["token"])
    status, _, snap = get(api, f"api/shared/{made['token']}")
    assert status == 200 and snap["kind"] == "progress_sheet" and snap["sessions"] == 5 and snap["clip"] is None
    text = json.dumps(snap)
    assert all(j not in text for j in jobs) and user not in text and ".mp4" not in text and "video" not in text
    assert "entry_id" not in snap and "job_id" not in text  # the title is the entry's name (here its id, the test catalog has no name)
    assert get(api, f"api/shared/{made['token']}/clip.mp4")[0] == 404  # the clip route never serves a sheet
    other, _ = _owner(api, GRACE)
    assert _delete(api, f"api/me/shares/{made['id']}", other)[0] == 404  # another person's sheet
    assert _delete(api, f"api/me/shares/{made['id']}", sid, same_origin=False)[0] == 403  # CSRF
    assert _delete(api, f"api/me/shares/{made['id']}", sid) == (200, {"revoked": True})
    assert get(api, f"api/shared/{made['token']}")[0] == 404
    rows = auth.identity(api.app).fetch("SELECT COUNT(*) AS n FROM shares WHERE token_hash = ?", (made["id"],))
    assert rows[0]["n"] == 0  # the stored copy is deleted, not only revoked


def test_no_sheet_to_share_is_404_and_the_preview_matches(api: Api) -> None:
    sid, user = _owner(api)
    body = {"kind": "progress_sheet", "item_ref": ENTRY, "confirm": True, "days": 30}
    status, _, doc = post(api, "api/shares", body, cookie=sid)
    assert status == 404 and doc["message"] == "There are no measured sessions to share yet."
    seed_five(api.app.state, auth.identity(api.app), user)
    preview = post(api, "api/shares/preview", body, cookie=sid)[2]
    assert preview["kind"] == "progress_sheet" and preview["sessions"] == 5 and preview["clip"] is None


def test_forgetting_the_movement_deleting_a_take_or_withdrawing_retention_deletes_the_sheet(api: Api) -> None:
    sid, user = _owner(api)
    db = auth.identity(api.app)
    seed_five(api.app.state, db, user)
    count = lambda: db.fetch("SELECT COUNT(*) AS n FROM shares WHERE kind = 'progress_sheet'")[0]["n"]  # noqa: E731
    _sheet_share(api, sid)
    assert _delete(api, f"api/me/history/{ENTRY}", sid)[0] == 200 and count() == 0
    for n, day in enumerate(("2026-11-01", "2026-11-02")):
        assert seed(api.app.state, db, user, job_id(0xB00 + n), day)
    _sheet_share(api, sid)
    db.forget_job(job_id(0xB00))
    assert count() == 0
    _sheet_share(api, sid)
    assert post(api, "api/me/consent", {"retention": False, "version": "v1"}, cookie=sid)[0] == 200 and count() == 0


def test_an_old_shares_table_is_widened_once_after_a_backup(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    sign_in(api)
    db = auth.identity(api.app)
    old = share._TABLE.format(name="shares").replace(", 'progress_sheet'", "")
    db.write(old.strip())
    db.write("INSERT INTO shares (token_hash, owner_id, kind, item_ref, snapshot, created_utc, expires_utc) VALUES "
             "('a', 'u', 'take_result', 'j', '{}', '2026-11-01T00:00:00Z', '2099-01-01T00:00:00Z')")
    monkeypatch.setattr(identity.IdentityStore, "backup_to", lambda self, target: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(share.ShareError) as refused:
        share.ensure_schema(db)
    assert refused.value.status == 503 and not share._takes_sheets(db)  # no copy, no migration
    monkeypatch.undo()
    share.ensure_schema(db)
    backup = identity.db_path(api.app.state).with_name("identity.db.pre-progress-sheet")
    old_sql = sqlite3.connect(backup).execute("SELECT sql FROM sqlite_master WHERE name = 'shares'").fetchone()[0]
    assert "progress_sheet" not in old_sql and (backup.stat().st_mode & 0o777) == 0o600
    assert share._takes_sheets(db) and db.fetch("SELECT kind FROM shares")[0]["kind"] == "take_result"
    assert {r["name"] for r in db.fetch("SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = 'shares'")} >= {"shares_owner", "shares_item"}
    share.ensure_schema(db)  # again: nothing changes
    assert db.fetch("SELECT COUNT(*) AS n FROM shares")[0]["n"] == 1


def test_programme_routes_are_public_to_read_and_owner_only_to_change(api: Api) -> None:
    sid, user = _owner(api)
    other, _ = _owner(api, GRACE)
    auth.identity(api.app).attach_entry(ENTRY, user)
    assert len(get(api, "api/programmes")[2]["measures"]) == 13
    assert get(api, f"api/programmes/{ENTRY}")[0] == 404
    body = {"primary_measure": "left_knee_flexion"}
    assert post(api, f"api/programmes/{ENTRY}", body)[0] == 401
    assert post(api, f"api/programmes/{ENTRY}", body, cookie=other)[0] == 404
    assert post(api, f"api/programmes/{ENTRY}", body, cookie=sid, guard=False)[0] == 403
    assert post(api, f"api/programmes/{ENTRY}", {"primary_measure": "nose"}, cookie=sid)[0] == 400
    status, _, doc = post(api, f"api/programmes/{ENTRY}", body, cookie=sid)
    assert status == 200 and doc["label"] == "left knee bend"
    assert get(api, f"api/programmes/{ENTRY}")[2]["primary_measure"] == "left_knee_flexion"  # signed out can read it
    assert _delete(api, f"api/programmes/{ENTRY}", other)[0] == 404
    assert _delete(api, f"api/programmes/{ENTRY}", sid, same_origin=False)[0] == 403
    assert _delete(api, f"api/programmes/{ENTRY}", sid) == (200, {"removed": True})
    assert get(api, f"api/programmes/{ENTRY}")[0] == 404 and history_store.entries(api.app.state, user) == []


def test_the_trainer_form_saves_with_put_and_only_for_the_owner(api: Api) -> None:
    """An entry the test catalog holds, so the teacher page (where the form mounts) answers."""
    sid, user = _owner(api)
    other, _ = _owner(api, GRACE)
    auth.identity(api.app).attach_entry(CATALOG_ENTRY, user)

    def put(cookie: str | None, body: dict[str, Any], same_origin: bool = True) -> int:
        hdr = {"Content-Type": "application/json", **({"Origin": origin(api)} if same_origin else {}), **({"Cookie": f"{auth.COOKIE}={cookie}"} if cookie else {})}
        return api.request("PUT", f"api/programmes/{CATALOG_ENTRY}", json.dumps(body).encode(), hdr)[0]

    body = {"primary_measure": "right_knee_flexion"}
    assert put(None, body) == 401 and put(other, body) == 404 and put(sid, body, same_origin=False) == 403
    assert put(sid, {"primary_measure": "nose"}) == 400 and get(api, f"api/programmes/{CATALOG_ENTRY}")[0] == 404
    assert put(sid, body) == 200 and get(api, f"api/programmes/{CATALOG_ENTRY}")[2]["label"] == "right knee bend"
    status, _, doc = get(api, f"api/teacher/{CATALOG_ENTRY}", cookie=sid)
    assert status == 200 and doc["attribution"]["mine"] is True  # the page the form mounts on says mine to the owner
    assert get(api, f"api/teacher/{CATALOG_ENTRY}", cookie=other)[2]["attribution"]["mine"] is False
