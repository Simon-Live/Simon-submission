"""`make smoke-muse-spark`: the opt-in live smoke, tested through an injected client (never live here)."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from part5.phrasing import muse_spark, smoke
from test_phrasing import clean_env, no_network  # noqa: F401
from test_phrasing_muse_spark import SENTINEL, Client, live, reply  # noqa: F401

ROOT = Path(__file__).resolve().parent.parent


def test_it_exits_0_and_prints_the_line_and_the_token_counts(live, capsys):  # noqa: F811
    client = Client(reply("Your left foot drifts too far to the left at 1.9 s", 91, 52, 47))
    assert smoke.main(client=client) == 0
    out = capsys.readouterr()
    assert "line: Your left foot drifts too far to the left at 1.9 s" in out.out
    assert "tokens: prompt 91, completion 52, reasoning 47" in out.out
    assert "model: meta-models/muse-spark-open-1026" in out.out
    assert SENTINEL not in out.out + out.err
    assert json.loads(live["ledger"].read_text())["prompt_tokens"] == 91


def test_it_asks_about_the_fixed_fault_record(live):  # noqa: F811
    client = Client(reply("Your left foot drifts too far to the left at 1.9 s"))
    smoke.main(client=client)
    user = json.loads(client.requests[0]["body"]["messages"][1]["content"])
    assert user["measure"] == "foot_out" and user["side"] == "left" and user["direction"] == "more"


@pytest.mark.parametrize("bad", [reply(""), reply("Your right foot drifts too far to the left at 1.9 s"), reply("Your left foot is 14 degrees too far to the left at 1.9 s"),
                                 TimeoutError()])
def test_it_exits_1_when_no_valid_line_came_back(live, capsys, bad):  # noqa: F811
    assert smoke.main(client=Client(bad)) == 1
    err = capsys.readouterr().err
    assert err.startswith("smoke failed: muse-spark: ") and SENTINEL not in err


def test_it_exits_1_without_the_key_file(capsys):
    client = Client()
    assert smoke.main(client=client) == 1
    assert "smoke failed: no key" in capsys.readouterr().err and client.requests == []


def test_it_exits_1_without_meta_live(live, monkeypatch, capsys):  # noqa: F811
    monkeypatch.delenv("META_LIVE")
    assert smoke.main(client=Client()) == 1
    assert "live calls are off" in capsys.readouterr().err


def test_the_makefile_target_sets_meta_live_and_runs_the_smoke():
    text = (ROOT / "Makefile").read_text()
    assert re.search(r"^\.PHONY: smoke-muse-spark$", text, re.M)
    assert re.search(r"^smoke-muse-spark:\n\tMETA_LIVE=1 uv run python -m part5\.phrasing\.smoke$", text, re.M)


@pytest.mark.skipif(shutil.which("make") is None, reason="make is not installed")
def test_make_dry_run_prints_the_command_without_running_it():
    done = subprocess.run(["make", "-n", "smoke-muse-spark"], cwd=ROOT, capture_output=True, text=True)
    assert done.returncode == 0 and "META_LIVE=1 uv run python -m part5.phrasing.smoke" in done.stdout


def test_the_smoke_is_not_part_of_test_check_5_or_the_publish_check():
    text = (ROOT / "Makefile").read_text()
    for target in ("test", "check-5", "check-5-contract"):
        recipe = re.search(rf"^{re.escape(target)}:.*\n((?:\t.*\n)*)", text, re.M).group(1)
        assert "smoke" not in recipe and "phrasing" not in recipe
    assert muse_spark.LIVE_ENV == "META_LIVE"
