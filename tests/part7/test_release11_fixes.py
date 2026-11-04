"""Fixes after release 10: an invited board stays out of `has=board`, a person's own score can always leave a board,
reports lose their visitor key, a group take answers only to its maker, Delete my data finds old rows by their takes,
crash inputs answer plainly, a clip with nobody in it is not tracked twice, a converter "no" is asked again soon, and
a zip from a Mac or Windows is not refused for its names."""

from __future__ import annotations

from datetime import timedelta
import json
from pathlib import Path
import time
from typing import Any
import unicodedata
import zipfile

import pytest

from auth_support import authenv, post, sign_in  # noqa: F401  authenv is a fixture
from part7 import auth, catalog_search as cs, challenge_routes, challenges, delete_routes, mail_webhook, model_import
from part7 import model_convert_modal as route, upload_owner
from support import Api, published
from test_challenges import _create, _job
from test_catalog_search import entry, ids, search, seed

pytestmark = pytest.mark.usefixtures("authenv")
ENTRY = "lateral-raise"


def _uid(api: Api, sid: str) -> str:
    return auth.identity(api.app).session_user(sid)


def _store(api: Api, doc: dict[str, Any]) -> None:
    with challenges._locked(api.app.state):
        challenges._write(api.app.state, doc)


# ----- privacy ------------------------------------------------------------------------------------------------
def test_has_board_leaves_out_a_movement_whose_only_board_is_invited(api: Api) -> None:
    seed(api, entry("step-b2", category="dance"), entry("squat-a1"))
    published(api.app.state, "step-b2")
    maker = sign_in(api)
    made = challenges.create(api.app.state, entry_id="step-b2", title="Club", creator_name="Sam", kind="friend", owner=_uid(api, maker))
    _store(api, {**challenges.get(api.app.state, made["id"]), "visibility": "invited"})
    assert ids(search(api, "has=board")[1]) == []  # negative: signed out, nothing says the board is there
    assert ids(search(api, "has=board", cookie=sign_in(api, "grace@example.com"))[1]) == []  # another account
    assert ids(search(api, "has=board", cookie=maker)[1]) == ["step-b2"]  # its maker sees it


def test_an_entrant_off_the_invite_list_can_remove_their_own_score_and_no_one_else(api: Api) -> None:
    maker, entrant, stranger = sign_in(api), sign_in(api, "grace@example.com"), sign_in(api, "dev@example.com")
    cid = _create(api)["id"]
    job = _job(api, "ddddddddddd1")
    auth.identity(api.app).attach(job, _uid(api, entrant), "follow", ENTRY, None, "submit")
    assert post(api, f"api/challenges/{cid}/entries", {"job_id": job, "name": "Grace"}, cookie=entrant)[0] == 201
    _store(api, {**challenges.get(api.app.state, cid), "visibility": "invited", "owner": _uid(api, maker)})
    assert post(api, f"api/challenges/{cid}/remove-my-score", {}, cookie=stranger)[0] == 403  # negative: the gate stands for them
    assert post(api, f"api/challenges/{cid}/close", {}, cookie=entrant)[0] == 403  # negative: only the score, never the board
    status, _, body = post(api, f"api/challenges/{cid}/remove-my-score", {}, cookie=entrant)
    assert status == 200 and body["removed"] == 1
    assert challenges.get(api.app.state, cid)["entries"] == []


def test_the_sweep_takes_the_visitor_key_off_old_reports_only(api: Api) -> None:
    cid = _create(api)["id"]
    now = challenges._now()
    old, new = challenges.stamp(now - timedelta(days=4)), challenges.stamp(now - timedelta(days=1))
    rows = [{"reason": "spam", "visitor": "aaa", "at": old}, {"reason": "spam", "visitor": "bbb", "at": new}, {"reason": "spam", "visitor": "ccc"}]
    _store(api, {**challenges.get(api.app.state, cid), "reports": rows})
    assert challenges.sweep(api.app.state, now)["unkeyed"] == 1
    kept = challenges.get(api.app.state, cid)["reports"]
    assert kept == [{"reason": "spam", "at": old}, {"reason": "spam", "visitor": "bbb", "at": new}, {"reason": "spam"}]
    assert challenges.sweep(api.app.state, now)["unkeyed"] == 0  # nothing left to do: no write


@pytest.mark.parametrize("made,caller,allowed", [
    ("u-maker", "u-maker", True),
    ("u-maker", "u-other", False),  # another account's group take is not there for them
    ("u-maker", None, False),
    ("", None, True),  # made signed out: its id is its key
    (upload_owner.UNKNOWN, "u-maker", False),  # a record without its owner fails closed
    (None, "u-other", True),  # not a group take: nothing changes
])
def test_a_group_take_answers_only_to_the_account_that_made_it(api: Api, monkeypatch: pytest.MonkeyPatch, made: Any, caller: str | None, allowed: bool) -> None:
    h = type("H", (), {"app": api.app})()
    monkeypatch.setattr(challenge_routes.takes_on, "owner", lambda app, job_id: None)
    monkeypatch.setattr(upload_owner, "people_owner", lambda queue, job_id, kinds=(): made)
    monkeypatch.setattr(auth, "current_user", lambda handler: caller)
    if allowed:
        assert challenge_routes._owned_by_caller(h, "ddddddddddd2") is None  # no `owner` on the row either way (S8)
    else:
        with pytest.raises(challenges.ChallengeError) as refused:
            challenge_routes._owned_by_caller(h, "ddddddddddd2")
        assert refused.value.status == 404


def test_forget_account_finds_a_row_with_no_owner_or_poster_by_its_take(api: Api) -> None:
    sid = sign_in(api)
    cid = _create(api)["id"]
    row = {"name": "Crew One", "score": 70, "grade": "C", "job_id": "ddddddddddd3", "pid": "0"}
    other = {"name": "Kim", "score": 60, "grade": "D", "job_id": "ddddddddddd4", "pid": None}
    _store(api, {**challenges.get(api.app.state, cid), "entries": [row, other]})
    delete_routes.forget_account(api.app, _uid(api, sid), ["ddddddddddd3"])
    assert [e["name"] for e in challenges.get(api.app.state, cid)["entries"]] == ["Kim"]


# ----- crashes ------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("raw", ["9" * 5000, "9" * 11, "0" * 5000])
def test_a_page_of_too_many_digits_is_a_plain_refusal(raw: str) -> None:
    with pytest.raises(cs.SearchError):
        cs.parse(f"page={raw}")


def test_leading_zeros_in_range_still_read() -> None:
    assert cs.parse("page=0002").page == 2


@pytest.mark.parametrize("given", ["v1,éé", "☃", "v1,abc ÿ"])
def test_a_non_ascii_signature_is_a_no_not_a_crash(given: str) -> None:
    assert mail_webhook.verify(b"k", "msg", "100", given, b"{}", now=100.0) is False


def test_a_stamp_too_long_to_subtract_is_a_no_not_a_crash() -> None:
    assert mail_webhook.verify(b"k", "msg", "9" * 400, "v1,abc", b"{}", now=100.0) is False


# ----- a clip with nobody in it, and a converter "no" -----------------------------------------------------------
def test_a_converter_no_is_asked_again_within_a_minute_and_a_yes_within_the_hour(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    asked: list[Path] = []
    monkeypatch.setattr(route, "refresh", asked.append)
    spool = tmp_path / "spool"
    spool.mkdir()

    def ready(ok: bool, age: float) -> None:
        (spool / route.READY_FILE).write_text(json.dumps({"ok": ok, "ts": time.time() - age}), encoding="utf-8")

    ready(False, route.RECHECK_NO_S - 30)
    assert route.available(spool) is False and asked == []
    ready(False, route.RECHECK_NO_S + 5)
    assert route.available(spool) is False and asked == [spool]
    asked.clear()
    ready(True, route.RECHECK_NO_S + 5)
    assert route.available(spool) is True and asked == []  # negative: a yes is not asked about every minute
    ready(True, route.RECHECK_S + 5)
    assert route.available(spool) is True and asked == [spool]


# ----- zips ---------------------------------------------------------------------------------------------------
def _zip(tmp_path: Path, files: dict[str, bytes]) -> Path:
    path = tmp_path / "upload.zip"
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return path


def _gltf(*uris: str, **more: Any) -> bytes:
    return json.dumps({"asset": {"version": "2.0"}, "buffers": [{"uri": u} for u in uris], **more}).encode("utf-8")


NFD = unicodedata.normalize("NFD", "café.bin")
NFC = unicodedata.normalize("NFC", "café.bin")


@pytest.mark.parametrize("files", [
    {"a.gltf": _gltf("a.bin", extras={"uri": "../../etc/passwd"}), "a.bin": b"x"},  # no reader follows `extras`
    {"a.gltf": _gltf(NFC), NFD: b"x"},  # a Mac's zip
    {"a.gltf": _gltf("TEX.BIN"), "tex.bin": b"x"},  # Windows' case
    {"a.gltf": _gltf("a.bin"), "a.bin": b"x", "__MACOSX/._a.gltf": b"\x00\x05\x16\x07binary", "._a.gltf": _gltf("../../x")},  # sidecars
])
def test_a_zip_is_not_refused_for_its_names(tmp_path: Path, files: dict[str, bytes]) -> None:
    model_import.check_zip(_zip(tmp_path, files))


@pytest.mark.parametrize("files,message", [
    ({"a.gltf": _gltf("../../etc/passwd")}, model_import.MSG_ZIP_GLTF_MISSING),
    ({"a.gltf": _gltf("TEX.BIN"), "tex.bin": b"x", "Tex.bin": b"y"}, model_import.MSG_ZIP_GLTF_MISSING),  # two loose matches
    ({"a.gltf": json.dumps({"buffers": [{"extras": {}, "uri": "../x"}]}).encode()}, model_import.MSG_ZIP_GLTF_MISSING),
    ({"a.gltf": b'{"buffers":[{"uri":"a.bin","uri":"../x"}]}', "a.bin": b"x"}, model_import.MSG_ZIP_GLTF_MISSING),  # a repeated key
    ({"a.gltf": b'{"buffers":[{"ur\\u0069":"../x"}]}'}, model_import.MSG_ZIP_GLTF_MISSING),  # an escaped key
    ({"a.gltf": _gltf("../x").decode().encode("utf-16")}, model_import.MSG_ZIP_GLTF_MISSING),
    ({"__MACOSX/._a.gltf": b"binary", "._a.gltf": b"binary"}, model_import.MSG_ZIP_NO_GLTF),  # only sidecars
])
def test_a_zip_that_points_outside_is_still_refused(tmp_path: Path, files: dict[str, bytes], message: str) -> None:
    with pytest.raises(model_import.ImportRefused) as refused:
        model_import.check_zip(_zip(tmp_path, files))
    assert refused.value.message == message


def test_a_big_gltf_is_scanned_a_window_at_a_time(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(model_import, "GLTF_PARSE_MAX", 1000)
    monkeypatch.setattr(model_import, "SCAN_WINDOW", 4096)
    monkeypatch.setattr(model_import, "SCAN_OVERLAP", 512)
    pad = "x" * 20_000
    good = json.dumps({"asset": {"pad": pad}, "buffers": [{"uri": "a.bin"}]}).encode()
    model_import.check_zip(_zip(tmp_path, {"a.gltf": good, "a.bin": b"x"}))
    bad = json.dumps({"asset": {"pad": pad}, "buffers": [{"uri": "../outside.bin"}], "more": pad}).encode()
    for raw in (bad, bad.decode().encode("utf-16")):
        with pytest.raises(model_import.ImportRefused):
            model_import.check_zip(_zip(tmp_path, {"a.gltf": raw}))
    astride = b" " * (4096 - 10) + bad  # the key starts just before a window ends
    with pytest.raises(model_import.ImportRefused):
        model_import.check_zip(_zip(tmp_path, {"a.gltf": astride}))


# ----- the converter's own unpacking (Blender is not imported: bpy and mathutils are stood in for) ------------------
@pytest.fixture
def convert(monkeypatch: pytest.MonkeyPatch) -> Any:
    import sys
    import types

    monkeypatch.setitem(sys.modules, "bpy", types.ModuleType("bpy"))
    monkeypatch.setitem(sys.modules, "mathutils", types.ModuleType("mathutils"))
    source = (Path(__file__).parents[2] / "tools" / "model-converter" / "convert.py").read_text(encoding="utf-8")
    mod = types.ModuleType("convert_under_test")
    exec(compile(source.rsplit("\nmain()", 1)[0], "convert.py", "exec"), mod.__dict__)  # the file ends by running itself in Blender
    return mod


def test_the_converter_never_picks_a_sidecar_and_links_loose_names(tmp_path: Path, convert: Any) -> None:
    source = _zip(tmp_path, {"._a.gltf": b"\x00binary", "__MACOSX/._a.gltf": b"\x00binary", "m/a.gltf": _gltf(NFC, "TEX.BIN", "../outside.bin"),
                             f"m/{NFD}": b"one", "m/tex.bin": b"two", "outside.bin": b"three"})
    dest = tmp_path / "out"
    picked = Path(convert.unzip_gltf(str(source), str(dest)))
    assert picked.name == "a.gltf" and picked.parent.name == "m"
    assert (picked.parent / NFC).read_bytes() == b"one" and (picked.parent / "TEX.BIN").read_bytes() == b"two"
    assert (picked.parent / "TEX.BIN").is_symlink()


def test_the_converter_leaves_two_loose_matches_alone(tmp_path: Path, convert: Any) -> None:
    source = _zip(tmp_path, {"a.gltf": _gltf("TEX.BIN"), "tex.bin": b"x", "Tex.bin": b"y"})
    picked = Path(convert.unzip_gltf(str(source), str(tmp_path / "out")))
    assert not (picked.parent / "TEX.BIN").exists()


def test_the_converter_stops_on_a_uri_leaving_the_zip(tmp_path: Path, convert: Any) -> None:
    source = _zip(tmp_path, {"a.gltf": _gltf("../../etc/passwd")})
    with pytest.raises(SystemExit):
        convert.unzip_gltf(str(source), str(tmp_path / "out"))
    assert not (tmp_path / "etc").exists()
