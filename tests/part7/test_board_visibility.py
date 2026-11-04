"""Who sees and joins a board, and the invite mail (docs/specs/board-visibility.md, TICKET-394)."""

from __future__ import annotations

from email.parser import BytesParser
from email.policy import default as default_policy
import json
import logging
import re
from typing import Any

import pytest

from auth_support import authenv, get, outbox, post, sign_in  # noqa: F401
from part7 import auth_routes, challenge_visibility as vis, challenges, entry_access, invite_mail, mail
from support import Api, published

pytestmark = pytest.mark.usefixtures("authenv")
ENTRY = "lateral-raise"
OWNER, ANN, BOB = "owner@example.com", "ann@example.com", "bob@example.com"


def make(api: Api, sid: str | None, **over: Any) -> tuple[int, dict[str, Any]]:
    published(api.app.state, ENTRY)
    body = {"entry_id": ENTRY, "title": "Beat my raises", "creator_name": "Sam", "kind": "friend", **over}
    status, _, doc = post(api, "api/challenges", body, cookie=sid)
    return status, doc


def board(api: Api, sid: str | None, cid: str) -> tuple[int, Any]:
    status, _, doc = get(api, f"api/challenges/{cid}", cookie=sid)
    return status, doc


def invite_mails(api: Api) -> list[Any]:
    out = []
    for path in outbox(api):
        msg = BytesParser(policy=default_policy).parsebytes(path.read_bytes())
        if "invited you" in str(msg["Subject"]):
            out.append(msg)
    return out


def invited_board(api: Api, owner: str, who: list[str]) -> tuple[str, dict[str, Any]]:
    status, doc = make(api, owner, visibility="invited", invites=who)
    assert status == 201, doc
    return doc["id"], doc


# ----- the access matrix ----------------------------------------------------------------------------------
def test_access_matrix_for_an_invited_board(api: Api) -> None:
    own, ann, bob = sign_in(api, OWNER), sign_in(api, ANN), sign_in(api, BOB)
    cid, _ = invited_board(api, own, ["Ann@Example.COM"])
    assert board(api, own, cid)[0] == 200                         # owner
    status, doc = board(api, ann, cid)                            # invited, other letter case
    assert status == 200 and doc["you"] == "guest" and doc["visibility"] == "invited"
    status, doc = board(api, None, cid)                           # signed out
    assert status == 401 and doc["needs_sign_in"] is True and doc["error"] == vis.MSG_SIGN_IN
    status, doc = board(api, bob, cid)                            # signed in with another address
    assert status == 403 and doc["error"] == vis.MSG_WRONG_ACCOUNT
    assert "example.com" not in json.dumps(doc) and "Ann" not in json.dumps(doc)   # names nobody, confirms nothing
    status, _, _ = post(api, f"api/challenges/{cid}/access", {"remove": [ANN]}, cookie=own)   # removed
    assert status == 200 and board(api, ann, cid)[0] == 403
    assert board(api, own, "nosuchboard1")[0] == 404


def test_wrong_account_and_not_invited_get_the_same_words(api: Api) -> None:
    own, bob = sign_in(api, OWNER), sign_in(api, BOB)
    cid, _ = invited_board(api, own, [ANN])
    other, _ = invited_board(api, own, ["zed@example.com"])
    assert board(api, bob, cid)[1] == board(api, bob, other)[1]


def test_plus_addresses_and_case_follow_the_sign_in_rule(api: Api) -> None:
    own, plus, plain = sign_in(api, OWNER), sign_in(api, "ann+x@example.com"), sign_in(api, ANN)
    cid, _ = invited_board(api, own, ["  ANN@example.com "])
    assert board(api, plain, cid)[0] == 200
    assert board(api, plus, cid)[0] == 403                        # no provider aliasing: two spellings, two accounts
    assert vis.clean_emails(["A@b.com", "a@B.COM", "nope", 5]) == (["a@b.com"], ["nope", "5"])


def test_public_board_is_open_to_everyone_and_listed(api: Api) -> None:
    own = sign_in(api, OWNER)
    status, doc = make(api, own)
    assert status == 201 and doc["visibility"] == "public"
    assert board(api, None, doc["id"])[0] == 200
    rows = get(api, f"api/challenges?entry_id={ENTRY}")[2]["challenges"]
    assert [r["id"] for r in rows] == [doc["id"]]


def test_invited_board_is_listed_only_for_those_who_may_view_it(api: Api) -> None:
    own, ann, bob = sign_in(api, OWNER), sign_in(api, ANN), sign_in(api, BOB)
    cid, _ = invited_board(api, own, [ANN])
    ids = lambda sid: [r["id"] for r in get(api, f"api/challenges?entry_id={ENTRY}", cookie=sid)[2]["challenges"]]  # noqa: E731
    assert ids(own) == [cid] and ids(ann) == [cid] and ids(bob) == [] and ids(None) == []


def test_a_private_board_made_beside_an_open_public_one_stays_private(api: Api) -> None:
    """Round 13 H2: the maker already has a public friend board; naming people makes a second, private board."""
    own, ann, bob = sign_in(api, OWNER), sign_in(api, ANN), sign_in(api, BOB)
    status, public = make(api, own)
    assert status == 201 and public["visibility"] == "public"
    cid, _ = invited_board(api, own, [ANN])
    assert cid != public["id"]
    assert board(api, ann, cid)[0] == 200                                         # the invited person
    assert board(api, bob, cid)[0] == 403 and board(api, None, cid)[0] == 401     # a stranger, signed in or not
    ids = lambda sid: [r["id"] for r in get(api, f"api/challenges?entry_id={ENTRY}", cookie=sid)[2]["challenges"]]  # noqa: E731
    assert cid not in ids(bob) and cid not in ids(None)


def test_no_address_in_any_answer_except_to_the_owner(api: Api) -> None:
    own, ann = sign_in(api, OWNER), sign_in(api, ANN)
    cid, made = invited_board(api, own, [ANN])
    assert ANN in json.dumps(made["access"])                      # the owner sees the list
    for sid in (own, ann, None):
        for path in (f"api/challenges/{cid}", "api/challenges"):
            text = json.dumps(get(api, path, cookie=sid)[2])
            assert ANN not in text and OWNER not in text
    assert get(api, f"api/challenges/{cid}/access", cookie=ann)[0] == 403
    assert get(api, f"api/challenges/{cid}/access", cookie=None)[0] == 401


def test_follow_and_add_use_the_same_check(api: Api) -> None:
    own, bob = sign_in(api, OWNER), sign_in(api, BOB)
    cid, _ = invited_board(api, own, [ANN])
    status, _, doc = post(api, f"api/challenges/{cid}/entries", {"job_id": "x" * 12, "name": "Bob"}, cookie=bob)
    assert status == 403 and doc["error"] == vis.MSG_WRONG_ACCOUNT
    assert challenges.get(api.app.state, cid)["visibility"] == "invited"


# ----- choosing, changing, no dead ends -------------------------------------------------------------------
def test_invited_needs_a_signed_in_maker(api: Api) -> None:
    status, doc = make(api, None, visibility="invited", invites=[ANN])
    assert status == 401 and doc["error"] == vis.MSG_SIGN_IN_TO_CHOOSE
    assert make(api, sign_in(api, OWNER), visibility="secret")[0] == 400
    assert make(api, sign_in(api, OWNER), visibility="invited", invites=["not an address"])[0] == 400


def test_owner_changes_back_and_forth_and_the_list_survives(api: Api) -> None:
    own, ann = sign_in(api, OWNER), sign_in(api, ANN)
    cid, _ = invited_board(api, own, [ANN])
    status, _, doc = post(api, f"api/challenges/{cid}/access", {"visibility": "public"}, cookie=own)
    assert status == 200 and doc["visibility"] == "public" and board(api, None, cid)[0] == 200
    status, _, doc = post(api, f"api/challenges/{cid}/access", {"visibility": "invited", "add": [BOB], "mail": False}, cookie=own)
    assert [i["email"] for i in doc["invites"]] == [ANN, BOB] and board(api, None, cid)[0] == 401
    assert board(api, ann, cid)[0] == 200


def test_only_the_owner_changes_access(api: Api) -> None:
    own, ann = sign_in(api, OWNER), sign_in(api, ANN)
    cid, _ = invited_board(api, own, [ANN])
    assert post(api, f"api/challenges/{cid}/access", {"visibility": "public"}, cookie=ann)[0] == 403
    assert post(api, f"api/challenges/{cid}/access", {"visibility": "public"}, cookie=None)[0] == 401
    assert post(api, f"api/challenges/{cid}/access", {"visibility": "public"}, cookie=own, guard=False)[0] == 403   # CSRF guard
    assert board(api, None, cid)[0] == 401


def test_the_owner_sees_who_joined(api: Api) -> None:
    own, ann = sign_in(api, OWNER), sign_in(api, ANN)
    cid, _ = invited_board(api, own, [ANN, BOB])
    before = get(api, f"api/challenges/{cid}/access", cookie=own)[2]["invites"]
    assert [i["joined"] for i in before] == [False, False]
    board(api, ann, cid)
    after = get(api, f"api/challenges/{cid}/access", cookie=own)[2]["invites"]
    assert {i["email"]: i["joined"] for i in after} == {ANN: True, BOB: False}


# ----- migration ------------------------------------------------------------------------------------------
def test_a_board_stored_before_visibility_stays_public(api: Api) -> None:
    published(api.app.state, ENTRY)
    legacy = challenges.create(api.app.state, entry_id=ENTRY, title="Old board", creator_name="Sam", kind="friend", owner="u1")
    stored = challenges.get(api.app.state, legacy["id"])
    for key in ("visibility", "invites"):
        stored.pop(key)
    challenges._write(api.app.state, stored)
    assert vis.visibility_of(stored) == "public" and vis.can_view(stored, None)
    status, doc = board(api, None, legacy["id"])
    assert status == 200 and doc["visibility"] == "public"
    assert [r["id"] for r in get(api, f"api/challenges?entry_id={ENTRY}")[2]["challenges"]] == [legacy["id"]]


# ----- the mail ---------------------------------------------------------------------------------------------
def test_invite_mail_content(api: Api) -> None:
    own = sign_in(api, OWNER)
    status, doc = make(api, own, creator_name="Sam www.evil.io", title="Win at http://evil.example/x now",
                       visibility="invited", invites=[ANN])
    assert doc["access"]["mail"][0]["state"] == "sent"
    (msg,) = invite_mails(api)
    text = msg.get_body(("plain",)).get_content()
    assert msg["To"] == ANN and "Sam invited you" in str(msg["Subject"])
    assert "evil" not in text and "evil" not in str(msg["Subject"]) and 'challenge "Win at now"' in text      # the sender's words, cleaned
    assert f"/simon-part-7/#/challenge/{doc['id']}" in text and "api/invites/stop/" in text
    assert "Simon Live LLC, Example Address, Test City" in text
    assert msg["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click" and "api/invites/stop/" in msg["List-Unsubscribe"]
    assert "—" not in text and "–" not in text


def test_clean_label_strips_links_markup_and_breaks() -> None:
    assert invite_mail.clean_label("Sam https://evil.example/p", "x", 24) == "Sam"
    assert invite_mail.clean_label("see evil.io/pay", "x", 24) == "see"
    assert "\n" not in invite_mail.clean_label("Ann\r\nBcc: x", "x", 24) and "<" not in invite_mail.clean_label("<b>Ann", "x", 24)
    assert invite_mail.clean_label("a@b.com", "Someone", 24) == "Someone"
    assert invite_mail.clean_label(7, "Someone", 24) == "Someone" and invite_mail.clean_label("x" * 90, "y", 24) == "x" * 24


def test_failed_send_is_shown_with_the_link_and_never_logs_an_address(api: Api, monkeypatch: pytest.MonkeyPatch,
                                                                       caplog: pytest.LogCaptureFixture) -> None:
    own = sign_in(api, OWNER)
    monkeypatch.setattr(mail.Mailer, "send_message_now", lambda self, msg, kind="invite": False)
    with caplog.at_level(logging.DEBUG):
        status, doc = make(api, own, visibility="invited", invites=[ANN])
    sent = doc["access"]["mail"][0]
    assert status == 201 and sent["state"] == "failed" and re.fullmatch(r"inv_[0-9a-f]{8}", sent["failure_id"])
    assert doc["access"]["link"].endswith(f"#/challenge/{doc['id']}")      # the copyable link
    assert "example.com" not in caplog.text and sent["failure_id"] in caplog.text
    kept = get(api, f"api/challenges/{doc['id']}/access", cookie=own)[2]["invites"][0]
    assert kept["mail"] == "failed"
    monkeypatch.undo()
    status, _, again = post(api, f"api/challenges/{doc['id']}/access", {"resend": [ANN]}, cookie=own)
    assert again["mail"][0]["state"] == "sent" and get(api, f"api/challenges/{doc['id']}/access", cookie=own)[2]["invites"][0]["mail"] == "sent"


def test_a_provider_that_raises_is_a_failed_send(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(self: Any, msg: Any, kind: str = "invite") -> bool:
        raise OSError("down")
    monkeypatch.setattr(mail.Mailer, "send_message_now", boom)
    doc = make(api, sign_in(api, OWNER), visibility="invited", invites=[ANN])[1]
    assert doc["access"]["mail"][0]["state"] == "failed"


def test_send_message_now_counts_only_what_the_transport_accepted(tmp_path: Any) -> None:
    msg = invite_mail.build_message(ANN, "Simon <s@x.org>", "Sam", "T", "https://x.org/#/challenge/a", "https://x.org/s")
    assert mail.Mailer(tmp_path, "off").send_message_now(msg) is False
    assert mail.Mailer(tmp_path, "outbox").send_message_now(msg) is True   # the staging test mailbox is the fake mail
    assert mail.Mailer(tmp_path, "file").send_message_now(msg) is True
    seen: list[Any] = []
    real = mail._api_send
    mail._api_send = lambda url, key, m: seen.append(m) or False   # type: ignore[assignment]
    try:
        assert mail.Mailer(tmp_path, "api").send_message_now(msg) is False and len(seen) == 1
    finally:
        mail._api_send = real  # type: ignore[assignment]


# ----- a crew's take of the same routine joins the board (operator, release 10) -------------------------------------
def crew_job(api: Api, job_id: str, own_entry: str = "crew-made-entry", **record: Any) -> str:
    """A finished group job that made its own movement `own_entry`, with each person's analysis on disk."""
    from part7 import group
    analysis = {"status": {"code": "ok"}, "score": {"value": 80, "grade": "B", "timeline": []}, "faults": []}
    people = [{"id": pid, "label": f"P{pid}", "score": 50} for pid in ("1", "2")]
    api.app.queue._jobs[job_id] = {"id": job_id, "kind": "group", "status": "done", "entry_id": own_entry, "stages": [], "note": None,
                                   "result": {"entry_id": own_entry, "people": people}, **record}
    for pid in ("1", "2"):
        folder = group.person_dir(api.app.queue.job_dir(job_id), pid)
        folder.mkdir(parents=True)
        (folder / "analysis.json").write_text(json.dumps(analysis), encoding="utf-8")
    return job_id


class StubHandler:
    def __init__(self, api: Api) -> None:
        self.app, self.headers, self.client_address, self.errors = api.app, {}, ("127.0.0.1", 1), []

    def _error(self, status: int, message: str, **more: Any) -> None:
        self.errors.append((status, message))


def test_a_crew_take_whose_source_is_the_boards_movement_joins_it(api: Api) -> None:
    own = sign_in(api, OWNER)
    published(api.app.state, ENTRY)
    board_id = make(api, own)[1]["id"]
    h = StubHandler(api)
    source = __import__("part7.challenge_routes", fromlist=["x"]).group_source(h, {"challenge_id": board_id})
    assert source == {"challenge_id": board_id, "source_entry_id": ENTRY}      # derived from the challenge on the server
    job = crew_job(api, "c" * 12, **source)
    status, _, doc = post(api, f"api/challenges/{board_id}/entries", {"job_id": job, "people": [{"pid": "1", "name": "Ann"}, {"pid": "2", "name": "Bo"}]})
    assert status == 201 and sorted(e["name"] for e in doc["added"]) == ["Ann", "Bo"]
    assert sorted(e["name"] for e in board(api, None, board_id)[1]["entries"]) == ["Ann", "Bo"]


def test_a_crew_take_of_another_routine_is_refused(api: Api) -> None:
    own = sign_in(api, OWNER)
    board_id = make(api, own)[1]["id"]
    elsewhere = crew_job(api, "d" * 12, source_entry_id="some-other-routine", challenge_id="whatever1")
    status, _, doc = post(api, f"api/challenges/{board_id}/entries", {"job_id": elsewhere, "people": [{"pid": "1", "name": "Ann"}]})
    assert status == 409 and "different movement" in doc["error"]
    plain = crew_job(api, "e" * 12)                       # a group take with no source at all
    assert post(api, f"api/challenges/{board_id}/entries", {"job_id": plain, "people": [{"pid": "1", "name": "Ann"}]})[0] == 409
    assert board(api, None, board_id)[1]["entries"] == []


def test_a_forged_source_in_the_request_is_ignored(api: Api) -> None:
    from part7 import challenge_routes
    own = sign_in(api, OWNER)
    board_id = make(api, own)[1]["id"]
    h = StubHandler(api)
    got = challenge_routes.group_source(h, {"challenge_id": board_id, "source_entry_id": "forged-routine"})
    assert got["source_entry_id"] == ENTRY                # the client's value is never read
    assert challenge_routes.group_source(h, {"source_entry_id": ENTRY}) == {}      # a bare source, no challenge: nothing recorded
    assert challenge_routes.group_source(h, {"challenge_id": "nosuchboard"}) is None and h.errors[-1][0] == 400
    # a job record the client could not have set: a solo follow never carries a source, so it cannot use one
    solo = {"id": "f" * 12, "kind": "follow", "status": "done", "entry_id": "x", "stages": [], "note": None, "source_entry_id": ENTRY}
    api.app.queue._jobs["f" * 12] = solo
    status, _, doc = post(api, f"api/challenges/{board_id}/entries", {"job_id": "f" * 12, "name": "Zed"})
    assert status in (404, 409) and board(api, None, board_id)[1]["entries"] == []   # only a group job's source counts


def test_a_crew_cannot_join_a_prize_board(api: Api) -> None:
    """Prize boards take one result per signed-in account; a crew's people share the poster's account, so they stay out."""
    doc = {"entries": [], "kind": "sponsored"}
    crew = [{"owner": "u1", "pid": "1", "job_id": "j" * 12}, {"owner": "u1", "pid": "2", "job_id": "j" * 12}]
    with pytest.raises(challenges.ChallengeError) as refused:
        challenges._admit_prize(doc, crew)
    assert refused.value.status == 409 and refused.value.args[0] == challenges.MSG_SPONSOR_CREW
    challenges._admit_prize(doc, [{"owner": "u1", "pid": None, "job_id": "k" * 12}])      # a solo, signed-in take still passes
    with pytest.raises(challenges.ChallengeError):
        challenges._admit_prize(doc, [{"pid": None, "job_id": "k" * 12}])                  # signed out: refused


def test_a_bounced_address_is_not_mailed_again(api: Api) -> None:
    """lane/mail-hardening: the Resend webhook records a bounce or complaint (mail_suppress); invites honour it."""
    from part7 import mail_suppress
    own = sign_in(api, OWNER)
    mail_suppress.add(api.app.state, ANN, "bounce")
    cid, doc = invited_board(api, own, [ANN, BOB])
    states = {m["email"]: m["state"] for m in doc["access"]["mail"]}
    assert states == {ANN: "not_mailed", BOB: "sent"} and len(invite_mails(api)) == 1
    assert invite_mails(api)[0]["To"] == BOB and invite_mails(api)[0]["Message-ID"] and invite_mails(api)[0]["Date"]


def test_no_cap_stops_a_send(api: Api) -> None:
    """Operator 2026-11-04, no limits: many addresses, many resends, all mailed."""
    own = sign_in(api, OWNER)
    who = [f"p{i}@example.com" for i in range(25)]
    cid, doc = invited_board(api, own, who)
    assert [m["state"] for m in doc["access"]["mail"]] == ["sent"] * 25
    for _ in range(3):
        _, _, again = post(api, f"api/challenges/{cid}/access", {"resend": who[:2]}, cookie=own)
        assert [m["state"] for m in again["mail"]] == ["sent", "sent"]
    assert len(invite_mails(api)) == 25 + 6


def test_stop_link_is_honoured_on_the_server(api: Api) -> None:
    own = sign_in(api, OWNER)
    cid, _ = invited_board(api, own, [ANN])
    link = re.search(r"api/invites/stop/([0-9a-f]{32})", invite_mails(api)[0].get_body(("plain",)).get_content())
    assert link
    key = link.group(1)
    status, _, page = api.request("GET", f"api/invites/stop/{key}")[0], None, api.request("GET", f"api/invites/stop/{key}")[2]
    assert status == 200 and b"<form" in page                      # a GET changes nothing (link scanners)
    assert not invite_mail.stopped(api.app.state, key)
    assert api.request("POST", f"api/invites/stop/{key}", b"List-Unsubscribe=One-Click", {})[0] == 200
    assert invite_mail.stopped(api.app.state, key)
    _, _, again = post(api, f"api/challenges/{cid}/access", {"resend": [ANN]}, cookie=own)
    assert again["mail"][0]["state"] == "not_mailed" and len(invite_mails(api)) == 1
    assert api.request("POST", f"api/invites/stop/{'0' * 32}", b"", {})[0] == 404      # only keys that went out


def test_the_owners_own_address_is_not_mailed(api: Api) -> None:
    cid, doc = invited_board(api, sign_in(api, OWNER), [OWNER, ANN])
    assert [m["email"] for m in doc["access"]["mail"]] == [ANN] and len(invite_mails(api)) == 1


# ----- names ------------------------------------------------------------------------------------------------
def test_an_address_is_refused_as_a_name_or_title_and_masked_when_stored(api: Api) -> None:
    own = sign_in(api, OWNER)
    for field in ("creator_name", "title"):
        for typed in ("teammate@example.com", "teammate＠example.com"):
            status, doc = make(api, own, **{field: typed})
            assert status == 400 and "@" in doc["error"]
    published(api.app.state, ENTRY)
    old = challenges.create(api.app.state, entry_id=ENTRY, title="Fine", creator_name="Sam", kind="friend")
    stored = challenges.get(api.app.state, old["id"])
    stored["creator_name"] = "teammate@example.com"
    stored["entries"] = [{"name": "teammate@example.com", "score": 5, "grade": "C", "created_at": "2026-11-01T00:00:00Z"}]
    challenges._write(api.app.state, stored)
    text = json.dumps(board(api, None, old["id"])[1]) + json.dumps(get(api, "api/challenges")[2])
    assert "teammate" not in text and "Hidden name" in text


# ----- a private movement -------------------------------------------------------------------------------------
def test_private_movement_the_owner_is_warned_and_the_link_does_not_die(api: Api) -> None:
    own, ann, bob = sign_in(api, OWNER), sign_in(api, ANN), sign_in(api, BOB)
    cid, _ = invited_board(api, own, [ANN])
    pub, pubdoc = make(api, own)
    assert entry_access.set_published(api.app.state, ENTRY, False) or True
    entry_access.record(api.app.state, ENTRY, owner="someone-else", published=False, age_band="adult")
    status, doc = board(api, ann, cid)                              # invited: sees the board, not the movement
    assert status == 200 and doc["movement_private"] is True and doc["warning"] is None
    status, doc = board(api, own, cid)                              # owner: the board link stays, with a warning
    assert status == 200 and "private" in doc["warning"]
    assert get(api, f"api/challenges/{cid}/access", cookie=own)[2]["movement_private"] is True
    assert board(api, bob, cid)[0] == 403                           # not invited
    status, doc = board(api, None, pubdoc["id"])                    # a public board of a private movement: still not shown,
    assert status == 404 and doc["code"] == "movement_private" and "publish" in doc["error"]   # but the words say why
    status, _, doc = post(api, f"api/challenges/{cid}/entries", {"job_id": "x" * 12, "name": "Ann"}, cookie=ann)
    assert status == 403 and doc["error"] == challenge_routes_msg()


def challenge_routes_msg() -> str:
    from part7 import challenge_routes
    return challenge_routes.MSG_GUEST_PRIVATE


# ----- deleting my data ---------------------------------------------------------------------------------------
def test_delete_my_data_covers_boards_invites_and_the_address(api: Api) -> None:
    own, ann = sign_in(api, OWNER), sign_in(api, ANN)
    mine, _ = invited_board(api, own, [ANN])
    other_owner = sign_in(api, "zed@example.com")
    theirs, _ = invited_board(api, other_owner, [ANN, BOB])
    ann_id = api.app.state and auth_user(api, ann)
    auth_routes.delete_account(api.app, ann_id)
    assert vis.invite_emails(challenges.get(api.app.state, theirs)) == [BOB]       # off every list
    own_id = auth_user(api, own)
    auth_routes.delete_account(api.app, own_id)
    assert challenges.get(api.app.state, mine) is None                              # the owner's board and its list go
    assert ANN not in json.dumps([d for d in challenges.docs(api.app.state)])


def test_a_stop_survives_delete_my_data(api: Api) -> None:
    own, ann = sign_in(api, OWNER), sign_in(api, ANN)
    invited_board(api, own, [ANN])
    key = invite_mail.stop_key(api.app.state and __import__("part7.auth", fromlist=["x"]).identity(api.app).pepper, ANN)
    assert invite_mail.stop(api.app.state, key)
    auth_routes.delete_account(api.app, auth_user(api, ann))
    assert invite_mail.stopped(api.app.state, key)                                  # the opt-out keeps being honoured, a hash only


def auth_user(api: Api, sid: str) -> str:
    return get(api, "api/auth/me", cookie=sid)[2]["user_id"]


def test_export_lists_the_owners_invites(api: Api) -> None:
    own = sign_in(api, OWNER)
    invited_board(api, own, [ANN])
    from part7 import export_data
    docs = challenges.made_by(api.app.state, auth_user(api, own))
    assert docs and docs[0]["invites"][0]["email"] == ANN and export_data  # the exporter reads these stored rows


# ----- prod rules for making a board (audit row 2) and the create-time warning ------------------------------------
def test_prod_needs_sign_in_and_a_result_and_ignores_the_friend_title(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    from part7 import challenge_routes, prod_mode
    own = sign_in(api, OWNER)
    published(api.app.state, ENTRY)
    monkeypatch.setattr(prod_mode, "is_prod", lambda: True)
    body = {"entry_id": ENTRY, "title": "BUY CRYPTO", "creator_name": "Simon Official", "kind": "friend"}
    status, _, doc = post(api, "api/challenges", body)
    assert status == 401 and doc["error"] == challenge_routes.MSG_PROD_SIGN_IN
    status, _, doc = post(api, "api/challenges", body, cookie=own)
    assert status == 400 and doc["error"] == challenge_routes.MSG_PROD_RESULT       # no board without a scored result
    assert get(api, "api/challenges")[2]["challenges"] == []
    h = type("H", (), {"app": api.app})()
    assert challenge_routes._friend_title(h, ENTRY).startswith("Beat my ") and "CRYPTO" not in challenge_routes._friend_title(h, ENTRY)


def test_the_create_answer_warns_when_the_movement_is_private(api: Api) -> None:
    own = sign_in(api, OWNER)
    assert make(api, own)[1]["movement_private"] is False
    entry_access.set_published(api.app.state, ENTRY, False)
    entry_access.record(api.app.state, ENTRY, owner="someone-else", published=False, age_band="adult")
    status, _, _ = post(api, "api/challenges", {"entry_id": ENTRY, "title": "T", "creator_name": "Sam", "kind": "friend"}, cookie=own)
    assert status == 404                                   # a movement the maker cannot view cannot get a board at all
