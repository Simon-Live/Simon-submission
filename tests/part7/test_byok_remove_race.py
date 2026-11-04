"""go-live BYOK N1 (docs/specs/byok-prod.md AC-BY11): Remove with a take queued leaves no client holding or using the
token. Before the fix Remove stopped the owner's clients, then wiped the token; a queued take read it in that gap and
started a launcher nothing stopped. Now Remove wipes and stops under the owner's lock, and every own-route process
starts through `modal_creds.launch_gate`, which reads the token again under that lock and registers the process
before letting go. Real processes: the real launcher (`p2_client.py --own`) and a stand-in Modal client that sleeps."""

from __future__ import annotations

import fcntl
import functools
import os
from pathlib import Path
import sys
import threading
from typing import Any

import pytest

from part7 import byok_crypto, jobs, modal_check, modal_creds, own_clients, run_on, runner
from part7.parts import p2_pose
from test_byok_own_clients import CLIENT, TOKENS, alive, stand, wait_for  # noqa: F401  stand is a fixture

TID, SECRET = TOKENS["MODAL_TOKEN_ID"], TOKENS["MODAL_TOKEN_SECRET"]


@pytest.fixture(autouse=True)
def _key(monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory) -> None:
    monkeypatch.setenv(byok_crypto.KEY_ENV, str(tmp_path_factory.mktemp("byok-key") / "k"))


def _launch(st: dict, env: dict[str, str] | None, gate: Any) -> runner.Step:
    """One own-route Part 2 call as p2_pose makes it, inside the owner's job (the launcher registers for "ann")."""
    base = {k: v for k, v in st["env"].items() if k not in TOKENS}
    with own_clients.job(st["state"], "ann"):
        argv = [sys.executable, "-I", str(CLIENT), "--own", *own_clients.launcher_args(), "--check"]
    old = dict(os.environ)
    os.environ.update(base)
    try:
        return runner.run(2, argv, cwd=st["tmp"], env_extra=env, timeout_s=30, gate=gate)
    finally:
        os.environ.clear()
        os.environ.update(old)


def test_a_take_that_read_the_token_before_remove_starts_nothing(stand: dict) -> None:  # noqa: F811
    """The queued take of the report: it read the token (run_on.run_own), Remove ran, then it starts its client."""
    assert modal_creds.save(stand["state"], "ann", TID, SECRET)
    env = modal_creds.env_for(stand["state"], "ann")
    assert env == TOKENS
    assert modal_creds.remove(stand["state"], "ann") is True
    step = _launch(stand, env, functools.partial(modal_creds.launch_gate, stand["state"], "ann"))
    assert step["exit"] == runner.GATE_CLOSED_EXIT and step["refused"] is True
    assert not stand["childpid"].exists(), "a Modal client started on the removed token"
    assert list(own_clients.registry(stand["state"]).glob("*.json")) == []


def test_remove_while_a_client_starts_stops_it(stand: dict) -> None:  # noqa: F811
    """A client started just before Remove is registered by the server at once, so Remove finds it and ends it."""
    assert modal_creds.save(stand["state"], "ann", TID, SECRET)
    out: dict[str, runner.Step] = {}
    seen: list[bool] = []
    gate = lambda: _Checked(modal_creds.launch_gate(stand["state"], "ann"), stand["state"], seen)  # noqa: E731
    take = threading.Thread(target=lambda: out.setdefault("step", _launch(stand, None, gate)))
    take.start()
    assert wait_for(lambda: bool(seen)), "the client never started"
    assert seen == [True], "the server had not registered the client before letting the lock go"
    assert modal_creds.remove(stand["state"], "ann") is True
    take.join(timeout=20)
    assert not take.is_alive() and out["step"]["exit"] != 0
    text = stand["childpid"].read_text().strip() if stand["childpid"].is_file() else ""
    assert not text or wait_for(lambda: not alive(int(text))), "a client still holds the removed token"
    assert modal_creds.env_for(stand["state"], "ann") is None
    assert list(own_clients.registry(stand["state"]).glob("*.json")) == []


class _Checked:
    """`launch_gate` that, as `started` returns, records whether the launcher's registry file already exists."""

    def __init__(self, inner: Any, state: Path, seen: list[bool]) -> None:
        self.inner, self.state, self.seen = inner, state, seen

    def __enter__(self) -> Any:
        env, started = self.inner.__enter__()

        def check(pid: int) -> Path | None:
            path = started(pid)
            self.seen.append(path is not None and path.is_file() and path.name == f"{pid}.json")
            return path

        return env, check

    def __exit__(self, *exc: Any) -> Any:
        return self.inner.__exit__(*exc)


def test_remove_wipes_first_and_stops_under_the_lock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert modal_creds.save(tmp_path, "ann", TID, SECRET)
    path = tmp_path / "credentials" / "ann.json"
    seen: list[tuple[bool, bool]] = []

    def stop_owner(state: Any, user: str) -> int:
        fd = os.open(modal_creds.side(path, modal_creds.LOCK), os.O_RDWR)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            held = False
        except BlockingIOError:
            held = True
        finally:
            os.close(fd)
        seen.append((path.exists(), held))
        return 0

    monkeypatch.setattr(modal_creds.own_clients, "stop_owner", stop_owner)
    assert modal_creds.remove(tmp_path, "ann") is True
    assert seen == [(False, True)], "the token must be gone, and the lock held, when the clients are stopped"


def test_the_own_route_starts_every_part2_call_through_the_gate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    gates: list[Any] = []
    monkeypatch.setattr(p2_pose.runner, "run", lambda *a, **k: gates.append(k.get("gate")) or runner.Step(exit=0))
    monkeypatch.setattr(p2_pose.byok_route, "command", lambda sub, sha: ["own-client"])
    monkeypatch.setattr(p2_pose.quota, "disk_refusal", lambda *a: None)
    lk = p2_pose.modules.load()
    with p2_pose.job_modal_env_set(TOKENS, gate="the-gate"):
        p2_pose._on_route("modal", ["run"], "gpu", tmp_path, "part2.log", lk, tmp_path, True, None)
    assert gates == ["the-gate"]
    assert p2_pose.job_modal_gate() is None


class _Ctx:
    def __init__(self, draining: bool = False) -> None:
        self.id, self.draining = "job1", draining


def _cut_job(state: Path, after: Any) -> Any:
    def fn(ctx: Any) -> dict[str, Any]:
        after()
        raise jobs.JobFailed("pose", "The 3D step failed: modal: your Modal account, part2 run at c273b198f735, "
                                     "uploading 7.0 MB")
    return run_on.bind(fn, "serverless", state, "ann")


@pytest.mark.parametrize("cut", ["remove", "drain", "none"])
def test_a_take_cut_off_says_why_in_plain_words(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cut: str) -> None:
    """go-live BYOK N2: Remove names the Me page; the drain says the app restarted; any other failure keeps its reason."""
    monkeypatch.setenv("PROD_COMPUTE", "byok")
    assert modal_creds.save(tmp_path, "ann", TID, SECRET)
    fn = _cut_job(tmp_path, (lambda: modal_creds.remove(tmp_path, "ann")) if cut == "remove" else (lambda: None))
    with pytest.raises(jobs.JobFailed) as err:
        fn(_Ctx(draining=cut == "drain"))
    want = {"remove": run_on.MSG_REMOVED, "drain": jobs.DRAIN_CUT_REASON}.get(cut)
    if want is None:
        assert "part2 run at" in err.value.reason
    else:
        assert err.value.reason == want and "c273b198" not in err.value.reason
    assert ("the Me page" in err.value.reason) == (cut == "remove")


def test_sr2_check_my_credentials_starts_through_the_gate_and_remove_stops_it(
    stand: dict, monkeypatch: pytest.MonkeyPatch  # noqa: F811
) -> None:
    """S-R2: the real "Check my credentials" launcher is registered before the lock is let go, so Remove ends it; once
    the token is gone a check starts nothing."""
    for key in ("PATH", "HOME", "SIMON7_MODAL_PYTHON"):
        monkeypatch.setenv(key, stand["env"][key])
    assert modal_creds.save(stand["state"], "ann", TID, SECRET)
    out: list[str] = []
    check = threading.Thread(target=lambda: out.append(modal_check.run_check(stand["state"], "ann")))
    check.start()
    assert wait_for(lambda: stand["childpid"].is_file()), "the check's Modal client never started"
    assert list(own_clients.registry(stand["state"]).glob("*.json")), "a running check that Remove cannot find"
    assert modal_creds.remove(stand["state"], "ann") is True
    check.join(timeout=20)
    assert not check.is_alive() and out and out[0] != modal_check.OK
    assert wait_for(lambda: not alive(int(stand["childpid"].read_text().strip()))), "the check still holds the token"
    assert list(own_clients.registry(stand["state"]).glob("*.json")) == []
    assert modal_check.result(stand["state"], "ann") is None
    stand["childpid"].unlink()
    assert modal_check.run_check(stand["state"], "ann") == modal_check.FAILED
    assert not stand["childpid"].exists(), "a check started with no token"
