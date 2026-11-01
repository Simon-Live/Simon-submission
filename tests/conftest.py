"""No test makes a live call, whatever the shell it runs from has set (docs/specs/journey-followup.md AC-P02).

`staging/env.sh` exports `META_LIVE=1` when the key file exists, and a test that runs `cli.main(["analyse", ...])`
or `pipeline.run` without a `phrasing` takes the live default (ADR-0008). Without a guard, `make test` from that
shell would spend real Baseten calls with the operator's key. So every test starts with:

- `SIMON5_LIVE` and `META_LIVE` unset, so the default backend is `template`;
- the key files (Baseten, and the Meta Model API's for the second opinion) pointed at paths that do not exist and the
  usage ledgers at temp paths, so even a test that turns live mode on finds no key and writes no line to
  `~/.simon/baseten_usage.jsonl` or `~/.simon/meta_usage.jsonl`;
- `HTTP_PROXY`, `HTTPS_PROXY` and `ALL_PROXY` unset in any case: a proxy on 127.0.0.1 passes the loopback rule
  below, so it could carry a test request off the host;
- every socket connect, and every name lookup, for a host outside the loopback refused (`ConnectionRefusedError`),
  while the local HTTP servers some tests start keep working.

A test of a live path sets its own environment through `monkeypatch` after this runs. Module and session scoped
fixtures are set up before any function scoped one, so the same environment is applied once for the session too.

`seed5` is shared by tests/test_profiles.py and tests/test_profiles_tempo.py (docs/specs/profiles.md): the seed 5 takes
analysed under each profile. It is session scoped so the analyses run once for both files. tests/test_generator.py has a
`seed5` of its own, which wins in that file.
"""
import ipaddress
import json
import os
import socket
from pathlib import Path

import pytest

LIVE_ENVS = ("SIMON5_LIVE", "META_LIVE")
KEY_ENV, USAGE_ENV = "PART5_BASETEN_KEY_FILE", "PART5_BASETEN_USAGE_FILE"
META_KEY_ENV, META_USAGE_ENV = "PART5_META_KEY_FILE", "PART5_META_USAGE_FILE"   # the second opinion (TICKET-045)
PROXY_ENVS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")
PROFILE_NAMES = ("fitness", "dance", "rehab")
BLIND_BASE = Path(__file__).resolve().parent.parent / "fixtures/input/expected/exercise/animation.json"


def is_local(address):
    """True for a loopback address, an empty host (this machine) or `localhost`."""
    host = address[0] if isinstance(address, tuple) else address
    if isinstance(host, bytes):
        host = host.decode("ascii", "replace")
    if host in ("", "localhost"):
        return True
    try:
        return ipaddress.ip_address(host.split("%")[0]).is_loopback
    except ValueError:
        return False


def refuse(host):
    raise ConnectionRefusedError(f"tests make no network calls: refused {host!r}")


def guarded(connect):
    def wrapper(self, address, *args, **kwargs):
        if self.family != socket.AF_UNIX and not is_local(address):
            refuse(address[0])
        return connect(self, address, *args, **kwargs)
    return wrapper


def guarded_lookup(getaddrinfo):
    """A name lookup for anything but this machine would leave the host, so it is refused like a connect."""
    def wrapper(host, *args, **kwargs):
        if host is not None and not is_local(host):
            refuse(host)
        return getaddrinfo(host, *args, **kwargs)
    return wrapper


def no_live(mp, directory):
    """Apply the guard to `mp` (a MonkeyPatch): live mode off, no proxy, no key file, a temp ledger."""
    for name in LIVE_ENVS:
        mp.delenv(name, raising=False)
    for name in [n for n in os.environ if n.upper() in PROXY_ENVS]:
        mp.delenv(name)
    mp.setenv(KEY_ENV, str(directory / "no-such-key-file"))
    mp.setenv(USAGE_ENV, str(directory / "baseten_usage.jsonl"))
    mp.setenv(META_KEY_ENV, str(directory / "no-such-meta-key-file"))
    mp.setenv(META_USAGE_ENV, str(directory / "meta_usage.jsonl"))


@pytest.fixture(scope="session", autouse=True)
def _session_without_live_calls(tmp_path_factory):
    mp = pytest.MonkeyPatch()
    no_live(mp, tmp_path_factory.mktemp("no-live"))
    for method in ("connect", "connect_ex"):
        mp.setattr(socket.socket, method, guarded(getattr(socket.socket, method)))
    mp.setattr(socket, "getaddrinfo", guarded_lookup(socket.getaddrinfo))
    yield
    mp.undo()


@pytest.fixture(autouse=True)
def _without_live_calls(monkeypatch, tmp_path):
    no_live(monkeypatch, tmp_path)


@pytest.fixture(scope="session")
def blind_follower():
    """A factory for a follower with no usable joints, nothing to align or measure (ADR-0012 `no_usable_measures`).

    Every call builds a new document, so a test may change what it gets."""
    def build():
        doc = json.loads(BLIND_BASE.read_text())
        for frame in doc["frames"]:
            frame["conf"] = {j: 0.0 for j in frame["joints"]}
            frame["joints"] = {j: None for j in frame["joints"]}
        return {"path": "blind.upload", "doc": doc}
    return build


@pytest.fixture(scope="session")
def seed5():
    """({take_id: analysis} per profile, labels): every seed 5 take analysed with the score under each profile.

    The analyses are only read by the tests that ask for it."""
    from part5 import profiles_report   # here and not at the top, so a test that never asks for it does not import it
    labels = profiles_report.tuning_labels()
    return {name: profiles_report.run_profile(labels, name)[0] for name in PROFILE_NAMES}, labels
