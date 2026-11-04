"""BYOK-C2, BYOK-H1 (B2), BYOK-M5 (R1, R2), BYOK-H3 (docs/specs/byok-prod.md): under BYOK-only every model job runs on
its owner's own Modal credentials, and nothing falls back to this machine or the server's Modal account. Outside it,
an own-account job never reaches the server's account either. GPU-safe: the runner is faked, nothing is launched."""

from __future__ import annotations

import os
from pathlib import Path
import time
from typing import Any

import pytest

from part7 import byok_crypto, byok_route, challenges, jobs, modal_creds, modules, run_on, runner
from part7.parts import p2_pose

TID, SECRET = "ak-ProdTokenIdValue01", "as-ProdSecretValue0001"
SERVER_TID, SERVER_SECRET = "ak-ServerWideTokenXX", "as-ServerWideSecretXX"


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, tmp_path_factory: pytest.TempPathFactory) -> None:
    monkeypatch.setenv(byok_crypto.KEY_ENV, str(tmp_path_factory.mktemp("byok-key") / "k"))
    for name in (p2_pose.REMOTE_ENV, p2_pose.FALLBACK_ENV, byok_route.PROD_COMPUTE_ENV, "FIRM_ENV"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(run_on.CONFIG_PATH_ENV, str(tmp_path / "no-modal.toml"))


@pytest.fixture
def prod(monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory) -> None:
    monkeypatch.setenv("FIRM_ENV", "prod")
    monkeypatch.setenv("SIMON7_BYOK", "on")  # serverless-compute.md: paused by default; these hold the lane for its return
    monkeypatch.setenv("PROD_SECRETS_DIR", str(tmp_path_factory.mktemp("prod-secrets")))  # log redaction reads it (ADR-0025)
    # the server has its own Modal route and the fallback on: BYOK-only must ignore both
    monkeypatch.setenv(p2_pose.REMOTE_ENV, "modal")
    monkeypatch.setenv(p2_pose.FALLBACK_ENV, "on")
    monkeypatch.setenv(run_on.TOKEN_ENV[0], SERVER_TID)
    monkeypatch.setenv(run_on.TOKEN_ENV[1], SERVER_SECRET)


class Ctx:
    def __init__(self, job_id: str = "job1") -> None:
        self.id = job_id


def fake_runner(monkeypatch: pytest.MonkeyPatch, exits: list[int] | None = None) -> list[dict[str, Any]]:
    """Every Part 2 launch, as {route, env}; `exits` are the own/server modal exits in order (default 0)."""
    calls: list[dict[str, Any]] = []
    left = list(exits or [])
    monkeypatch.setattr(p2_pose.applog, "anomaly", lambda *a, **k: None)

    def fake_run(part: Any, argv: list[str], cwd: Any, env_extra: dict[str, str] | None = None, **kw: Any) -> runner.Step:
        route = "own" if argv == ["own-client"] else "server-modal"
        calls.append({"route": route, "env": dict(env_extra or {})})
        return runner.Step(exit=left.pop(0) if left else 0)

    monkeypatch.setattr(p2_pose.runner, "run", fake_run)
    monkeypatch.setattr(p2_pose, "_remote_command", lambda sub, lk: ["server-client"])
    monkeypatch.setattr(p2_pose.byok_route, "command", lambda sub, sha: ["own-client"])
    monkeypatch.setattr(p2_pose, "has_worker", lambda *a: False)
    monkeypatch.setattr(p2_pose, "_attempt", lambda *a, **k: calls.append({"route": "local", "env": {}}) or runner.Step(exit=0))
    return calls


def part2_job(tmp_path: Path, times: int = 1) -> Any:
    """A job that makes `times` Part 2 calls (a retry is a second call) and fails like a real one on a non-zero exit."""
    def fn(ctx: Any) -> dict[str, Any]:
        exits = []
        for _ in range(times):
            step = p2_pose._execute(["run"], "gpu", tmp_path, "part2.log", modules.load(), tmp_path, True, None)
            if step["exit"] != 0:
                raise jobs.JobFailed("pose", "part 2 failed")
            exits.append(step["exit"])
        return {"result": {"exits": exits}}
    return fn


def own_job(tmp_path: Path, user: str = "ann", times: int = 1) -> Any:
    choice, bad = run_on.parse({}, tmp_path, user)
    assert bad is None
    return run_on.bind(part2_job(tmp_path, times), choice, tmp_path, run_on.owner_for(choice, tmp_path, user))


# ----- BYOK-only: refuse without the owner's credentials (BYOK-C2) --------------------------------------------------
@pytest.mark.usefixtures("prod")
def test_prod_refuses_a_take_without_own_credentials_and_never_offers_the_servers_account(tmp_path: Path) -> None:
    assert run_on.byok_only() and run_on.modal_configured() is False
    assert run_on.offered(tmp_path, "ann") is False
    assert run_on.parse({}, tmp_path, "ann") == (None, run_on.MSG_NEEDS_OWN)
    assert run_on.parse({"run_on": "serverless"}, tmp_path, None) == (None, run_on.MSG_NEEDS_OWN)
    assert "Me page" in run_on.MSG_NEEDS_OWN, "the message says how to add them"


@pytest.mark.usefixtures("prod")
def test_prod_this_machine_is_refused_and_no_choice_means_own(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = fake_runner(monkeypatch)
    modal_creds.save(tmp_path, "ann", TID, SECRET)
    assert run_on.parse({"run_on": "local"}, tmp_path, "ann") == (None, run_on.MSG_NEEDS_OWN)
    assert run_on.parse({}, tmp_path, "ann") == ("serverless", None)
    assert run_on.parse({"run_on": "serverless"}, tmp_path, "ann") == ("serverless", None)
    out = own_job(tmp_path)(Ctx())
    assert out["result"]["exits"] == [0]
    assert calls == [{"route": "own", "env": {"MODAL_TOKEN_ID": TID, "MODAL_TOKEN_SECRET": SECRET}}]


@pytest.mark.usefixtures("prod")
def test_prod_a_part2_call_without_owner_env_never_starts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = fake_runner(monkeypatch)
    step = p2_pose._execute(["run"], "gpu", tmp_path, "part2.log", modules.load(), tmp_path, True, None)  # a trainer job
    assert step["exit"] == byok_route.BYOK_REFUSED_EXIT and step["refused"] is True
    assert calls == [], "not this machine, not the server's Modal account"
    assert "Me page" in (tmp_path / "steps" / "part2.log").read_text(encoding="utf-8")
    with pytest.raises(jobs.JobFailed) as err:
        run_on.bind(part2_job(tmp_path), None, tmp_path, None)(Ctx())
    assert err.value.reason == run_on.MSG_NEEDS_OWN and calls == []


@pytest.mark.usefixtures("prod")
@pytest.mark.parametrize("gone", ["removed", "expired"])
def test_prod_credentials_removed_or_expired_before_the_run_are_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                                       gone: str) -> None:
    calls = fake_runner(monkeypatch)
    modal_creds.save(tmp_path, "ann", TID, SECRET)
    fn = own_job(tmp_path)
    if gone == "removed":
        modal_creds.remove(tmp_path, "ann")
    else:
        then = time.time() - 25 * 3600
        os.utime(tmp_path / "credentials" / "ann.json", (then, then))
    with pytest.raises(jobs.JobFailed) as err:
        fn(Ctx())
    assert err.value.reason == run_on.MSG_NEEDS_OWN and calls == []


@pytest.mark.usefixtures("prod")
def test_prod_refused_credentials_never_fall_back(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = fake_runner(monkeypatch, exits=[byok_route.CREDS_REFUSED_EXIT])
    modal_creds.save(tmp_path, "ann", TID, SECRET)
    with pytest.raises(jobs.JobFailed) as err:
        own_job(tmp_path)(Ctx())
    assert err.value.reason == run_on.MSG_REFUSED_BYOK
    assert [c["route"] for c in calls] == ["own"], "no local re-run, no server account, even with the fallback on"


@pytest.mark.usefixtures("prod")
def test_prod_any_other_failure_never_falls_back(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = fake_runner(monkeypatch, exits=[1])
    modal_creds.save(tmp_path, "ann", TID, SECRET)
    with pytest.raises(jobs.JobFailed) as err:
        own_job(tmp_path)(Ctx())
    assert err.value.reason == "part 2 failed" and [c["route"] for c in calls] == ["own"]


@pytest.mark.usefixtures("prod")
def test_prod_a_retry_stays_on_the_owners_account(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = fake_runner(monkeypatch)
    modal_creds.save(tmp_path, "ann", TID, SECRET)
    own_job(tmp_path, times=2)(Ctx())
    assert [c["route"] for c in calls] == ["own", "own"]
    assert all(c["env"]["MODAL_TOKEN_SECRET"] == SECRET for c in calls)
    assert all(SERVER_SECRET not in str(c["env"]) for c in calls)


# ----- resume (B2, BYOK-H1) -----------------------------------------------------------------------------------------
def _own_record(job_id: str = "j1") -> dict[str, Any]:
    return {"id": job_id, "kind": "follow", run_on.FIELD: "serverless", run_on.MODAL_FIELD: run_on.OWN}


@pytest.mark.parametrize("case", ["owner-lookup-none", "account-deleted", "credentials-removed"])
def test_b2_resume_without_the_owner_runs_here_never_on_the_servers_modal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                                       case: str) -> None:
    monkeypatch.setenv(p2_pose.REMOTE_ENV, "modal")  # the server has its own Modal route
    calls = fake_runner(monkeypatch)
    modal_creds.save(tmp_path, "ann", TID, SECRET)
    owner: str | None = "ann"
    if case == "owner-lookup-none":
        owner = None
    elif case == "account-deleted":
        modal_creds.remove(tmp_path, "ann")
        owner = None
    else:
        modal_creds.remove(tmp_path, "ann")
    run_on.resume_bind(part2_job(tmp_path), _own_record(), tmp_path, owner)(Ctx())
    assert [c["route"] for c in calls] == ["local"], f"{case}: this machine, never the server's account"


@pytest.mark.parametrize("case", ["owner-lookup-none", "credentials-removed"])
def test_b2_resume_without_the_owner_is_refused_in_prod(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, prod: None,
                                                        case: str) -> None:
    calls = fake_runner(monkeypatch)
    modal_creds.save(tmp_path, "ann", TID, SECRET)
    owner = None if case == "owner-lookup-none" else "ann"
    if case == "credentials-removed":
        modal_creds.remove(tmp_path, "ann")
    with pytest.raises(jobs.JobFailed):
        run_on.resume_bind(part2_job(tmp_path), _own_record(), tmp_path, owner)(Ctx())
    assert calls == []


def test_resume_with_the_owners_credentials_stays_on_their_account(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = fake_runner(monkeypatch)
    modal_creds.save(tmp_path, "ann", TID, SECRET)
    run_on.resume_bind(part2_job(tmp_path), _own_record(), tmp_path, "ann")(Ctx())
    assert calls == [{"route": "own", "env": {"MODAL_TOKEN_ID": TID, "MODAL_TOKEN_SECRET": SECRET}}]


def test_prod_resume_of_a_job_from_before_byok_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, prod: None) -> None:
    calls = fake_runner(monkeypatch)
    with pytest.raises(jobs.JobFailed):
        run_on.resume_bind(part2_job(tmp_path), {"id": "j2", "kind": "follow", run_on.FIELD: "local"}, tmp_path, None)(Ctx())
    assert calls == []


# ----- outside prod: R1 and R2 (BYOK-M5) ----------------------------------------------------------------------------
def test_r1_an_own_failure_other_than_refused_does_not_rerun_here(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = fake_runner(monkeypatch, exits=[1])
    modal_creds.save(tmp_path, "ann", TID, SECRET)
    fn = run_on.bind(part2_job(tmp_path), "serverless", tmp_path, "ann")
    with pytest.raises(jobs.JobFailed):
        fn(Ctx())
    assert [c["route"] for c in calls] == ["own"]


def test_r1_with_the_fallback_on_an_own_failure_still_never_reaches_the_servers_account(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(p2_pose.FALLBACK_ENV, "on")
    calls = fake_runner(monkeypatch, exits=[byok_route.CREDS_REFUSED_EXIT])
    modal_creds.save(tmp_path, "ann", TID, SECRET)
    out = run_on.bind(part2_job(tmp_path), "serverless", tmp_path, "ann")(Ctx())
    assert [c["route"] for c in calls] == ["own", "local"]
    assert out["result"]["run_on_note"] == run_on.MSG_OWN_REFUSED


def test_r2_the_refused_exit_is_reserved_and_not_parts_3() -> None:
    assert byok_route.CREDS_REFUSED_EXIT == p2_pose.CREDS_REFUSED_EXIT == 77
    assert byok_route.may_fall_back(True, 3, False) is False, "Part 2's own exit 3 is a failure, not a refusal"
    assert byok_route.may_fall_back(True, 77, False) is True


def test_prod_compute_byok_alone_turns_byok_only_on(monkeypatch: pytest.MonkeyPatch) -> None:
    assert byok_route.byok_only() is False
    monkeypatch.setenv(byok_route.PROD_COMPUTE_ENV, "byok")
    assert byok_route.byok_only() is True and byok_route.may_fall_back(True, 77, True) is False


# ----- boards (BYOK-H3, #415) ---------------------------------------------------------------------------------------
def test_prod_own_compute_results_are_flagged_and_rank_unless_the_operator_closes_it(tmp_path: Path, prod: None,
                                                             monkeypatch: pytest.MonkeyPatch) -> None:
    rec = run_on.record("serverless", "ann")
    assert rec == {"run_on": "serverless", "modal": "own", "compute_owner": True}, "the ph-policy board contract"
    assert rec["compute_owner"] is True and challenges.ranks_owner_compute() is True  # on in prod from release 7
    monkeypatch.setenv("SIMON7_POLICY_BYOK_RANKED", "off")
    assert challenges.ranks_owner_compute() is False, "the operator's switch keeps them off"


def test_every_own_credentials_job_carries_compute_owner_and_no_other_does(tmp_path: Path) -> None:
    rec = run_on.record("serverless", "ann")
    assert rec["compute_owner"] is True, "set outside prod too: the field is a fact, the boards apply the policy"
    for other in (run_on.record("serverless", None), run_on.record("local", None), run_on.record(None, None)):
        assert "compute_owner" not in other
    assert challenges.ranks_owner_compute() is True, "outside prod every policy is on"
