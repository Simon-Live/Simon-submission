"""docs/specs/muse-prod.md AC-MP1 to AC-MP8. No network, no real key: temp folders and fake values."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from part7 import consent_record, keys, licence_gates, muse_prod, policy_routes, prod_check, setup_parts
from part7.parts import p1_keyframes, p5_analyse


@pytest.fixture
def prod(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    secrets, state = tmp_path / "secrets", tmp_path / "state"
    secrets.mkdir(), state.mkdir()
    (secrets / "MODEL_API_KEY").write_text("fake-meta-value\n")
    (secrets / "BASETEN_API_KEY").write_text("fake-baseten-value\n")
    for name, value in (("FIRM_ENV", "prod"), ("PROD_SECRETS_DIR", str(secrets)), ("SIMON7_STATE_DIR", str(state)),
                        ("SIMON7_POLICY_MUSE", "on")):
        monkeypatch.setenv(name, value)
    return state


def test_ac_mp1_only_the_two_keys_and_only_with_the_switch(prod: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert keys.read_key("MODEL_API_KEY") == "fake-meta-value" and keys.read_key("BASETEN_API_KEY") == "fake-baseten-value"
    secrets = prod.parent / "secrets"
    (secrets / "HF_TOKEN").write_text("fake-hf")
    assert keys.read_key("HF_TOKEN") is None
    monkeypatch.setenv("SIMON7_POLICY_MUSE", "off")
    assert keys.read_key("MODEL_API_KEY") is None and keys.read_key("BASETEN_API_KEY") is None


def test_ac_mp2_start_check(prod: Path) -> None:
    secrets = prod.parent / "secrets"
    assert prod_check._key_file_problems(secrets, muse_on=True) == []
    assert {"MODEL_API_KEY", "BASETEN_API_KEY"} <= {p.split()[3] for p in prod_check._key_file_problems(secrets, muse_on=False)}
    assert prod_check._muse_problems({}, secrets) == []
    (secrets / "MODEL_API_KEY").unlink()
    assert any("MODEL_API_KEY" in p for p in prod_check._muse_problems({}, secrets))
    (secrets / "MODEL_API_KEY").write_text("x")


def test_ac_mp3_stop_file_closes_at_once_and_the_window_never_lifts_it(prod: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert muse_prod.admit("ask_take", "u1") is None and policy_routes.policy_doc()["switches"]["muse"] is True
    (prod / muse_prod.STOP_FILE).touch()
    closed = muse_prod.admit("ask_take", "u1")
    assert closed is not None and closed.code == "muse_stopped" and "paused" in closed.message
    assert muse_prod.status("compare", "u1") is not None and policy_routes.policy_doc()["switches"]["muse"] is False


def test_status_spends_nothing(prod: Path) -> None:
    for _ in range(10):
        assert muse_prod.status("compare", "u1") is None
    assert not list((prod / "muse").glob("spend-*.json")) or json.loads(next((prod / "muse").glob("spend-*.json")).read_text())["site"] == 0


def test_outside_prod_nothing_closes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FIRM_ENV", raising=False)
    assert muse_prod.admit("compare", "u") is None and muse_prod.status("part1") is None and muse_prod.part5_env() == {}


def test_switch_off_closes_and_wording_falls_back(prod: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert licence_gates.phrasing("live") == "live" and "mirror" in str(licence_gates.READ["muse_spark_open"]).lower()
    monkeypatch.setenv("SIMON7_POLICY_MUSE", "off")
    assert licence_gates.phrasing("live") == "template"
    closed = muse_prod.admit("ask_history", "u1")
    assert closed is not None and closed.code == "muse_off"


def test_negative_the_tracker_stays_off_meta_with_the_gate_open(prod: Path) -> None:
    assert licence_gates.tracker("api-sam31") == licence_gates.LOCAL_OPEN and licence_gates.meta_barred()


ITEMS = {k: True for k in consent_record.ITEMS}


def _doc(**extra: bool) -> dict:
    return {"age_band": "adult", "consent": {"version": consent_record.VERSION, "items": {**ITEMS, **extra}, "at": None}}


def test_ac_mp5_meta_tick_is_optional_and_decides(prod: Path) -> None:
    assert consent_record.refusal(_doc()) is None
    without, with_tick = consent_record.job_fields(_doc()), consent_record.job_fields(_doc(meta=True, meta_adults=True))
    assert consent_record.meta_allowed(without) is False and consent_record.meta_allowed(with_tick) is True
    assert consent_record.meta_allowed({}) is False
    assert policy_routes.policy_doc()["consent"]["meta_item"] == "meta"
    old = {"age_band": "adult", "consent": {"version": "2026-11-03.5", "items": ITEMS, "at": None}}
    assert consent_record.refusal(old) == (400, consent_record.MSG_STALE)  # everyone agrees again


def test_ac_mp7_prod_copy_and_hashes(prod: Path, tmp_path: Path) -> None:
    clone = tmp_path / "clone"
    (clone / "keyframe_finder").mkdir(parents=True)
    (clone / "keyframe_finder" / "a.py").write_text("x")
    (clone / ".venv").mkdir()
    (clone / ".firm-sha").write_text("abcdef0123456789\n")
    target = p1_keyframes._run_dir(clone, prod)
    assert target == prod / "part1" / "abcdef012345" and (target / "keyframe_finder" / "a.py").is_file()
    assert not (target / ".venv").exists() and p1_keyframes._run_dir(clone, prod) == target
    cmds = setup_parts._default_setup_commands("1", clone)
    assert "--require-hashes" in cmds[-1] and str(setup_parts.PART1_PROD_REQUIREMENTS) in cmds[-1]
    assert "--hash=sha256:" in setup_parts.PART1_PROD_REQUIREMENTS.read_text()


def test_ac_mp8_part5_gets_paths_never_values(prod: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env = muse_prod.part5_env()
    assert env["PART5_META_KEY_FILE"].endswith("/secrets/MODEL_API_KEY") and "fake-meta-value" not in json.dumps(env)
    assert int(env["PART5_META_SPEND_CAP_USD"]) == muse_prod.PART5_CAP_UNLIMITED_USD and str(prod) in env["PART5_META_USAGE_FILE"]
    assert int(muse_prod.part5_env()["PART5_META_SPEND_CAP_USD"]) == muse_prod.PART5_CAP_UNLIMITED_USD
    assert "muse_prod.part5_env()" in Path(p5_analyse.__file__).read_text()


def test_ac_mp5_the_trainers_own_answer_decides(prod: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from part7 import auth, jobs

    queue = jobs.JobQueue.__new__(jobs.JobQueue)
    queue._cond, queue._owner = __import__("threading").Condition(), True
    queue._jobs = {"a": {"kind": "trainer", "result": {"entry_id": "said-no"}, "consent": {"items": {**ITEMS}}},
                   "b": {"kind": "trainer", "entry_id": "said-yes", "consent": {"items": {**ITEMS, "meta": True, "meta_adults": True}}},
                   "c": {"kind": "trainer", "entry_id": "no-statement", "consent": {"items": {**ITEMS, "meta": True}}}}
    app = type("App", (), {"queue": queue, "state": prod})()
    monkeypatch.setitem(muse_prod._APPS, prod.resolve(), app)

    class Store:
        @staticmethod
        def entry_owner(entry_id: str) -> tuple[str, bool] | None:
            return ("u1", False) if entry_id == "aged-out" else None

    monkeypatch.setattr(auth, "identity", lambda _app: Store)
    assert not muse_prod.trainer_video_allowed(prod, "said-no") and muse_prod.trainer_video_allowed(prod, "said-yes")
    assert not muse_prod.trainer_video_allowed(prod, "aged-out") and muse_prod.trainer_video_allowed(prod, "operator-catalog")
    assert not muse_prod.trainer_video_allowed(prod, "no-statement")
