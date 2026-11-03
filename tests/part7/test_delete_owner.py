"""Who may delete a take, and the featured hero (TICKET-373, delete-take.md "Authorisation", judge-view.md AC-J7).

Real sessions through the sign-in routes (auth_support.sign_in) and the real identity store; each refusal is checked
with the file still on disk and still served afterwards.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from auth_support import authenv, post, sign_in  # noqa: F401  authenv is a fixture
from part7 import auth, delete_routes, identity, impact, judge_view
from support import Api
from test_judge_view import REAL, finished

OTHER = "grace.hopper@example.com"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(judge_view.HERO_ENV, raising=False)
    monkeypatch.delenv(impact.ENV, raising=False)


def take(api: Api, score: int = 80) -> tuple[str, Path]:
    """A finished follow take that qualifies as a hero, with a clip; returns its id and its clip path."""
    job_id = finished(api, "follow", REAL, score=score)
    clip = api.app.queue.job_dir(job_id) / "work" / "video.mp4"
    clip.write_bytes(b"clip-bytes")
    return job_id, clip


def own(api: Api, sid: str, job_id: str, via: str = "submit") -> str:
    """Record `job_id` as owned by the user of session `sid` (`submit`: what attach_job does at submit; `claim`: a claim
    recorded before claims of featured takes were refused); returns the user id."""
    store = auth.identity(api.app)
    user = store.session_user(sid)
    store.attach(job_id, user, "follow", REAL, None, via)
    return user


def name_hero(api: Api, job_id: str) -> None:
    (api.app.state / judge_view.HERO_FILE).write_text(json.dumps({"job_id": job_id}), encoding="utf-8")


def delete(api: Api, job_id: str, sid: str | None = None) -> tuple[int, Any]:
    status, _, body = post(api, f"api/jobs/{job_id}/delete", {}, cookie=sid)
    return status, body


def plays(api: Api, job_id: str, sid: str | None = None) -> bool:
    headers = {"Cookie": f"{auth.COOKIE}={sid}"} if sid else {}
    status, _, body = api.request("GET", f"api/results/{job_id}/video.mp4", None, headers)
    return status == 200 and body == b"clip-bytes"


# ----- the featured hero ------------------------------------------------------------------------------------
def test_the_named_hero_plays_signed_out_and_a_signed_out_delete_is_refused(api: Api) -> None:
    finished(api, "trainer", REAL)
    hero, clip = take(api)
    (api.app.state / judge_view.HERO_FILE).write_text(json.dumps({"job_id": hero}), encoding="utf-8")
    assert api.json("GET", "api/judge/hero")[1]["job_id"] == hero
    assert plays(api, hero)  # the judge view, signed out
    status, body = delete(api, hero)
    assert (status, body["error"]) == (403, delete_routes.MSG_FEATURED)
    assert clip.is_file() and plays(api, hero)  # negative: nothing went, and it still plays
    assert api.json("GET", "api/judge/hero")[1]["job_id"] == hero


def test_another_session_cannot_delete_the_hero(api: Api, authenv: Path) -> None:
    finished(api, "trainer", REAL)
    hero, clip = take(api)
    (api.app.state / judge_view.HERO_FILE).write_text(json.dumps({"job_id": hero}), encoding="utf-8")
    stranger = sign_in(api, OTHER)
    status, body = delete(api, hero, stranger)
    assert (status, body["error"]) == (403, delete_routes.MSG_FEATURED)
    assert clip.is_file() and plays(api, hero)


def test_the_hero_is_protected_while_named_even_when_it_no_longer_qualifies(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    job_id = finished(api, "follow", REAL, score=80, mesh=False)  # not shown: no mesh
    monkeypatch.setenv(judge_view.HERO_ENV, job_id)
    assert api.json("GET", "api/judge/hero")[1]["job_id"] is None
    assert delete(api, job_id)[0] == 403
    monkeypatch.delenv(judge_view.HERO_ENV)
    assert delete(api, job_id)[0] == 403, "TICKET-374 R1: once named, always protected from a visitor"


def test_the_signed_in_owner_of_the_hero_may_delete_it(api: Api, authenv: Path) -> None:
    finished(api, "trainer", REAL)
    hero, clip = take(api)
    (api.app.state / judge_view.HERO_FILE).write_text(json.dumps({"job_id": hero}), encoding="utf-8")
    sid = sign_in(api)
    own(api, sid, hero)
    status, body = delete(api, hero, sid)
    assert status == 200 and body["deleted"] is True and not clip.exists()


def test_an_impact_page_take_is_featured_too_even_when_it_no_longer_qualifies(api: Api, monkeypatch: pytest.MonkeyPatch,
                                                                              tmp_path: Path) -> None:
    persona, clip = take(api)
    gone_off = finished(api, "follow", "verify-2026-11-02t00-53-32z-196f3040", score=70)  # a test movement: not shown
    rows = tmp_path / "persona-takes.json"
    rows.write_text(json.dumps([{"persona": "seated", "job_id": persona, "entry_id": REAL},
                                {"persona": "bodies", "job_id": gone_off}]), encoding="utf-8")
    monkeypatch.setenv(impact.ENV, str(rows))
    assert delete_routes.featured(api.app) == {persona, gone_off}
    assert delete(api, persona)[0] == 403 and clip.is_file()
    assert delete(api, gone_off)[0] == 403 and api.app.queue.get(gone_off) is not None


# ----- review B1: a public id never becomes ownership ---------------------------------------------------------------
def test_a_featured_take_cannot_be_claimed(api: Api, authenv: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    finished(api, "trainer", REAL)
    hero, clip = take(api)
    persona, _ = take(api)
    name_hero(api, hero)
    rows = tmp_path / "persona-takes.json"
    rows.write_text(json.dumps([{"persona": "seated", "job_id": persona}]), encoding="utf-8")
    monkeypatch.setenv(impact.ENV, str(rows))
    sid = sign_in(api, OTHER)
    for job_id in (hero, persona):
        status, _, body = post(api, "api/me/claims", {"job_id": job_id}, cookie=sid)
        assert (status, body["error"]) == (403, delete_routes.MSG_NO_CLAIM)
        assert identity.owner_of_job(api.app.state, job_id) is None  # negative: nothing recorded
    assert delete(api, hero, sid)[0] == 403 and clip.is_file() and plays(api, hero)
    plain, _ = take(api)
    assert post(api, "api/me/claims", {"job_id": plain}, cookie=sid)[0] == 200  # any other take is claimed as before


def test_an_earlier_claim_neither_deletes_the_hero_nor_takes_it_with_the_account(api: Api, authenv: Path) -> None:
    finished(api, "trainer", REAL)
    hero, clip = take(api)
    name_hero(api, hero)
    sid = sign_in(api, OTHER)
    own(api, sid, hero, via="claim")  # recorded before claims of featured takes were refused
    status, body = delete(api, hero, sid)
    assert (status, body["error"]) == (403, delete_routes.MSG_FEATURED) and clip.is_file()
    status, _, body = post(api, "api/me/delete", {"confirm": "delete"}, cookie=sid)
    assert status == 200 and body["deleted"] is True and body["takes_removed"] == 0
    assert clip.is_file() and plays(api, hero)  # negative: the hero outlives the claimer's account
    assert identity.owner_of_job(api.app.state, hero) is None  # the claim went with the account
    assert api.json("GET", "api/judge/hero")[1]["job_id"] == hero


def test_the_owner_who_made_the_hero_takes_it_with_their_account(api: Api, authenv: Path) -> None:
    finished(api, "trainer", REAL)
    hero, clip = take(api)
    name_hero(api, hero)
    sid = sign_in(api)
    own(api, sid, hero)
    status, _, body = post(api, "api/me/delete", {"confirm": "delete"}, cookie=sid)
    assert status == 200 and body["takes_removed"] == 1 and not clip.exists()


# ----- a take made signed in ----------------------------------------------------------------------------------
def test_an_owned_take_is_deleted_only_from_the_owners_session(api: Api, authenv: Path) -> None:
    job_id, clip = take(api)
    owner = sign_in(api)
    own(api, owner, job_id)
    stranger = sign_in(api, OTHER)
    for sid in (None, stranger):  # signed out, then another account
        status, body = delete(api, job_id, sid)
        assert (status, body["error"]) == (403, delete_routes.MSG_NOT_OWNER)
        assert clip.is_file()  # negative: the refused delete removed nothing
    assert api.json("GET", f"api/jobs/{job_id}")[0] == 200
    status, body = delete(api, job_id, owner)
    assert status == 200 and body == {"deleted": True, "removed": ["job"]}
    assert not clip.exists() and api.json("GET", f"api/jobs/{job_id}")[0] == 404


def test_an_unreadable_owner_refuses_the_delete(api: Api, authenv: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    job_id, clip = take(api)
    sign_in(api)  # the identity store exists

    def broken(self: Any, job: str) -> None:
        raise OSError("disk")

    monkeypatch.setattr(type(auth.identity(api.app)), "owner_of", broken)
    status, body = delete(api, job_id)
    assert (status, body["error"]) == (503, delete_routes.MSG_OWNER_UNKNOWN) and clip.is_file()


# ----- an anonymous take (identity.md: delete by job id works signed out) --------------------------------------------
def test_an_anonymous_take_that_is_not_featured_is_still_deleted_by_its_id(api: Api) -> None:
    job_id, clip = take(api)
    status, body = delete(api, job_id)
    assert status == 200 and body["deleted"] is True and not clip.exists()


def test_an_unknown_id_is_still_404(api: Api) -> None:
    assert delete(api, "dddddddddddd")[0] == 404


# ----- the clip route only reads ------------------------------------------------------------------------------------
@pytest.mark.parametrize("method", ["DELETE", "POST", "PUT", "PATCH"])
def test_the_clip_route_refuses_every_write_method(api: Api, method: str) -> None:
    job_id, clip = take(api)
    status, _, _ = api.request(method, f"api/results/{job_id}/video.mp4")
    assert status == 405
    assert clip.is_file() and plays(api, job_id)



# ----- TICKET-374: R1 (once named, always featured) and R8 (CSRF guard, session fault) ----------------------
def test_a_take_once_named_hero_stays_protected_after_another_is_named(api: Api, authenv: Path) -> None:
    finished(api, "trainer", REAL)
    first, clip = take(api)
    second, _ = take(api, score=85)
    name_hero(api, first)
    assert api.json("GET", "api/judge/hero")[1]["job_id"] == first  # read as configured: recorded
    name_hero(api, second)
    assert api.json("GET", "api/judge/hero")[1]["job_id"] == second
    assert first in judge_view.ever_named(api.app.state)
    status, body = delete(api, first)
    assert (status, body["error"]) == (403, delete_routes.MSG_FEATURED) and clip.is_file()
    sid = sign_in(api)
    own(api, sid, first, via="claim")
    assert post(api, "api/me/claims", {"job_id": first}, cookie=sid)[0] == 403, "no claim of a once-named hero"
    assert delete(api, first, sid)[0] == 403 and clip.is_file(), "a claim never counts"


def test_an_unreadable_hero_file_keeps_the_last_known_hero_protected(api: Api) -> None:
    finished(api, "trainer", REAL)
    hero, clip = take(api)
    name_hero(api, hero)
    assert api.json("GET", "api/judge/hero")[1]["job_id"] == hero
    (api.app.state / judge_view.HERO_FILE).write_text("{not json", encoding="utf-8")
    assert delete(api, hero)[0] == 403 and clip.is_file()


def test_an_unreadable_ever_named_list_fails_closed(api: Api) -> None:
    finished(api, "trainer", REAL)
    plain, clip = take(api)
    (api.app.state / judge_view.EVER_FILE).write_text("{not json", encoding="utf-8")
    assert delete(api, plain)[0] == 403 and clip.is_file()
    assert (api.app.state / judge_view.EVER_FILE).read_text(encoding="utf-8") == "{not json", "left for the operator"


def test_the_delete_route_refuses_a_cross_site_post(api: Api) -> None:
    job_id, clip = take(api)
    path = f"api/jobs/{job_id}/delete"
    assert post(api, path, {}, guard=False)[0] == 403  # no JSON content type, no Origin
    assert post(api, path, {}, headers={"Origin": "https://evil.example"})[0] == 403
    status, _, body = post(api, path, {}, headers={"Sec-Fetch-Site": "cross-site"})
    assert status == 403 and body["error"] == delete_routes.MSG_CSRF and clip.is_file()
    assert delete(api, job_id)[0] == 200


def test_a_failed_session_lookup_answers_503_not_403(api: Api, authenv: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    job_id, clip = take(api)
    sid = sign_in(api)
    own(api, sid, job_id)

    def broken(self: Any, sid: str) -> None:
        raise OSError("disk")

    monkeypatch.setattr(type(auth.identity(api.app)), "session_user", broken)
    status, body = delete(api, job_id, sid)
    assert (status, body["error"]) == (503, delete_routes.MSG_OWNER_UNKNOWN) and clip.is_file()
