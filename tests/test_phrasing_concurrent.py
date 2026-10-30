"""Live phrasing runs its model calls on a small thread pool (PART5_PHRASING_CONCURRENCY, default 4).

The client is injected with an artificial delay; no socket is opened. Wall time is about the longest
call, not the sum; lines keep fault order; the rate limit, the time budget and the usage ledger hold.
"""
import json
import threading
import time

from part5 import phrasing
from test_phrasing import FAULTS, KNEE, TRUNK, clean_env, make_fault, no_network  # noqa: F401
from test_phrasing_muse_spark import GOOD, http_error, live, reply  # noqa: F401

DELAY = 0.3
LINE_OF = {"foot_out": GOOD[0], "knee_flexion": GOOD[1], "trunk_lean_forward": GOOD[2]}


class SlowClient:
    """Answers by the measure in the request, after a delay; tracks calls and the peak in flight."""

    def __init__(self, delay=DELAY, bad=(), delays=None):
        self.delay, self.bad, self.delays = delay, set(bad), delays or {}
        self.calls = self.peak = self.active = 0
        self.lock = threading.Lock()

    def __call__(self, request):
        measure = json.loads(request["body"]["messages"][-1]["content"])["measure"]
        with self.lock:
            self.calls += 1
            self.active += 1
            self.peak = max(self.peak, self.active)
        time.sleep(self.delays.get(measure, self.delay))
        with self.lock:
            self.active -= 1
        if measure in self.bad:
            raise http_error(500)
        return reply(LINE_OF[measure])


def run(concurrency, monkeypatch, client, faults=FAULTS, **options):
    monkeypatch.setenv("PART5_PHRASING_CONCURRENCY", str(concurrency))
    start = time.monotonic()
    out = phrasing.phrase(faults, "muse-spark", client=client, **options)
    return out, time.monotonic() - start


def test_wall_time_is_about_the_longest_call_not_the_sum(live, monkeypatch):
    client = SlowClient()
    (lines, record), wall = run(4, monkeypatch, client)
    assert wall < DELAY * 2 and client.peak == 3
    assert lines == GOOD and record["backend"] == "muse-spark"


def test_one_at_a_time_takes_the_sum(live, monkeypatch):
    client = SlowClient()
    (lines, _), wall = run(1, monkeypatch, client)
    assert wall >= DELAY * 3 and client.peak == 1 and lines == GOOD


def test_default_is_four_in_flight(live, monkeypatch):
    monkeypatch.delenv("PART5_PHRASING_CONCURRENCY")
    client = SlowClient(delay=0.1)
    phrasing.phrase(FAULTS * 2, "muse-spark", client=client)
    assert client.peak == 4 and client.calls == 6


def test_order_is_kept_when_calls_finish_out_of_order(live, monkeypatch):
    client = SlowClient(delays={"foot_out": 0.3, "knee_flexion": 0.15, "trunk_lean_forward": 0.0})
    (lines, _), _ = run(4, monkeypatch, client)
    assert lines == GOOD


def test_fallbacks_are_per_fault(live, monkeypatch):
    (lines, record), _ = run(4, monkeypatch, SlowClient(bad=("knee_flexion",)))
    assert lines == [GOOD[0], KNEE["text"], GOOD[2]]
    assert [e["backend"] for e in record["faults"]] == ["muse-spark", "template", "muse-spark"]
    assert record["faults"][1]["fallback_reason"].startswith("muse-spark:")


def test_rate_limit_holds_under_concurrency(live, monkeypatch):
    monkeypatch.setenv("PART5_MUSE_PER_MINUTE", "2")
    client = SlowClient()
    (lines, record), _ = run(4, monkeypatch, client)
    assert client.calls == 2
    reasons = [e["fallback_reason"] for e in record["faults"]]
    assert [r for r in reasons if r] == ["rate limited"]
    assert len(lines) == 3 and sum(e["backend"] == "muse-spark" for e in record["faults"]) == 2


def test_budget_applies_when_a_call_would_start(live, monkeypatch):
    # Two workers, three faults: the third would start after about DELAY, past a budget of 0.3 s.
    client = SlowClient()
    (lines, record), _ = run(2, monkeypatch, client, timeout_s=0.1, budget_s=0.3)
    assert client.calls == 2
    assert record["faults"][2]["fallback_reason"] == phrasing.BUDGET_SPENT and lines[2] == TRUNK["text"]


def test_ledger_has_one_whole_line_per_call(live, monkeypatch):
    faults = [make_fault() for _ in range(24)]
    run(4, monkeypatch, SlowClient(delay=0.01), faults=faults)
    rows = [json.loads(x) for x in live["ledger"].read_text().splitlines()]
    assert len(rows) == 24 and all(r["http_status"] == 200 for r in rows)


def test_template_run_is_unchanged_and_makes_no_call(monkeypatch):
    client = SlowClient()
    lines, record = phrasing.phrase(FAULTS, "template", client=client)
    assert client.calls == 0 and lines == [f["text"] for f in FAULTS] and record["backend"] == "template"


def test_concurrency_value_parsing(monkeypatch):
    monkeypatch.setenv("PART5_PHRASING_CONCURRENCY", "many")
    assert phrasing._concurrency() == 4
    monkeypatch.setenv("PART5_PHRASING_CONCURRENCY", "0")
    assert phrasing._concurrency() == 1
