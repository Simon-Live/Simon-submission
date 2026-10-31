"""No test, and no deterministic target, makes a live call (docs/specs/journey-followup.md AC-P02, AC-NFR-J01).

`tests/conftest.py` scrubs the environment for every test; these tests check that guard, and that with live mode
on and a key file present the paths `make check-5`, `make output-examples` and `make check-5-contract` run still
phrase with the template and never touch the usage ledger. The key file here is a fake, and the guard refuses the
network, so even a failure of the property would spend nothing.
"""
import importlib.util
import json
import os
import socket
import urllib.request
from pathlib import Path

import pytest

from part5 import check, contract
from part5.phrasing import select_backend
from part5.phrasing import muse_spark

ROOT = Path(__file__).resolve().parent.parent
LABELS = json.loads((ROOT / "fixtures/input/followers/labels.json").read_text())
TAKE = next(t for t in LABELS["takes"] if t["take_id"].startswith("exercise_front_good_08"))
GOLDENS = ("analysis.example.json", "analysis.no-faults.example.json")
REPLAY = "replay.example.json"   # the golden replay of the first golden's take


@pytest.fixture
def live_with_a_fake_key(monkeypatch, tmp_path):
    """Live mode on twice over, a key file in place, and a ledger path to look at afterwards."""
    key = tmp_path / "fake-key"
    key.write_text("fake-key-value-for-tests\n")
    ledger = tmp_path / "ledger" / "baseten_usage.jsonl"
    monkeypatch.setenv("META_LIVE", "1")
    monkeypatch.setenv("SIMON5_LIVE", "1")
    monkeypatch.setenv("PART5_BASETEN_KEY_FILE", str(key))
    monkeypatch.setenv("PART5_BASETEN_USAGE_FILE", str(ledger))
    muse_spark._calls.clear()
    return ledger


def no_ledger_line(ledger):
    return not ledger.exists() or ledger.read_text() == ""


def is_template(analysis):
    p = analysis["phrasing"]
    # The goldens go through the CLI path (R11), which records selected_by; it must never be the live default.
    return (p["requested"], p["backend"], p["fallback_reason"]) == ("template", "template", None) \
        and p.get("selected_by") != "live" and all(f["backend"] == "template" for f in p["faults"])


# --- the guard itself ---------------------------------------------------------------------------

def test_every_test_starts_with_live_mode_off_and_no_key():
    assert "META_LIVE" not in os.environ and "SIMON5_LIVE" not in os.environ
    assert not muse_spark.key_path().exists()
    assert muse_spark.unavailable() == "no key"
    assert select_backend(None, False) == ("template", "default")


def test_the_default_ledger_is_never_the_operators(tmp_path):
    assert muse_spark.usage_path().parent == tmp_path


def test_a_connect_outside_the_loopback_is_refused():
    with pytest.raises(ConnectionRefusedError, match="no network calls"):
        socket.create_connection(("203.0.113.9", 443), timeout=1)


def test_connect_ex_outside_the_loopback_is_refused_too():
    with socket.socket() as s, pytest.raises(ConnectionRefusedError):
        s.connect_ex(("198.51.100.4", 80))


def test_a_name_lookup_outside_the_loopback_is_refused_and_a_local_one_works():
    with pytest.raises(ConnectionRefusedError, match="no network calls"):
        socket.getaddrinfo("inference.baseten.co", 443)
    assert socket.getaddrinfo("127.0.0.1", 80)


def load_conftest():
    spec = importlib.util.spec_from_file_location("tests_conftest", ROOT / "tests/conftest.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PROXY_SPELLINGS = ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy", "Http_Proxy")


def proxy_names():
    return [n for n in os.environ if n.upper() in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")]


def proxies_in_force():
    """The schemes urllib would send through a proxy named by the environment."""
    return set(urllib.request.getproxies_environment()) & {"http", "https", "all"}


def test_a_proxy_in_the_environment_is_unset_in_any_case_so_no_request_leaves_through_it(monkeypatch, tmp_path):
    """A proxy on 127.0.0.1 passes the loopback rule, so the guard removes the variable that names it."""
    for name in PROXY_SPELLINGS:
        monkeypatch.setenv(name, "http://127.0.0.1:3128")
    assert proxies_in_force() == {"http", "https", "all"}  # the control: they are in force
    guard = pytest.MonkeyPatch()
    try:
        load_conftest().no_live(guard, tmp_path)
        assert proxy_names() == []
        assert proxies_in_force() == set()
    finally:
        guard.undo()
    assert set(PROXY_SPELLINGS) <= set(os.environ)  # the guard only removed them for its own patch


def test_every_test_runs_with_no_proxy_in_the_environment():
    assert proxy_names() == [] and proxies_in_force() == set()


def test_a_connect_to_a_local_server_still_works():
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        with socket.create_connection(server.getsockname(), timeout=2) as client:
            peer, _ = server.accept()
            client.sendall(b"ok")
            assert peer.recv(2) == b"ok"
            peer.close()


# --- AC-P02: deterministic paths stay template under live mode ---------------------------------------

def test_the_control_live_mode_with_a_key_does_pick_the_model(live_with_a_fake_key):
    assert select_backend(None, False) == ("muse-spark", "live")
    assert muse_spark.unavailable() is None


def test_ac_p02_the_check_5_path_phrases_with_the_template(live_with_a_fake_key):
    labels = {"takes": [{"take_id": TAKE["take_id"], "expected": TAKE["expected"], "follower": TAKE["follower"]}]}
    analyses, errors = check.analyse_set(labels, ROOT)
    assert errors == []
    analysis = analyses[TAKE["take_id"]]
    assert analysis["faults"] and is_template(analysis)
    assert no_ledger_line(live_with_a_fake_key)


def load_output_examples():
    spec = importlib.util.spec_from_file_location("make_output_examples", ROOT / "scripts/make_output_examples.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_ac_p02_the_output_examples_path_is_template_and_the_goldens_stay_byte_identical(
        live_with_a_fake_key, monkeypatch, tmp_path):
    module = load_output_examples()
    (tmp_path / "examples").mkdir()
    module.main(tmp_path / "examples")  # main's default binds OUT at definition, so pass the directory
    for name in (*GOLDENS, REPLAY):
        made = (tmp_path / "examples" / name).read_bytes()
        assert made == (ROOT / "fixtures/output" / name).read_bytes(), name
        if name in GOLDENS:
            assert is_template(json.loads(made))
    assert no_ledger_line(live_with_a_fake_key)


def test_ac_p02_the_check_5_contract_builder_rebuilds_the_goldens_with_the_template(live_with_a_fake_key):
    run = contract._Run(ROOT)
    for name in GOLDENS:
        rel = f"fixtures/output/{name}"
        run.rebuild(rel, ROOT / rel)
    run.rebuild_replay(f"fixtures/output/{REPLAY}", ROOT / "fixtures/output" / REPLAY)
    assert run.failures == [] and run.rebuilt == [f"fixtures/output/{n}" for n in (*GOLDENS, REPLAY)]
    assert no_ledger_line(live_with_a_fake_key)
