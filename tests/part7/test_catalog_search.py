"""GET api/catalog/search: every option, pagination, stability, visibility, policy and bad input
(docs/specs/catalog-search.md, AC-S1 to AC-S12, TICKET-440). Real app, real routes, a stub Part 6 list."""

from __future__ import annotations

import json
from pathlib import Path
import re
import time
from typing import Any
from urllib.parse import quote

import pytest

from auth_support import authenv, sign_in  # noqa: F401  authenv is a fixture
from part7 import auth, catalog_search as cs, catalog_search_routes as routes, entry_access, prod_mode, source_credit
from part7 import labels
from support import Api, published

pytestmark = pytest.mark.usefixtures("authenv")
ROOT = Path(__file__).resolve().parents[2]


def entry(entry_id: str, name: str | None = None, **more: Any) -> dict[str, Any]:
    base = {"id": entry_id, "name": name or entry_id, "category": "exercise", "duration_ms": 20_000,
            "created_at": "2026-10-01T00:00:00Z", "video_uri": None, "animation": "animation.json", "files_source": "mock"}
    return {**base, **more}


def seed(api: Api, *entries: dict[str, Any], tags: dict[str, list[str]] | None = None, private: tuple[str, ...] = ()) -> None:
    api.app.child.entries = {e["id"]: e for e in entries}
    published(api.app.state, *[i for i in api.app.child.entries if i not in private])
    for entry_id, tag_list in (tags or {}).items():
        labels.save(api.app.state, entry_id, labels.validate({"tags": tag_list}))


def search(api: Api, qs: str = "", cookie: str | None = None) -> tuple[int, dict[str, Any]]:
    head = {"Cookie": f"{auth.COOKIE}={cookie}"} if cookie else {}
    status, _, data = api.request("GET", "api/catalog/search" + (f"?{qs}" if qs else ""), None, head)
    return status, json.loads(data)


def ids(doc: dict[str, Any]) -> list[str]:
    return [e["id"] for e in doc["entries"]]


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SIMON7_DEFAULT_PROFILE", raising=False)
    monkeypatch.delenv("FIRM_ENV", raising=False)


@pytest.fixture()
def library(api: Api) -> Api:
    seed(
        api,
        entry("squat-a1", "Bodyweight squat", created_at="2026-10-03T00:00:00Z", duration_ms=10_000, video_uri="v.mp4"),
        entry("step-b2", "Step touch", category="dance", created_at="2026-10-02T00:00:00Z", duration_ms=30_000),
        entry("calf-c3", "Calf raise", created_at="2026-10-01T00:00:00Z", duration_ms=60_000, animation=None),
        entry("loose-d4", "Loose move", category=None, created_at="2026-09-01T00:00:00Z", duration_ms=None),
        tags={"squat-a1": ["legs", "home"], "step-b2": ["cardio"], "calf-c3": ["rehab", "legs"]},
    )
    return api


# ----- AC-S1 the reply ------------------------------------------------------------------------------------
def test_default_lists_newest_first_with_totals_and_computed_fields(library: Api) -> None:
    status, doc = search(library)
    assert status == 200 and doc["ok"] is True
    assert ids(doc) == ["squat-a1", "step-b2", "calf-c3", "loose-d4"]
    assert (doc["total"], doc["page"], doc["per_page"], doc["pages"], doc["sort"]) == (4, 1, 24, 1, "newest")
    first = doc["entries"][0]
    assert first["name"] == "Bodyweight squat" and first["types"] == ["exercise"] and first["tags"] == ["legs", "home"]
    assert first["has"] == ["model", "video"] and first["duration_bucket"] == "short" and first["takes"] == 0
    assert doc["types_offered"] == ["exercise", "dance", "rehab"]


def test_the_route_answers_no_store_and_refuses_other_methods(library: Api) -> None:
    status, head, _ = library.request("GET", "api/catalog/search")
    assert status == 200 and head["cache-control"] == "no-store"
    assert library.request("POST", "api/catalog/search", b"{}", {"Content-Type": "application/json"})[0] in (403, 405)


# ----- AC-S2 text search ---------------------------------------------------------------------------------
@pytest.mark.parametrize(("q", "want"), [
    ("squat", ["squat-a1"]), ("SQUAT", ["squat-a1"]), ("  step   TOUCH ", ["step-b2"]), ("cardio", ["step-b2"]),
    ("legs", ["squat-a1", "calf-c3"]), ("ca", ["calf-c3", "step-b2"]), ("nothing-here", []),
])
def test_text_matches_title_and_tags_case_insensitively_with_all_terms(library: Api, q: str, want: list[str]) -> None:
    status, doc = search(library, f"q={quote(q)}")
    assert status == 200
    assert sorted(ids(doc)) == sorted(want)


def test_a_term_must_be_in_the_movement(library: Api) -> None:
    assert ids(search(library, "q=squat+cardio")[1]) == []


@pytest.mark.parametrize("q", [".*", "(", "[a-", "\\", "%00", "a" * 60, "'; DROP TABLE x;--", "‮"])
def test_input_is_never_a_pattern(library: Api, q: str) -> None:
    status, doc = search(library, f"q={quote(q)}")
    assert status == 200 and doc["total"] == 0


def test_accents_and_width_fold(api: Api) -> None:
    seed(api, entry("cafe-1", "Café stretch"), entry("full-1", "Ｓquat wide"))
    assert ids(search(api, "q=cafe%CC%81")[1]) == ["cafe-1"]  # decomposed accent matches the composed name
    assert ids(search(api, "q=squat")[1]) == ["full-1"]  # fullwidth S


def test_credit_is_searched(api: Api) -> None:
    sid = sign_in(api)
    seed(api, entry("clip-1", "Plain clip"), entry("clip-2", "Other clip"))
    store = auth.identity(api.app)
    source_credit.put(store, "entry", "clip-1", "u-1", {"title": "Morning flow", "creator": "Ada Pexels", "licence": "CC0",
                                                       "licence_other": "", "url": ""})
    assert ids(search(api, "q=pexels", sid)[1]) == ["clip-1"]
    assert ids(search(api, "q=morning+ada")[1]) == ["clip-1"]


def test_relevance_orders_a_word_match_over_a_buried_one_over_a_tag_with_a_title_tiebreak(api: Api) -> None:
    seed(api, entry("a-1", "Deep squat hold"), entry("b-1", "Squatting basics"), entry("c-1", "Wall sit"),
         entry("d-1", "Resquat drill"), tags={"c-1": ["squat"]})
    doc = search(api, "q=squat")[1]
    assert doc["sort"] == "relevance"
    assert ids(doc) == ["a-1", "b-1", "d-1", "c-1"]  # word start (a, b tie: title order), inside a word, tag only
    assert search(api, "q=squat&sort=title")[1]["sort"] == "title"


# ----- AC-S3 type -----------------------------------------------------------------------------------------
def test_type_filters_one_or_several_and_rehab_follows_the_tag(library: Api) -> None:
    assert ids(search(library, "type=dance")[1]) == ["step-b2"]
    assert ids(search(library, "type=rehab")[1]) == ["calf-c3"]
    assert sorted(ids(search(library, "type=dance,rehab")[1])) == ["calf-c3", "step-b2"]
    doc = search(library, "type=exercise")[1]
    assert sorted(ids(doc)) == ["calf-c3", "squat-a1"]  # a rehab-tagged exercise is also an exercise (web kind.js)
    calf = next(e for e in doc["entries"] if e["id"] == "calf-c3")
    assert calf["types"] == ["exercise", "rehab"]


def test_a_movement_with_no_category_has_no_type_and_shows_only_without_a_type_filter(library: Api) -> None:
    assert "loose-d4" in ids(search(library)[1])
    for t in ("exercise", "dance", "rehab"):
        assert "loose-d4" not in ids(search(library, f"type={t}")[1])
    assert next(e for e in search(library)[1]["entries"] if e["id"] == "loose-d4")["types"] == []


# ----- AC-S4 policy ---------------------------------------------------------------------------------------
def test_rehab_off_hides_the_type_everywhere(library: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(prod_mode, "policy", lambda name: name != "rehab")
    status, doc = search(library, "type=rehab")
    assert status == 400 and doc["error"] == cs.MSG_REHAB
    doc = search(library)[1]
    assert doc["types_offered"] == ["exercise", "dance"] and doc["facets"]["type"]["rehab"] == 0
    assert all("rehab" not in e["types"] for e in doc["entries"])
    assert "calf-c3" in ids(search(library, "type=exercise")[1])  # still an exercise, as the web lists it


# ----- AC-S5 sorts ----------------------------------------------------------------------------------------
def test_sorts(library: Api) -> None:
    assert ids(search(library, "sort=title")[1]) == ["squat-a1", "calf-c3", "loose-d4", "step-b2"]
    assert ids(search(library, "sort=newest")[1]) == ["squat-a1", "step-b2", "calf-c3", "loose-d4"]
    assert ids(search(library, "sort=duration")[1]) == ["squat-a1", "step-b2", "calf-c3", "loose-d4"]  # unknown last


def test_title_sort_is_alphabetical_ignoring_case(api: Api) -> None:
    seed(api, entry("z-1", "zebra walk"), entry("a-1", "Apple press"), entry("m-1", "mid step"))
    assert ids(search(api, "sort=title")[1]) == ["a-1", "m-1", "z-1"]


def test_popular_counts_finished_follow_takes_with_newest_as_tiebreak(library: Api) -> None:
    def done(entry_id: str, n: int, kind: str = "follow") -> None:
        for _ in range(n):
            rec = library.app.queue.submit(kind, lambda ctx: {"result": {}}, entry_id=entry_id)
            assert library.app.queue.wait(rec["id"], 10)["status"] == "done"
    done("calf-c3", 3)
    done("step-b2", 1)
    done("loose-d4", 5, kind="trainer")  # a trainer job is not a follow take
    doc = search(library, "sort=popular")[1]
    assert ids(doc) == ["calf-c3", "step-b2", "squat-a1", "loose-d4"]
    assert [e["takes"] for e in doc["entries"]] == [3, 1, 0, 0]


def test_unknown_sort_is_refused(library: Api) -> None:
    status, doc = search(library, "sort=random")
    assert status == 400 and "Unknown sort" in doc["error"]


# ----- AC-S6 duration -------------------------------------------------------------------------------------
@pytest.mark.parametrize(("ms", "want"), [
    (1, "short"), (14_999, "short"), (15_000, "medium"), (45_000, "medium"), (45_001, "long"), (0, "unknown"),
    (None, "unknown"), (-5, "unknown"), ("20", "unknown"), (True, "unknown"),
])
def test_duration_buckets_and_their_edges(ms: Any, want: str) -> None:
    assert cs.bucket(ms) == want


def test_duration_filter_and_combination(library: Api) -> None:
    assert ids(search(library, "duration=short")[1]) == ["squat-a1"]
    assert ids(search(library, "duration=medium")[1]) == ["step-b2"]
    assert ids(search(library, "duration=long")[1]) == ["calf-c3"]
    assert sorted(ids(search(library, "duration=short,long")[1])) == ["calf-c3", "squat-a1"]
    assert ids(search(library, "duration=short,medium,long&type=dance")[1]) == ["step-b2"]


# ----- AC-S7 has and tag ------------------------------------------------------------------------------------
def test_has_video_model_and_board(library: Api) -> None:
    from part7 import challenges

    published(library.app.state, "step-b2")
    challenges.create(library.app.state, entry_id="step-b2", title="Beat my step", creator_name="Sam", kind="friend")
    assert ids(search(library, "has=video")[1]) == ["squat-a1"]
    assert sorted(ids(search(library, "has=model")[1])) == ["loose-d4", "squat-a1", "step-b2"]
    assert ids(search(library, "has=board")[1]) == ["step-b2"]
    assert ids(search(library, "has=video,board")[1]) == []  # all named must hold


def test_tag_filter_needs_every_tag(library: Api) -> None:
    assert sorted(ids(search(library, "tag=legs")[1])) == ["calf-c3", "squat-a1"]
    assert ids(search(library, "tag=legs,home")[1]) == ["squat-a1"]
    assert ids(search(library, "tag=LEGS,rehab")[1]) == ["calf-c3"]


# ----- AC-S8 visibility ---------------------------------------------------------------------------------------
def test_a_private_movement_is_listed_to_its_owner_only(api: Api) -> None:
    a, b = sign_in(api), sign_in(api, "grace.hopper@example.com")
    owner = auth_user(api, a)
    seed(api, entry("open-1", "Open one"), entry("mine-2", "Mine two"), entry("theirs-3", "Theirs three"),
         private=("mine-2", "theirs-3"))
    entry_access.record(api.app.state, "mine-2", owner=owner, published=False, age_band="adult")
    entry_access.record(api.app.state, "theirs-3", owner="someone-else", published=False, age_band="adult")
    assert ids(search(api)[1]) == ["open-1"]  # signed out
    assert sorted(ids(search(api, cookie=b)[1])) == ["open-1"]  # another account
    assert sorted(ids(search(api, cookie=a)[1])) == ["mine-2", "open-1"]
    doc = search(api, "mine=1", a)[1]
    assert ids(doc) == ["mine-2"] and doc["total"] == 1 and doc["entries"][0]["mine"] is True
    assert search(api, "q=theirs", a)[1]["total"] == 0 and search(api, "q=theirs", a)[1]["facets"]["type"]["exercise"] == 0


def test_private_movements_stay_out_of_facets_and_tags(api: Api) -> None:
    seed(api, entry("open-1", "Open one"), entry("priv-2", "Private two", category="dance"), tags={"priv-2": ["secret-tag"]}, private=("priv-2",))
    entry_access.record(api.app.state, "priv-2", owner="someone-else", published=False, age_band="adult")
    doc = search(api)[1]
    assert doc["facets"]["type"]["dance"] == 0 and "secret-tag" not in doc["facets"]["tag"]


def test_an_unrecorded_movement_is_shown_to_nobody(api: Api) -> None:
    seed(api, entry("open-1", "Open one"))
    api.app.child.entries["ghost-9"] = entry("ghost-9", "No access row")  # no row, not a shipped sample (W-N1)
    assert ids(search(api)[1]) == ["open-1"]


def test_mine_needs_a_signed_in_caller(library: Api) -> None:
    status, doc = search(library, "mine=1")
    assert status == 401 and doc["error"] == routes.MSG_MINE
    assert search(library, "mine=0")[0] == 200


# ----- AC-S9 test entries and the judge profile -------------------------------------------------------------------
TESTERS = [entry("qa-journey-qamvxvd3y", "Journey squat"), entry("verify-2026-11-02-aa", "Verify run squat"),
           entry("flagged-1", "Flagged squat", test=True), entry("tagged-1", "Tagged squat"), entry("arm-salute", "Arm salute squat")]


def with_testers(api: Api) -> None:
    seed(api, entry("real-1", "Real squat"), *TESTERS, tags={"tagged-1": ["check7"]})


def test_test_entries_are_not_listed_but_a_search_finds_them_outside_prod(api: Api) -> None:
    with_testers(api)
    assert ids(search(api)[1]) == ["real-1"]
    assert ids(search(api, "type=exercise")[1]) == ["real-1"]
    assert sorted(ids(search(api, "q=squat")[1])) == sorted(["real-1", "qa-journey-qamvxvd3y", "verify-2026-11-02-aa", "flagged-1",
                                                           "tagged-1", "arm-salute"])


def test_in_prod_a_test_entry_is_never_listed_even_by_name(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    with_testers(api)
    monkeypatch.setattr(prod_mode, "is_prod", lambda: True)
    assert ids(search(api, "q=squat")[1]) == ["real-1"]
    assert search(api, "q=journey")[1]["total"] == 0


def test_the_judge_profile_lists_curated_movements_with_a_video_or_the_owners_own(api: Api) -> None:
    sid = sign_in(api)
    seed(api, entry("squat-1a2b", "Squat", video_uri="v.mp4"), entry("arm-wave", "Wave", video_uri=None),
         entry("uncurated-1", "Other", video_uri="v.mp4"), entry("own-1", "Own thing"))
    entry_access.record(api.app.state, "own-1", owner=auth_user(api, sid), published=True, age_band="adult")
    assert ids(search(api, "profile=submission")[1]) == ["squat-1a2b"]
    assert sorted(ids(search(api, "profile=submission", sid)[1])) == ["own-1", "squat-1a2b"]
    assert len(ids(search(api, "profile=default")[1])) == 4


def test_the_server_default_profile_applies_without_the_option(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    seed(api, entry("squat-1a2b", "Squat", video_uri="v.mp4"), entry("uncurated-1", "Other", video_uri="v.mp4"))
    monkeypatch.setenv("SIMON7_DEFAULT_PROFILE", "submission")
    assert ids(search(api)[1]) == ["squat-1a2b"]
    assert len(ids(search(api, "profile=default")[1])) == 2  # the page's own choice wins, as in flags.js


def test_curation_lists_match_the_web(api: Api) -> None:
    js = (ROOT / "web" / "curation.js").read_text(encoding="utf-8")
    curated = re.findall(r'"([a-z0-9-]+)"', "".join(re.findall(r"CURATED(?: = \[|\.push\()(.*?)[\])];", js, re.S)))
    assert tuple(curated) == routes.CURATED
    assert re.search(r'HIDDEN_IDS = \["arm-salute"\]', js) and routes.HIDDEN_IDS == ("arm-salute",)
    assert "verify|check-7" in js and routes.TEST_NAME.pattern == r"^(verify|check-7)\b"
    assert re.search(r'TEST_TAGS = \["verify", "check7", "check-7"\]', js)


# ----- AC-S10 pagination ------------------------------------------------------------------------------------
def crowd(api: Api, n: int = 50) -> None:
    # equal durations and equal dates for most: only the tiebreak keeps the order
    seed(api, *[entry(f"move-{i:03d}", f"Move {i % 7}", created_at="2026-10-01T00:00:00Z" if i % 3 else "2026-10-02T00:00:00Z",
                      duration_ms=20_000 if i % 4 else 5_000) for i in range(n)])


@pytest.mark.parametrize("sort", ["newest", "title", "duration", "popular", "relevance"])
@pytest.mark.parametrize("per_page", [12, 24, 48])
def test_walking_every_page_repeats_and_skips_nothing(api: Api, sort: str, per_page: int) -> None:
    crowd(api)
    first = search(api, f"sort={sort}&per_page={per_page}")[1]
    walked: list[str] = []
    for page in range(1, first["pages"] + 1):
        doc = search(api, f"sort={sort}&per_page={per_page}&page={page}")[1]
        assert doc["total"] == 50 and doc["page"] == page
        walked += ids(doc)
    assert len(walked) == 50 and len(set(walked)) == 50
    assert walked == [e for p in range(1, first["pages"] + 1) for e in ids(search(api, f"sort={sort}&per_page={per_page}&page={p}")[1])]


def test_page_counts_and_boundaries(api: Api) -> None:
    crowd(api, 25)
    doc = search(api, "per_page=12")[1]
    assert (doc["total"], doc["pages"], len(doc["entries"])) == (25, 3, 12)
    assert len(search(api, "per_page=12&page=3")[1]["entries"]) == 1
    past = search(api, "per_page=12&page=4")[1]
    assert (past["entries"], past["total"], past["pages"], past["page"]) == ([], 25, 3, 4)
    exact = search(api, "per_page=24&page=1")[1]
    assert exact["pages"] == 2 and len(exact["entries"]) == 24
    assert search(api, "per_page=48")[1]["pages"] == 1


def test_an_empty_result_has_no_pages(api: Api) -> None:
    seed(api)
    doc = search(api)[1]
    assert (doc["entries"], doc["total"], doc["pages"]) == ([], 0, 0)
    assert search(api, "page=2")[1]["entries"] == []


def test_order_is_the_same_on_every_call(api: Api) -> None:
    crowd(api)
    one = ids(search(api, "sort=title&per_page=48")[1])
    api.app.child.entries = dict(reversed(list(api.app.child.entries.items())))  # Part 6 may list in any order
    assert ids(search(api, "sort=title&per_page=48")[1]) == one


# ----- AC-S11 facets ---------------------------------------------------------------------------------------
def test_facets_count_with_every_filter_except_their_own(library: Api) -> None:
    all_f = search(library)[1]["facets"]
    assert all_f["type"] == {"exercise": 2, "dance": 1, "rehab": 1}
    assert all_f["duration"] == {"short": 1, "medium": 1, "long": 1, "unknown": 1}
    assert all_f["has"] == {"video": 1, "model": 3, "board": 0}
    assert all_f["tag"] == {"legs": 2, "cardio": 1, "home": 1, "rehab": 1}
    doc = search(library, "type=dance")[1]
    assert doc["total"] == 1
    assert doc["facets"]["type"] == {"exercise": 2, "dance": 1, "rehab": 1}  # its own filter is left out
    assert doc["facets"]["duration"] == {"short": 0, "medium": 1, "long": 0, "unknown": 0}  # the others apply
    doc = search(library, "type=exercise&duration=long&has=video")[1]
    assert doc["total"] == 0
    assert doc["facets"]["type"]["exercise"] == 0  # exercise movements that are long and have video: none
    assert doc["facets"]["duration"]["short"] == 1 and doc["facets"]["duration"]["long"] == 0
    assert doc["facets"]["has"]["video"] == 0 and doc["facets"]["has"]["model"] == 0  # the long exercise is the calf raise: no video, no model


def test_facets_follow_the_text(library: Api) -> None:
    doc = search(library, "q=squat")[1]
    assert doc["facets"]["type"] == {"exercise": 1, "dance": 0, "rehab": 0}


def test_facets_count_the_whole_result_not_the_page(api: Api) -> None:
    crowd(api)
    doc = search(api, "per_page=12")[1]
    assert len(doc["entries"]) == 12 and doc["facets"]["type"]["exercise"] == 50


# ----- AC-S12 bad input -------------------------------------------------------------------------------------
@pytest.mark.parametrize("qs", [
    "type=pilates", "duration=forever", "has=audio", "page=0", "page=-1", "page=abc", "page=1.5", "page=100001", "page=1&page=2",
    "per_page=13", "per_page=0", "per_page=99", "per_page=abc", "sort=", "sort=;", "mine=yes", "tag=Bad%20Tag", "tag=" + "a" * 25,
    "tag=" + ",".join(f"t{i}" for i in range(9)), "q=" + "a" * 101, "q=" + "+".join("w" * 3 for _ in range(9)),
    "q=" + "w" * 65, "bogus=1", "profile=other", "level=beginner", "type=exercise&type=dance",
])
def test_bad_options_answer_400_with_a_plain_line(library: Api, qs: str) -> None:
    if qs == "sort=":
        assert search(library, qs)[0] == 200  # a blank sort is the default
        return
    status, doc = search(library, qs)
    assert status == 400 and doc["ok"] is False
    assert doc["error"] and doc["error"] == doc["message"] and "Traceback" not in doc["error"] and len(doc["error"]) < 120


def test_empty_options_are_the_default(library: Api) -> None:
    assert search(library, "q=&type=&sort=&duration=&has=&tag=&mine=&page=&per_page=")[1]["total"] == 4
    assert search(library, "_=12345")[0] == 200  # a cache-buster passes


# ----- the pure module -----------------------------------------------------------------------------------------
def test_parse_defaults_and_sort_default_follows_the_text() -> None:
    assert cs.parse("").sort == "newest" and cs.parse("q=x").sort == "relevance" and cs.parse("q=x&sort=title").sort == "title"
    assert cs.parse("").per_page == 24 and cs.parse("").page == 1


def test_a_hundred_thirty_entry_catalog_answers_fast(api: Api) -> None:
    seed(api, *[entry(f"move-{i:04d}", f"Movement number {i}", duration_ms=1000 * (i % 70), created_at=f"2026-10-{1 + i % 28:02d}T00:00:00Z")
                for i in range(130)])
    start = time.perf_counter()
    status, doc = search(api, "q=movement&sort=popular&type=exercise&has=model&per_page=24&page=3")
    assert status == 200 and doc["total"] == 130
    assert time.perf_counter() - start < 1.0


def auth_user(api: Api, sid: str) -> str:
    from auth_support import get

    return get(api, "api/auth/me", cookie=sid)[2]["user_id"]
