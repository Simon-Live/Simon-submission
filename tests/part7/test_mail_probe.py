"""The timed send probe: off without a sink address, a streak of misses opens the finding, a success closes it."""

from __future__ import annotations

import importlib.util
import json
import logging
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from part7 import mail, mail_probe, selfheal

SINK = "sink@probe.example.org"
ROOT = Path(__file__).resolve().parents[2]


class Sender:
    def __init__(self, answers: list[bool]) -> None:
        self.answers, self.calls = answers, []

    def send_notice_now(self, to: str, subject: str, text: str, kind: str = "ops_notice") -> bool:
        self.calls.append((to, subject, kind))
        return self.answers.pop(0)


def test_without_the_variable_the_probe_is_off_and_says_so(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    monkeypatch.delenv(mail_probe.ENV_TO, raising=False)
    sender = Sender([True])
    assert mail_probe.run_once(tmp_path, sender) == "off" and sender.calls == []
    assert mail_probe.status(tmp_path) == {"state": "off", "why": "SIMON7_MAIL_PROBE_TO is not set; no probe runs"}
    with caplog.at_level(logging.INFO, logger="part7"):
        mail_probe.Prober(tmp_path, sender).start()
    assert "mail probe: off (SIMON7_MAIL_PROBE_TO is not set)" in caplog.text
    assert not (tmp_path / mail_probe.FILE).exists()


@pytest.mark.parametrize("bad", ["", "no-at-sign", "a@b", "a b@c.org", "a@b.org,c@d.org", "<a@b.org>", "a@@b.org"])
def test_only_a_plain_address_counts_as_a_sink(monkeypatch: pytest.MonkeyPatch, bad: str) -> None:
    monkeypatch.setenv(mail_probe.ENV_TO, bad)
    assert mail_probe.target() is None


def test_two_misses_open_the_finding_and_a_success_closes_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    monkeypatch.setenv(mail_probe.ENV_TO, SINK)
    selfheal.configure(tmp_path)
    sender = Sender([True, False, False, True])
    with caplog.at_level(logging.INFO, logger="part7"):
        assert mail_probe.run_once(tmp_path, sender, now=100.0) == "ok"
        assert mail_probe.run_once(tmp_path, sender, now=200.0) == "ok"  # one miss: not yet failing
        assert mail_probe.run_once(tmp_path, sender, now=300.0) == "failing"
        assert caplog.text.count("ANOMALY mail_probe_failed") == 2 and SINK not in caplog.text
        assert "mail_send" in selfheal.status(tmp_path)["open"]
        assert mail_probe.status(tmp_path)["failures"] == 2 and mail_probe.status(tmp_path)["last_ok"] == 100.0
        assert mail_probe.run_once(tmp_path, sender, now=400.0) == "ok"
    assert sender.calls[0] == (SINK, mail_probe.SUBJECT, "probe")
    assert oct((tmp_path / mail_probe.FILE).stat().st_mode & 0o777) == "0o600"


def test_the_cli_exit_codes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.delenv(mail_probe.ENV_TO, raising=False)
    assert mail_probe.cli(tmp_path) == 3
    monkeypatch.setenv(mail_probe.ENV_TO, SINK)
    sender = Sender([False, False])
    mail_probe.run_once(tmp_path, sender)
    mail_probe.run_once(tmp_path, sender)
    assert mail_probe.cli(tmp_path) == 1
    assert json.loads(capsys.readouterr().out.splitlines()[-1])["state"] == "failing"


def test_the_prober_thread_runs_on_a_timer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(mail_probe.ENV_TO, SINK)
    monkeypatch.setattr(mail_probe, "FIRST_DELAY_S", 0.01)
    sender = Sender([True] * 50)
    prober = mail_probe.Prober(tmp_path, sender).start()
    for _ in range(100):
        if sender.calls:
            break
        time.sleep(0.02)
    prober.stop()
    assert sender.calls and mail_probe.status(tmp_path)["state"] == "ok"


def test_the_real_mailer_probe_goes_through_the_smtp_seam(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(mail_probe.ENV_TO, SINK)
    seen: list[Any] = []
    monkeypatch.setattr(mail, "_smtp_send", lambda url, msg: seen.append(msg) or True)
    monkeypatch.setattr(mail, "smtp_url", lambda keys_dir=None: "smtp://x.example.test")
    assert mail_probe.run_once(tmp_path, mail.Mailer(tmp_path, transport="smtp")) == "ok"
    assert seen[0]["To"] == SINK and seen[0].kind == "probe"


def test_the_health_detail_carries_the_probe_and_the_cli_prints_it(tmp_path: Path) -> None:
    result = subprocess.run([sys.executable, "-m", "part7", "mail-probe", "--state", str(tmp_path)], capture_output=True, text=True,
                            cwd=ROOT, env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)})
    assert result.returncode == 3 and '"state": "off"' in result.stdout


def load_smoke() -> Any:
    spec = importlib.util.spec_from_file_location("prod_smoke", ROOT / "prod" / "smoke.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_smoke_fails_on_a_failing_probe_and_says_when_it_did_not_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    smoke = load_smoke().Smoke("https://simon.example")
    monkeypatch.delenv("PROD_STATE_DIR", raising=False)
    smoke.mail_probe_check()
    assert "not checked" in capsys.readouterr().out and smoke.failures == []
    monkeypatch.setenv("PROD_STATE_DIR", str(tmp_path))
    smoke.mail_probe_check()
    assert "has not run" in capsys.readouterr().out and smoke.failures == []
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "mail-probe.json").write_text(json.dumps({"failures": 1}))
    smoke.mail_probe_check()
    assert smoke.failures == []
    (tmp_path / "app" / "mail-probe.json").write_text(json.dumps({"failures": 2}))
    smoke.mail_probe_check()
    assert smoke.failures == ["mail probe is not failing"]
