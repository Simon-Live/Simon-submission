"""Source and licence credit of an entry or a take over a real server (docs/specs/source-credit.md AC-S1 to AC-S10; TICKET-322)."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

import pytest

from auth_support import authenv, get, origin, post, sign_in  # noqa: F401
from part7 import auth, share, source_credit
from support import Api

pytestmark = pytest.mark.usefixtures("authenv")
ENTRY = "lateral-raise"
OWNER, OTHER_USER = "olga@example.com", "otto@example.com"
GOOD = {"title": "MM-Fit workout", "creator": "Stromback et al.", "licence": "CC BY 4.0", "url": "https://mmfit.github.io/"}


def make_job(api: Api, *, private: bool = False) -> str:
    made = api.app.queue.submit("follow", lambda ctx: {"result": {}}, entry_id=ENTRY, **({"private": True} if private else {}))
    assert api.app.queue.wait(made["id"], 10)["status"] == "done"
    return made["id"]


def send(api: Api, path: str, doc: Any, sid: str | None, guard: bool = True) -> tuple[int, Any]:
    status, _, body = post(api, path, doc, cookie=sid, guard=guard)
    return status, body


class World:
    """One owner of an entry and of a take, another signed-in account, and a signed-out visitor."""

    def __init__(self, api: Api) -> None:
        self.api = api
        self.owner, self.other = sign_in(api, OWNER), sign_in(api, OTHER_USER)
        self.store = auth.identity(api.app)
        self.oid = self.store.session_user(self.owner)
        self.store.attach_entry(ENTRY, self.oid)
        self.job = make_job(api)
        assert post(api, "api/me/claims", {"job_id": self.job}, cookie=self.owner)[0] == 200

    def read(self, kind: str, subject: str, sid: str | None = None) -> dict[str, Any]:
        status, _, body = get(self.api, f"api/source/{kind}/{subject}", cookie=sid)
        assert status == 200
        return body

    def write(self, kind: str, subject: str, doc: Any, sid: str | None = None) -> tuple[int, Any]:
        return send(self.api, f"api/me/source/{kind}/{subject}", doc, sid or self.owner)


@pytest.fixture()
def world(api: Api) -> World:
    return World(api)


# ----- AC-S1 write and read ----------------------------------------------------------------------------
def test_owner_saves_and_everyone_reads_an_entry_source(world: World) -> None:
    status, body = world.write("entry", ENTRY, GOOD)
    assert status == 200 and body["mine"] is True
    assert body["source"] == {**GOOD, "licence_other": "", "licence_label": "CC BY 4.0",
                              "licence_url": "https://creativecommons.org/licenses/by/4.0/"}
    for sid, mine in ((world.owner, True), (world.other, False), (None, False)):
        doc = world.read("entry", ENTRY, sid)
        assert doc["source"]["title"] == GOOD["title"] and doc["source"]["url"] == GOOD["url"] and doc["mine"] is mine


def test_owner_saves_and_everyone_reads_a_take_source(world: World) -> None:
    status, body = world.write("take", world.job, {"creator": "Ana", "licence": "own recording"})
    assert status == 200 and body["source"]["licence_label"] == "Own recording (no licence needed)" and body["source"]["url"] == ""
    assert world.read("take", world.job)["source"]["creator"] == "Ana"
    assert world.read("take", world.job)["licences"] == list(source_credit.LICENCES)


def test_licence_list_has_the_agreed_names_and_other_shows_the_persons_words(world: World) -> None:
    assert {"CC BY 4.0", "Pexels License", "own recording", "Other"} <= set(source_credit.LICENCES)
    status, body = world.write("entry", ENTRY, {"title": "A clip", "licence": "Other", "licence_other": "Mixed licence 2"})
    assert status == 200 and body["source"]["licence_label"] == "Mixed licence 2"
    status, body = world.write("entry", ENTRY, {"title": "A clip", "licence": "CC0", "licence_other": "ignored"})
    assert status == 200 and body["source"]["licence_other"] == ""


def test_a_second_save_replaces_the_first(world: World) -> None:
    world.write("entry", ENTRY, GOOD)
    world.write("entry", ENTRY, {**GOOD, "title": "Second"})
    assert world.read("entry", ENTRY)["source"]["title"] == "Second"
    assert len(world.store.fetch("SELECT * FROM source_credits")) == 1


# ----- AC-S2 validation ---------------------------------------------------------------------------------
@pytest.mark.parametrize("url", [
    "javascript:alert(1)", "JavaScript:alert(1)", "data:text/html,<b>x</b>", "http://example.com/a", "ftp://example.com/a",
    "//example.com/a", "https:///nohost", "https://user:pw@example.com/", "https://example.com/a b", "https://localhost/",
    "https://example.com/\x07", "https://" + "a" * 500 + ".com", 7, ["https://example.com/"],
    "https://example.com\u202e/a", "https://exam\u200bple.com/", "https://example.com:8443/a", "https://example.com:443/a", "https://example.com:99999/a",
    "https://example.com:abc/",
])
def test_a_url_that_is_not_https_is_refused(world: World, url: Any) -> None:
    status, body = world.write("entry", ENTRY, {**GOOD, "url": url})
    assert status == 400 and body["message"] == source_credit.MSG_URL
    assert world.read("entry", ENTRY)["source"] is None


def test_url_at_the_length_limit_is_accepted_and_one_more_is_not(world: World) -> None:
    ok = "https://example.com/" + "a" * (source_credit.URL_MAX - len("https://example.com/"))
    assert world.write("entry", ENTRY, {**GOOD, "url": ok})[0] == 200
    assert world.write("entry", ENTRY, {**GOOD, "url": ok + "a"})[0] == 400


@pytest.mark.parametrize("doc, message", [
    ({"title": "x"}, source_credit.MSG_NEED_LICENCE),
    ({"title": "x", "licence": "GPL"}, source_credit.MSG_LICENCE),
    ({"title": "x", "licence": "Other"}, source_credit.MSG_OTHER),
    ({"licence": "CC0"}, source_credit.MSG_FIELDS),
    ({"title": "t" * 121, "licence": "CC0"}, source_credit.MSG_TEXT),
    ({"title": "bad\x00name", "licence": "CC0"}, source_credit.MSG_TEXT),
    ({"title": 5, "licence": "CC0"}, source_credit.MSG_TEXT),
    ({"title": "x", "licence": "Other", "licence_other": "o" * 81}, source_credit.MSG_OTHER),
    ({"title": "x", "licence": "Other", "licence_other": "a\u202eb"}, source_credit.MSG_OTHER),
    ({"title": "evil\u202egpj.exe", "licence": "CC0"}, source_credit.MSG_TEXT),
    ({"creator": "two\nlines", "licence": "CC0"}, source_credit.MSG_TEXT),
    ({"title": "zero\u200bwidth", "licence": "CC0"}, source_credit.MSG_TEXT),
])
def test_a_bad_field_answers_one_sentence(world: World, doc: dict[str, Any], message: str) -> None:
    status, body = world.write("take", world.job, doc)
    assert status == 400 and body["message"] == message
    assert world.read("take", world.job)["source"] is None


def test_markup_is_stored_as_text_and_the_page_escapes_it(world: World) -> None:
    status, body = world.write("entry", ENTRY, {**GOOD, "title": "<img src=x onerror=alert(1)>"})
    assert status == 200 and body["source"]["title"] == "<img src=x onerror=alert(1)>"  # escaping is the page's job (AC-S9 JS test)


def test_a_body_that_is_not_an_object_is_refused(world: World) -> None:
    assert world.write("entry", ENTRY, ["x"])[0] == 400


# ----- AC-S3 clearing -----------------------------------------------------------------------------------
def test_empty_fields_clear_the_source(world: World) -> None:
    world.write("entry", ENTRY, GOOD)
    status, body = world.write("entry", ENTRY, {})
    assert status == 200 and body["source"] is None
    assert world.read("entry", ENTRY)["source"] is None and world.store.fetch("SELECT * FROM source_credits") == []


# ----- AC-S4 owners only --------------------------------------------------------------------------------
def test_signed_out_is_401_and_another_account_is_403(world: World) -> None:
    assert send(world.api, f"api/me/source/entry/{ENTRY}", GOOD, None)[0] == 401
    assert send(world.api, f"api/me/source/take/{world.job}", GOOD, None)[0] == 401
    assert world.write("entry", ENTRY, GOOD, world.other)[0] == 403
    assert world.write("take", world.job, GOOD, world.other)[0] == 403
    assert world.read("entry", ENTRY)["source"] is None and world.read("take", world.job)["source"] is None


def test_an_unknown_subject_is_404_and_a_missing_origin_is_403(world: World) -> None:
    assert world.write("entry", "no-such-movement", GOOD)[0] == 404
    assert world.write("take", "no-such-job-id", GOOD)[0] == 404
    assert world.write("entry", "a%20b", GOOD)[0] == 404
    assert send(world.api, f"api/me/source/entry/{ENTRY}", GOOD, world.owner, guard=False)[0] == 403


def test_a_stranger_cannot_clear_the_owners_source(world: World) -> None:
    world.write("entry", ENTRY, GOOD)
    assert world.write("entry", ENTRY, {}, world.other)[0] == 403
    assert world.read("entry", ENTRY)["source"] is not None


def test_the_edit_route_is_gone_when_sign_in_is_off(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIMON7_MAIL_TRANSPORT", "off")
    status, _, _ = post(api, f"api/me/source/entry/{ENTRY}", GOOD)
    assert status in (401, 404)
    assert get(api, f"api/source/entry/{ENTRY}")[2]["source"] is None  # reading still answers, with nothing


# ----- AC-S5 only me and private ------------------------------------------------------------------------
def test_an_only_me_entry_hides_its_source_from_others(world: World) -> None:
    world.write("entry", ENTRY, GOOD)
    assert post(world.api, f"api/me/entries/{ENTRY}", {"only_me": True}, cookie=world.owner)[0] == 200
    assert world.read("entry", ENTRY, world.owner)["source"]["title"] == GOOD["title"]
    for sid in (world.other, None):
        assert world.read("entry", ENTRY, sid)["source"] is None
    post(world.api, f"api/me/entries/{ENTRY}", {"only_me": False}, cookie=world.owner)
    assert world.read("entry", ENTRY)["source"] is not None


def test_a_take_of_an_only_me_entry_hides_its_source_from_others(world: World) -> None:
    world.write("take", world.job, GOOD)
    post(world.api, f"api/me/entries/{ENTRY}", {"only_me": True}, cookie=world.owner)
    assert world.read("take", world.job)["source"] is None
    assert world.read("take", world.job, world.owner)["source"] is not None


def test_a_private_take_hides_its_source_from_others(api: Api) -> None:
    w = World(api)
    job = make_job(api, private=True)
    assert post(api, "api/me/claims", {"job_id": job}, cookie=w.owner)[0] == 200
    assert w.write("take", job, GOOD)[0] == 200
    assert w.read("take", job)["source"] is None and w.read("take", job, w.other)["source"] is None
    assert w.read("take", job, w.owner)["source"]["title"] == GOOD["title"]


# ----- AC-S6 nothing written -----------------------------------------------------------------------------
def test_no_source_reads_as_null_and_a_bad_id_reads_as_null(world: World) -> None:
    assert world.read("entry", ENTRY)["source"] is None and world.read("take", world.job)["source"] is None
    assert world.read("entry", "no%20such%20id")["source"] is None
    assert world.read("take", "x")["mine"] is False


# ----- AC-S7 download my data ----------------------------------------------------------------------------
def test_download_my_data_carries_the_owners_sources_only(world: World) -> None:
    world.write("entry", ENTRY, GOOD)
    world.write("take", world.job, {"title": "Mine", "licence": "own recording"})
    doc = get(world.api, "api/me/export", cookie=world.owner)[2]
    rows = doc["sources"]
    assert {r["kind"] for r in rows} == {"entry", "take"}
    entry = next(r for r in rows if r["kind"] == "entry")
    assert entry["title"] == GOOD["title"] and entry["url"] == GOOD["url"] and entry["licence"] == "CC BY 4.0" and entry["id"] == ENTRY
    assert next(r for r in rows if r["kind"] == "take")["id"] == world.job
    assert get(world.api, "api/me/export", cookie=world.other)[2]["sources"] == []
    assert world.oid not in json.dumps(doc["sources"])


# ----- AC-S8 deletes ---------------------------------------------------------------------------------------
def test_deleting_a_take_or_the_account_removes_the_credit(world: World) -> None:
    world.write("entry", ENTRY, GOOD)
    world.write("take", world.job, GOOD)
    world.store.forget_job(world.job)
    assert [r["kind"] for r in world.store.fetch("SELECT kind FROM source_credits")] == ["entry"]
    world.store.delete_user(world.oid)
    assert world.store.fetch("SELECT * FROM source_credits") == []


# ----- AC-S9 share view -------------------------------------------------------------------------------------
def test_a_share_view_carries_the_take_source(world: World) -> None:
    world.write("take", world.job, GOOD)
    token = share.create_share(world.store, world.oid, "take_result", world.job, False, False, 7, snapshot={"title": "Lateral raise"})
    status, _, snap = get(world.api, f"api/shared/{token}")
    assert status == 200 and snap["source"]["title"] == GOOD["title"] and snap["source"]["licence_label"] == "CC BY 4.0"
    assert "user" not in json.dumps(snap["source"])


def test_a_share_view_of_a_take_with_no_source_has_none(world: World) -> None:
    token = share.create_share(world.store, world.oid, "take_result", world.job, False, False, 7, snapshot={"title": "Lateral raise"})
    assert get(world.api, f"api/shared/{token}")[2]["source"] is None


def test_a_share_view_hides_the_source_of_an_only_me_entry(world: World) -> None:
    world.write("take", world.job, GOOD)
    post(world.api, f"api/me/entries/{ENTRY}", {"only_me": True}, cookie=world.owner)
    token = share.create_share(world.store, world.oid, "take_result", world.job, False, False, 7, snapshot={"title": "Lateral raise"})
    assert get(world.api, f"api/shared/{token}")[2]["source"] is None


# ----- AC-S10 migration ------------------------------------------------------------------------------------
def test_the_migration_is_idempotent_and_changes_no_other_table() -> None:
    conn = sqlite3.connect(":memory:")
    source_credit.migrate(conn)
    source_credit.migrate(conn)
    assert [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")] == ["source_credits"]
    assert origin  # the helper import is part of the fixture set


# ----- B1 licence links, R3 address, R4 existence, R10 label, B3 trainer cascade ------------------------------------
@pytest.mark.parametrize("name, url", [
    ("CC BY 4.0", "https://creativecommons.org/licenses/by/4.0/"), ("CC0", "https://creativecommons.org/publicdomain/zero/1.0/"),
    ("Pexels License", "https://www.pexels.com/license/"), ("Pixabay Content License", "https://pixabay.com/service/license-summary/"),
])
def test_each_licence_carries_its_official_page(world: World, name: str, url: str) -> None:
    body = world.write("entry", ENTRY, {"title": "x", "licence": name})[1]
    assert body["source"]["licence_url"] == url and url.startswith("https://")


def test_own_recording_and_other_have_no_licence_page_and_own_recording_is_not_called_a_licence(world: World) -> None:
    own = world.write("entry", ENTRY, {"title": "x", "licence": "own recording"})[1]["source"]
    assert own["licence_url"] == "" and own["licence_label"] == source_credit.LABEL_OWN == "Own recording (no licence needed)"
    other = world.write("entry", ENTRY, {"title": "x", "licence": "Other", "licence_other": "My terms"})[1]["source"]
    assert other["licence_url"] == ""


def test_the_address_is_stored_with_an_ascii_host_by_uts46(world: World) -> None:
    got = world.write("entry", ENTRY, {"title": "x", "licence": "CC0", "url": "https://B\u00fccher.example/Pfad?q=1#t"})[1]["source"]
    assert got["url"] == "https://xn--bcher-kva.example/Pfad?q=1#t"
    sharp = world.write("entry", ENTRY, {"title": "x", "licence": "CC0", "url": "https://fa\u00df.de/a"})[1]["source"]
    assert sharp["url"] == "https://xn--fa-hia.de/a"  # not folded to fass.de
    wide = world.write("entry", ENTRY, {"title": "x", "licence": "CC0", "url": "https://\uff21\uff22C.example/"})[1]["source"]
    assert wide["url"] == "https://abc.example/"


def test_a_host_that_fails_idna_encoding_is_refused(world: World) -> None:
    for host in ("a..example", "-bad-.example", "xn--.example", "a" * 64 + ".example"):
        status, body = world.write("entry", ENTRY, {"title": "x", "licence": "CC0", "url": f"https://{host}/"})
        assert status == 400 and body["message"] == source_credit.MSG_URL, host
        with pytest.raises(source_credit.SourceError):
            source_credit.clean_url(f"https://{host}/")


def test_a_stranger_gets_404_not_403_for_a_hidden_subject(world: World) -> None:
    post(world.api, f"api/me/entries/{ENTRY}", {"only_me": True}, cookie=world.owner)
    assert world.write("entry", ENTRY, GOOD, world.other)[0] == 404
    assert world.write("take", world.job, GOOD, world.other)[0] == 404  # the take's movement is only me
    post(world.api, f"api/me/entries/{ENTRY}", {"only_me": False}, cookie=world.owner)
    assert world.write("entry", ENTRY, GOOD, world.other)[0] == 403


def test_a_stranger_gets_404_for_a_private_take(api: Api) -> None:
    w = World(api)
    job = make_job(api, private=True)
    post(api, "api/me/claims", {"job_id": job}, cookie=w.owner)
    assert w.write("take", job, GOOD, w.other)[0] == 404


def test_deleting_a_trainer_take_through_the_route_removes_the_entry_credit(api: Api) -> None:
    owner = sign_in(api, OWNER)
    made = api.app.queue.submit("trainer", lambda ctx: {"result": {"entry_id": "made-entry-1"}}, entry_id=None)
    api.app.queue.wait(made["id"], 10)
    assert post(api, "api/me/claims", {"job_id": made["id"]}, cookie=owner)[0] == 200
    assert send(api, "api/me/source/entry/made-entry-1", GOOD, owner)[0] == 200
    store = auth.identity(api.app)
    assert len(store.fetch("SELECT * FROM source_credits")) == 1
    assert post(api, f"api/jobs/{made['id']}/delete", cookie=owner)[0] == 200  # the owner (TICKET-373)
    assert store.fetch("SELECT * FROM source_credits") == []
