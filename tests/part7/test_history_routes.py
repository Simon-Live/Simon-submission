"""The api/me/history routes over a real server (docs/specs/history.md "Routes", TICKET-180 AC-2, AC-3, AC-7)."""

from __future__ import annotations

import json
import sys
from typing import Any

import pytest

from history_support import ENTRY, FIRST, OTHER, SECOND, USER, World, record_two, seed_job, world  # noqa: F401
from part7 import history_report, history_store
from support import Api

ANSWER = json.dumps({"summary": {"text": "Take 2 scored 77.", "cites": [{"take": 2}]}, "trends": [], "observations": []})
BASE = "api/me/history"


def _as(user: str | None) -> dict[str, str]:
    return {"X-Test-User": user} if user else {}


def _get(api: Api, path: str, user: str | None = USER, headers: dict[str, str] | None = None) -> tuple[int, dict[str, str], bytes]:
    return api.request("GET", path, headers={**_as(user), **(headers or {})})


def _json(api: Api, method: str, path: str, doc: Any = None, user: str | None = USER) -> tuple[int, Any]:
    return api.json(method, path, doc, headers={**_as(user), "Origin": f"http://127.0.0.1:{api.port}"})  # a same-origin page


@pytest.fixture()
def seeded(api: Api, world: World, monkeypatch: pytest.MonkeyPatch) -> Api:
    world.install_model(monkeypatch)
    record_two(api.app.state, world)
    return api


def test_auth_401_without_a_session_and_404_for_another_user(seeded: Api) -> None:  # AC-2
    paths = [("GET", BASE), ("GET", f"{BASE}/{ENTRY}"), ("POST", f"{BASE}/{ENTRY}/report"), ("GET", f"{BASE}/{ENTRY}/report"),
             ("GET", f"{BASE}/{ENTRY}/takes/{FIRST}/clip.mp4"), ("POST", f"{BASE}/consent"), ("DELETE", BASE), ("DELETE", f"{BASE}/{ENTRY}")]
    for method, path in paths:
        status, doc = _json(seeded, method, path, {"video": True, "version": "v1"}, user=None)
        assert (path, status, doc["message"]) == (path, 401, "Sign in to see this.")
    for path in (f"{BASE}/{ENTRY}", f"{BASE}/{ENTRY}/report", f"{BASE}/{ENTRY}/takes/{FIRST}/clip.mp4"):
        assert _get(seeded, path, OTHER)[0] == 404  # another user's data is not there
    assert _json(seeded, "POST", f"{BASE}/{ENTRY}/report", user=OTHER)[0] == 404
    assert _json(seeded, "GET", BASE, user=OTHER)[1]["entries"] == []
    assert _json(seeded, "DELETE", f"{BASE}/{ENTRY}", user=OTHER) == (200, {"removed": 0})
    assert len(history_store.takes(seeded.app.state, USER, ENTRY)) == 2  # untouched
    assert _get(seeded, f"{BASE}/{ENTRY}/takes/{FIRST}/clip.mp4", "bad id")[0] == 401  # not a valid user id: no session


def test_owner_without_takes_gets_200_empty(seeded: Api) -> None:  # AC-H2: "no takes yet" is an answer, not a console error
    path = f"{BASE}/lateral-raise"  # in the catalog stub, with no takes by USER
    status, doc = _json(seeded, "GET", path)
    assert status == 200 and doc["takes"] == [] and doc["entry_id"] == "lateral-raise" and doc["can_compare"] is False
    assert doc["report"] == "none" and set(doc) == set(_json(seeded, "GET", f"{BASE}/{ENTRY}")[1])  # the shape of a non-empty answer
    assert _json(seeded, "GET", path, user=None)[0] == 401
    assert _json(seeded, "GET", f"{BASE}/nothing-here")[0] == 404 and _json(seeded, "GET", f"{BASE}/Bad_Entry")[0] == 404
    assert _json(seeded, "GET", f"{BASE}/{ENTRY}", user=OTHER)[0] == 404  # another user's entry stays 404
    assert history_store.takes(seeded.app.state, USER, "lateral-raise") == []  # negative: reading it stored nothing
    assert _json(seeded, "GET", BASE)[1]["entries"][0]["entry_id"] == ENTRY and len(_json(seeded, "GET", BASE)[1]["entries"]) == 1


def test_anonymous_flows_unchanged_with_no_auth_module(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:  # opt-in identity
    for name in ("part7.auth", "part7.identity"):
        monkeypatch.setitem(sys.modules, name, None)  # lane lc-auth not present
    assert api.request("GET", "api/health")[0] == 200 and api.request("GET", "api/version")[0] == 200
    assert api.request("GET", "api/config")[0] == 200
    assert api.json("GET", BASE)[0] == 401  # the feature is off, nothing else changes
    assert api.json("GET", "api/people")[0] != 401 and api.request("GET", "")[0] == 200


def test_list_and_entry(seeded: Api) -> None:
    status, doc = _json(seeded, "GET", BASE)
    assert status == 200 and doc["retention"] is True and doc["consent"]["video"] is False
    assert doc["entries"] == [{"entry_id": ENTRY, "name": ENTRY, "takes": 2, "synthetic": False, "latest": {"take": 2, "at": "2026-10-31T18:23:16Z", "score": 77, "grade": "C",
        "shown": {"letter": "C", "figures": "77", "caption": "out of 100", "unit": "score", "capped": False, "warning": [],
                   "measure": 77}}}]  # one-letter.md
    status, doc = _json(seeded, "GET", f"{BASE}/{ENTRY}")
    assert status == 200 and doc["can_compare"] is True and doc["report"] == "none" and doc["name"] == ENTRY  # the catalog stub names none: the id
    assert [(t["take"], t["job_id"], t["score"]) for t in doc["takes"]] == [(1, FIRST, 100), (2, SECOND, 77)]
    assert doc["takes"][0]["clip"] == f"{BASE}/{ENTRY}/takes/{FIRST}/clip.mp4" and doc["facts"]["measures"][0]["status"] == "new"
    assert "analysis" not in doc["takes"][0] and str(seeded.app.state) not in json.dumps(doc)  # no server paths
    assert _json(seeded, "GET", f"{BASE}/Bad_Entry")[0] == 404 and _json(seeded, "GET", f"{BASE}/nothing-here")[0] == 404


def test_report_codes(seeded: Api, world: World, monkeypatch: pytest.MonkeyPatch) -> None:  # AC-3
    path = f"{BASE}/{ENTRY}/report"
    world.opted_in.discard(USER)
    assert _json(seeded, "POST", path)[0] == 409
    world.opted_in.add(USER)
    assert _json(seeded, "GET", path)[0] == 404  # no report yet
    world.answers.append(ANSWER)
    status, headers, body = seeded.request("POST", path, headers={**_as(USER), "Origin": f"http://127.0.0.1:{seeded.port}", "Content-Type": "application/json"})
    assert status == 202 and headers["retry-after"] == "5" and json.loads(body)["status"] in ("queued", "running")
    assert _json(seeded, "GET", f"{BASE}/{ENTRY}")[1]["report"] in ("queued", "running", "ready")
    assert history_report.runner_for(seeded.app.state, seeded.app.child.catalog_dir).wait_idle(20)
    status, doc = _json(seeded, "GET", path)
    assert status == 200 and doc["status"] == "ok" and doc["summary"]["text"] == "Take 2 scored 77."
    status, doc = _json(seeded, "POST", path)
    assert status == 200 and doc["status"] == "ok" and len(world.asked) == 1  # 200 from cache
    assert _json(seeded, "GET", f"{BASE}/{ENTRY}")[1]["report"] == "ready"
    # 429: the limit is spent by runs on other keys
    monkeypatch.setenv("SIMON7_HISTORY_DAILY", "1")
    history_store.set_consent(seeded.app.state, USER, True, "v1")
    status, doc = _json(seeded, "POST", path)
    assert status == 429 and "times today" in doc["message"]


def test_report_422_with_fewer_than_two_takes(api: Api, world: World, monkeypatch: pytest.MonkeyPatch) -> None:  # AC-3
    world.install_model(monkeypatch)
    world.opted_in.add(USER)
    folder = seed_job(api.app.state, SECOND, with_video=False)
    world.owners[SECOND] = USER
    history_store.record_take(api.app.state, json.loads((folder / "job.json").read_text()), folder)
    status, doc = _json(api, "POST", f"{BASE}/{ENTRY}/report")
    assert status == 422 and doc["message"].startswith("Record at least 2 takes")
    assert _json(api, "GET", f"{BASE}/{ENTRY}")[1]["can_compare"] is False


def test_fallback_is_a_200_report_never_an_error(seeded: Api, world: World) -> None:  # AC-6 over HTTP
    world.answers.append(sys.modules["part7.history_api"].HistoryError("over the spend cap"))
    assert _json(seeded, "POST", f"{BASE}/{ENTRY}/report")[0] == 202
    assert history_report.runner_for(seeded.app.state, seeded.app.child.catalog_dir).wait_idle(20)
    status, doc = _json(seeded, "GET", f"{BASE}/{ENTRY}/report")
    assert status == 200 and doc["status"] == "fallback" and doc["reason"] == "over the spend cap" and doc["facts"]["takes"]


def test_clip_owner_only_with_range(seeded: Api) -> None:  # AC-7
    path = f"{BASE}/{ENTRY}/takes/{FIRST}/clip.mp4"
    status, headers, body = _get(seeded, path)
    assert status == 200 and headers["content-type"] == "video/mp4" and headers["accept-ranges"] == "bytes" and len(body) > 100
    status, headers, part = _get(seeded, path, headers={"Range": "bytes=0-99"})
    assert status == 206 and part == body[:100] and headers["content-range"] == f"bytes 0-99/{len(body)}"
    assert _get(seeded, path, headers={"Range": f"bytes={len(body) + 5}-"})[0] == 416
    assert _get(seeded, path, OTHER)[0] == 404
    assert _get(seeded, f"{BASE}/{ENTRY}/takes/ffffffffffff/clip.mp4")[0] == 404
    assert _get(seeded, f"{BASE}/{ENTRY}/takes/..%2f..%2fx/clip.mp4")[0] == 404
    (seeded.app.state / "history" / USER / ENTRY / "takes" / SECOND / "clip.mp4").unlink()
    assert _get(seeded, f"{BASE}/{ENTRY}/takes/{SECOND}/clip.mp4")[0] == 404  # a take without a clip
    assert _json(seeded, "GET", f"{BASE}/{ENTRY}")[1]["takes"][1]["clip"] is None


def test_consent_route(seeded: Api) -> None:
    status, doc = _json(seeded, "POST", f"{BASE}/consent", {"video": True, "version": "2026-11"})
    assert status == 200 and doc["video"] is True and doc["version"] == "2026-11"
    assert _json(seeded, "GET", BASE)[1]["consent"]["video"] is True
    for bad in ({"video": "yes", "version": "v1"}, {"video": True}, {"video": True, "version": "a b"}, {}):
        assert _json(seeded, "POST", f"{BASE}/consent", bad)[0] == 400
    assert _json(seeded, "GET", f"{BASE}/consent")[0] == 405
    assert _json(seeded, "POST", f"{BASE}/consent", {"video": False, "version": "2026-11"})[1]["video"] is False


def test_forget_routes(seeded: Api) -> None:
    assert _json(seeded, "DELETE", f"{BASE}/{ENTRY}") == (200, {"removed": 2})
    assert _json(seeded, "GET", f"{BASE}/{ENTRY}")[0] == 404 and _json(seeded, "GET", BASE)[1]["entries"] == []  # ENTRY is not in the catalog stub
    assert _json(seeded, "DELETE", BASE) == (200, {"removed": 0})


def test_forget_all(seeded: Api) -> None:
    assert _json(seeded, "DELETE", BASE) == (200, {"removed": 2})
    assert not (seeded.app.state / "history" / USER).exists()


def test_methods_and_paths(seeded: Api) -> None:
    assert _json(seeded, "PUT", f"{BASE}/{ENTRY}")[0] == 404
    assert _json(seeded, "DELETE", f"{BASE}/{ENTRY}/report")[0] == 405
    assert _json(seeded, "POST", f"{BASE}/{ENTRY}")[0] == 404
    assert _json(seeded, "GET", f"{BASE}/{ENTRY}/nothing/a/b")[0] == 404
    assert seeded.request("GET", "api/me/history/a/b/c/d/e/f/g", headers=_as(USER))[0] != 200  # too deep: not a history route


def test_csrf_every_post_and_delete_needs_a_json_same_origin_request(seeded: Api) -> None:  # B1
    foreign = {"Origin": "http://evil.example", "Content-Type": "application/json"}
    plain = {"Origin": f"http://127.0.0.1:{seeded.port}", "Content-Type": "text/plain"}
    cases = [("POST", f"{BASE}/consent", b'{"video": true, "version": "v1"}'), ("POST", f"{BASE}/{ENTRY}/report", b"{}"),
             ("DELETE", f"{BASE}/{ENTRY}", b""), ("DELETE", BASE, b"")]
    for method, path, body in cases:
        for headers in (foreign, plain, {"Content-Type": "application/json"}):  # foreign Origin, text/plain, no Origin
            status, _, data = seeded.request(method, path, body, {**_as(USER), **headers})
            assert (method, path, status) == (method, path, 403), headers
            assert json.loads(data)["message"] == "This request came from another site."
    assert history_store.consent(seeded.app.state, USER)["video"] is False  # nothing changed
    assert len(history_store.takes(seeded.app.state, USER, ENTRY)) == 2
    assert _json(seeded, "POST", f"{BASE}/consent", {"video": True, "version": "v1"})[0] == 200  # the page's own request passes
