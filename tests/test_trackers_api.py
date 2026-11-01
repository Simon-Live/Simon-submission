"""Tracker registry, the SAM 3.1 API tracker and the budget (docs/specs/tracker-registry.md): the api-sam31 shape and
provenance (AC-R04, AC-R05, TICKET-047), the order and fallback of the registry (AC-R08) and the spend caps (AC-R09).

Split from tests/test_trackers.py (800-line limit); the fixtures and helpers are that file's, imported here."""
import json
import os

import pytest
from test_trackers import (  # noqa: F401  (env is a fixture)
    MASK, _no_network, api_client, check_shape, env, fake_tracker, ledger_line, make_frames, put_key)

from part2 import backends, meta_api, track, trackers
from part2.trackers import api_sam31


# --- AC-R04 and AC-R05: the api-sam31 shape and provenance --------------------------------------

def test_api_sam31_shape_and_provenance(env, monkeypatch, tmp_path):
    put_key(env.keys, "MODEL_API_KEY")
    monkeypatch.setattr(track, "load_sam31_tracker", lambda: api_client([]))
    d, recs = make_frames(tmp_path, start=10)
    doc = track.track(d, tmp_path / "t.json", tracker="api-sam31")
    check_shape(doc, recs)
    assert [p["id"] for f in doc["frames"] for p in f["people"]] == [0, 1, 0, 1]  # 5 -> 0, 2 -> 1
    prov = doc["provenance"]
    assert prov["tracker"] == "api-sam31" and prov["models"][0]["name"] == "sam-3.1"
    assert prov["mask_source"] == "sam" and prov["spend_usd"] == round(meta_api.sam_video_cost(4), 4)
    assert json.loads((tmp_path / "t.json").read_text()) == doc


@pytest.mark.parametrize("nobody", [lambda recs: {}, lambda recs: {r["frame"]: [] for r in recs}],
                         ids=["no frame listed", "every frame empty"])
def test_api_sam31_that_finds_nobody_raises_no_person_and_keeps_the_spend(env, tmp_path, nobody):
    """TICKET-047: the API charged for the call whatever it found, so spend_usd is set before NoPerson is raised."""
    put_key(env.keys, "MODEL_API_KEY")
    d, recs = make_frames(tmp_path, start=10)
    t = api_sam31.ApiSam31(client=lambda frames_dir, records, budget=None: nobody(records))
    with pytest.raises(trackers.NoPerson, match="^no person found to track$") as e:
        t.track(d, tmp_path / "t.json")
    assert isinstance(e.value, backends.NoPersonFound) and e.value.exit_code == 4
    assert t.spend_usd == api_sam31.ApiSam31.estimate(len(recs)) > 0
    assert not (tmp_path / "t.json").exists()


def test_api_sam31_with_one_person_in_one_frame_still_returns(env, tmp_path):
    put_key(env.keys, "MODEL_API_KEY")
    d, recs = make_frames(tmp_path, start=10)
    person = {"id": 3, "bbox": [1, 1, 2, 2], "mask": MASK, "confidence": 0.9}
    t = api_sam31.ApiSam31(client=lambda frames_dir, records, budget=None: {records[1]["frame"]: [person]})
    doc = t.track(d, tmp_path / "t.json")
    check_shape(doc, recs)
    assert [len(f["people"]) for f in doc["frames"]] == [0, 1, 0, 0]
    assert doc["provenance"]["spend_usd"] == round(api_sam31.ApiSam31.estimate(len(recs)), 4)


# --- AC-R08: order and fallback ---------------------------------------------------------------------

def test_scored_order_without_key_falls_back_to_local_open(env, monkeypatch, tmp_path):
    calls = []
    monkeypatch.setitem(trackers._REGISTRY, "local-open", fake_tracker("local-open", calls))
    monkeypatch.setattr(track, "load_sam31_tracker", lambda: _no_network)
    d, _ = make_frames(tmp_path)
    prov = track.track(d, tmp_path / "t.json", purpose="scored")["provenance"]
    assert (prov["tracker"], prov["fallback_from"], prov["fallback_reason"]) == ("local-open", "api-sam31", "no_key")
    assert trackers.describe_fallback(prov) == "no key for SAM 3.1; tracked with local-open"


def test_bulk_order_skips_a_step_whose_packages_are_missing(env, monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(trackers, "parity_passed", lambda: True)
    monkeypatch.setitem(trackers._REGISTRY, "local-sam31",
                        fake_tracker("local-sam31", calls, ok=(False, "missing sam3, torch")))
    monkeypatch.setitem(trackers._REGISTRY, "api-sam31", fake_tracker("api-sam31", calls))
    t, skipped = trackers.resolve("bulk")
    assert (t.name, skipped) == ("api-sam31", [("local-sam31", "no_env")])
    with pytest.raises(Exception):
        trackers.select("local-sam31")
    assert trackers.describe_fallback({"tracker": "api-sam31", "fallback_reason": "no_env"}) == \
        "local SAM 3.1 is not installed here; tracked with api-sam31"


def test_exhausted_budget_falls_back_and_a_named_tracker_exits(env, monkeypatch, tmp_path):
    put_key(env.keys, "MODEL_API_KEY")
    ledger_line(os.environ["META_SPEND_LEDGER"], 24.995)
    calls = []
    monkeypatch.setitem(trackers._REGISTRY, "local-open", fake_tracker("local-open", calls))
    monkeypatch.setattr(track, "load_sam31_tracker", lambda: _no_network)
    d, _ = make_frames(tmp_path)
    prov = track.track(d, tmp_path / "t.json", purpose="scored")["provenance"]
    assert (prov["tracker"], prov["fallback_reason"]) == ("local-open", "budget")
    with pytest.raises(trackers.BudgetReached) as e:
        track.track(d, tmp_path / "u.json", tracker="api-sam31")
    assert str(e.value) == (f"tracker api-sam31: the spend cap of $25.00 is reached "
                            f"(ledger {os.environ['META_SPEND_LEDGER']})")


def test_bulk_without_parity_skips_local_sam31(env, monkeypatch, tmp_path):
    put_key(env.keys, "MODEL_API_KEY")
    put_key(env.keys, "HF_TOKEN")
    seen = []
    monkeypatch.setattr(track, "load_sam31_tracker", lambda: api_client(seen))
    d, _ = make_frames(tmp_path)
    prov = track.track(d, tmp_path / "t.json")["provenance"]
    assert (prov["tracker"], prov["fallback_from"], prov["fallback_reason"]) == ("api-sam31", "local-sam31",
                                                                                  "no_parity")


def test_bulk_with_a_committed_parity_pass_runs_local_sam31(env, monkeypatch, tmp_path):
    put_key(env.keys, "HF_TOKEN")
    record = tmp_path / "sam31.json"
    record.write_text(json.dumps({"pass": True}))
    monkeypatch.setattr(trackers, "PARITY_FILE", record)
    calls = []
    monkeypatch.setitem(trackers._REGISTRY, "local-sam31", fake_tracker("local-sam31", calls))
    t, skipped = trackers.resolve("bulk")
    assert t.name == "local-sam31" and skipped == []
    record.write_text(json.dumps({"pass": False}))
    assert not trackers.parity_passed()


def test_api_error_with_a_present_key_fails_the_run(env, monkeypatch, tmp_path):
    put_key(env.keys, "MODEL_API_KEY")
    calls = []
    monkeypatch.setitem(trackers._REGISTRY, "local-open", fake_tracker("local-open", calls))

    def down(frames_dir, recs, budget=None):
        raise RuntimeError("Meta API POST /responses: HTTP 503: unavailable")

    monkeypatch.setattr(track, "load_sam31_tracker", lambda: down)
    d, _ = make_frames(tmp_path)
    with pytest.raises(trackers.TrackerError, match="HTTP 503"):
        track.track(d, tmp_path / "t.json", purpose="scored")
    assert calls == []


def test_last_step_unavailable_fails_with_its_reason(env, monkeypatch, tmp_path):
    monkeypatch.setitem(trackers._REGISTRY, "local-open",
                        fake_tracker("local-open", [], ok=(False, "missing sam2")))
    with pytest.raises(trackers.TrackerError, match="tracker local-open needs sam2"):
        trackers.resolve("scored")


# --- AC-R09: spend caps -----------------------------------------------------------------------------

def test_staging_cap_moves_the_job_to_local_open(env, monkeypatch, tmp_path):
    put_key(env.keys, "MODEL_API_KEY")
    staging = tmp_path / "meta_spend_staging.jsonl"
    ledger_line(staging, 9.80)
    monkeypatch.setenv("META_SPEND_LEDGER", str(staging))
    monkeypatch.setenv("META_BUDGET_USD", "10")
    monkeypatch.setenv("PART2_JOB_LEDGER", str(tmp_path / "job" / "spend.jsonl"))
    monkeypatch.setitem(trackers._REGISTRY, "local-open", fake_tracker("local-open", []))
    t, skipped = trackers.resolve("bulk", n_frames=1500)  # $0.30
    assert t.name == "local-open" and ("api-sam31", "budget") in skipped
    d, _ = make_frames(tmp_path)
    doc = t.track(d, tmp_path / "t.json", skipped=[s for s in skipped if s[0] == "api-sam31"])
    assert trackers.describe_fallback(doc["provenance"]) == "SAM 3.1 spend cap reached; tracked with local-open"


def test_job_cap_stops_api_calls(env, monkeypatch, tmp_path):
    put_key(env.keys, "MODEL_API_KEY")
    job = tmp_path / "job" / "spend.jsonl"
    ledger_line(job, 0.45)
    monkeypatch.setenv("PART2_JOB_LEDGER", str(job))
    assert api_sam31.ApiSam31().available(500) == (False, "budget")  # $0.10 more passes $0.50
    assert api_sam31.ApiSam31().available(100)[0]
    with pytest.raises(meta_api.BudgetExceeded):
        list(meta_api.respond("sam-3.1", [], est_cost_usd=0.10, budget=api_sam31.budgets()))


def test_budgets_record_into_every_ledger(env, monkeypatch, tmp_path):
    job = tmp_path / "job.jsonl"
    monkeypatch.setenv("PART2_JOB_LEDGER", str(job))
    guard = api_sam31.budgets()
    assert [b.limit for b in guard.budgets] == [25.0, 0.5]
    guard.record(0.02, "t", "sam-3.1")
    assert guard.spent() == pytest.approx(0.02) and guard.budgets[1].spent() == pytest.approx(0.02)
