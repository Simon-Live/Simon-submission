"""The analysis API in live mode without the key file (docs/specs/journey-followup.md Error Cases, AC-P01, ADR-0008).

Live mode makes `muse-spark` the default phrasing. A server in live mode that has no key file does not offer it,
yet a request that names no backend must not be a 400: it is analysed with the template and every fault says
`no key`. A visitor who names `muse-spark` on such a server still gets the 400 (tests/test_api.py).

The listing's `phrasing_default` is the wording the page preselects (viewer.md AC-V19): Muse Spark in live mode with a
key file, the template otherwise. The key file in those tests is a temp file; nothing reads it.
"""
import json
from pathlib import Path

import pytest

from part5 import api

ROOT = Path(__file__).resolve().parent.parent
LABELS = json.loads((ROOT / "fixtures/input/followers/labels.json").read_text())
FOOT = next(t["take_id"] for t in LABELS["takes"]
            if t["take_id"].startswith("exercise_front_good_03_foot_out-right"))


def analyse(client="local", **extra):
    body = json.dumps({"expected": {"sample": "exercise"}, "follower": {"sample": FOOT}, **extra}).encode()
    status, _, out = api.handle("POST", "/api/analyse", body, base_path="/", client=client)
    return status, json.loads(out)


@pytest.fixture
def live_without_a_key(monkeypatch):
    monkeypatch.setenv("META_LIVE", "1")   # the key file is missing: tests/conftest.py points it at nothing
    monkeypatch.setattr(api, "_MUSE_LIMIT", api.ClientLimit())


def test_live_mode_without_a_key_does_not_offer_muse_spark(live_without_a_key):
    assert api.offered_phrasing() == ["template"]


def test_a_request_without_phrasing_is_analysed_with_the_template_and_says_no_key(live_without_a_key):
    status, body = analyse()
    assert status == 200
    record = body["analysis"]["phrasing"]
    assert (record["requested"], record["selected_by"], record["backend"]) == ("muse-spark", "live", "template")
    assert record["fallback_reason"] == "no key"
    faults = body["analysis"]["faults"]
    assert faults and [e["fallback_reason"] for e in record["faults"]] == ["no key"] * len(faults)
    assert all(f["coaching"] == f["text_timed"] for f in faults)


def test_the_scored_fields_equal_those_of_a_template_run(live_without_a_key):
    live = analyse()[1]["analysis"]
    template = analyse(phrasing="template")[1]["analysis"]
    assert template["phrasing"]["selected_by"] == "flag"
    for key in ("faults", "score", "insights", "status", "diagnostics"):
        assert live[key] == template[key], key


def test_a_request_that_makes_no_model_call_does_not_use_the_per_client_limit(live_without_a_key):
    statuses = [analyse(client="198.51.100.7")[0] for _ in range(api.MUSE_PER_MINUTE + 2)]
    assert statuses == [200] * (api.MUSE_PER_MINUTE + 2)


def test_naming_muse_spark_on_a_server_that_cannot_run_it_is_still_a_400(live_without_a_key):
    status, body = analyse(phrasing="muse-spark")
    assert status == 400 and body["error"]["field"] == "phrasing"
    assert "template" in body["error"]["message"]


def test_without_live_mode_a_request_without_phrasing_stays_the_template_default():
    status, body = analyse()
    record = body["analysis"]["phrasing"]
    assert status == 200 and (record["requested"], record["selected_by"]) == ("template", "default")


# ----------------------------------------------------------------------------- the default wording (AC-V19, ADR-0008)

def samples_listing():
    status, _, out = api.handle("GET", "/api/samples", b"", base_path="/")
    assert status == 200
    return json.loads(out)


@pytest.fixture
def fake_key_file(monkeypatch, tmp_path):
    """A key file that only has to exist: the listing never reads it, and no test here makes a model call."""
    key = tmp_path / "BASETEN_API_KEY"
    key.write_text("not-a-real-key\n")
    monkeypatch.setenv("PART5_BASETEN_KEY_FILE", str(key))
    return key


def test_live_mode_with_a_key_file_offers_muse_spark_and_names_it_the_default(fake_key_file, monkeypatch):
    monkeypatch.setenv("META_LIVE", "1")
    listing = samples_listing()
    assert "muse-spark" in listing["phrasing"] and "template" in listing["phrasing"]
    assert listing["phrasing_default"] == "muse-spark"
    assert listing["phrasing_default"] in listing["phrasing"]


def test_the_default_wording_follows_the_flag_that_turns_live_mode_on(fake_key_file, monkeypatch):
    monkeypatch.setenv("SIMON5_LIVE", "1")
    assert samples_listing()["phrasing_default"] == "muse-spark"


def test_live_mode_without_a_key_file_names_the_template_the_default(live_without_a_key):
    listing = samples_listing()
    assert listing["phrasing"] == ["template"]
    assert listing["phrasing_default"] == "template"


def test_without_live_mode_the_template_is_the_default_even_when_a_key_file_exists(fake_key_file):
    listing = samples_listing()
    assert "muse-spark" not in listing["phrasing"]   # a key alone does not turn live mode on
    assert listing["phrasing_default"] == "template"


def test_without_live_mode_and_without_a_key_file_the_template_is_the_default():
    assert samples_listing()["phrasing_default"] == "template"


def test_the_default_is_always_one_of_the_wordings_on_offer(fake_key_file, monkeypatch):
    for live in ("1", "0"):
        monkeypatch.setenv("META_LIVE", live)
        listing = samples_listing()
        assert listing["phrasing_default"] in listing["phrasing"]


def test_the_default_is_the_backend_a_request_without_phrasing_would_run(fake_key_file, monkeypatch):
    """Listing and analysis agree: what the page preselects is what a request that names nothing gets."""
    monkeypatch.setenv("META_LIVE", "1")
    monkeypatch.setattr(api, "_MUSE_LIMIT", api.ClientLimit())
    monkeypatch.setattr(api, "_in_worker", lambda fn, *a: {"phrasing": a[2], "selected_by": a[3]})
    status, _, out = api.handle("POST", "/api/analyse", json.dumps(
        {"expected": {"sample": "exercise"}, "follower": {"sample": FOOT}}).encode(), base_path="/")
    ran = json.loads(out)
    assert status == 200
    assert ran["phrasing"] == samples_listing()["phrasing_default"] and ran["selected_by"] == "live"


def test_the_listing_never_carries_the_key(fake_key_file, monkeypatch):
    monkeypatch.setenv("META_LIVE", "1")
    _, _, raw = api.handle("GET", "/api/samples", b"", base_path="/")
    assert b"not-a-real-key" not in raw and str(fake_key_file).encode() not in raw
