"""Part 5 call wiring: `--lang`, second-opinion videos and private mode are passed only where the pin offers them."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from part7 import private_mode
from part7.parts import p5_analyse, probe
from support import stub_modules


class Harness:
    def __init__(self, state: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        self.lock = stub_modules(state / "modules")
        for n in range(1, 7):
            self.lock.path(n).mkdir(parents=True, exist_ok=True)
        self.calls: list[tuple[list[str], dict[str, str]]] = []
        self.mp, self.tmp = monkeypatch, tmp_path
        monkeypatch.setattr(p5_analyse.runner, "run", self._fake_run)
        monkeypatch.setattr(probe, "help_text", lambda *a, **k: "muse-spark --live")
        monkeypatch.delenv(private_mode.SWITCH_ENV, raising=False)

    def _fake_run(self, part, argv, **kw):  # noqa: ANN001, ANN202
        self.calls.append((argv, kw.get("env_extra") or {}))
        out = Path(argv[argv.index("--out") + 1])
        out.write_text('{"status": {"code": "ok"}}', encoding="utf-8")
        return {"exit": 0}

    def run(self, flags: set[str], **kw: Any):  # noqa: ANN202
        self.mp.setattr(probe, "has_flag", lambda _n, _a, _c, flag, _lk=None: flag in flags)
        return p5_analyse.run("e.json", "f.json", self.tmp / "w", lock=self.lock, **kw)


@pytest.fixture
def h(state_dir: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Harness:
    return Harness(state_dir, monkeypatch, tmp_path)


def test_lang_and_videos_are_passed_when_the_pin_offers_them(h: Harness) -> None:
    *_, notes = h.run({"--lang", "--expected-video", "--follower-video", "--live", "--replay"}, phrasing="live", lang="es",
                      expected_video="t.mp4", follower_video="f.mp4")
    argv = h.calls[0][0]
    assert argv[argv.index("--lang") + 1] == "es"
    assert "--expected-video" in argv and "--follower-video" in argv
    assert argv.count("--live") == 1
    assert not notes


def test_missing_flags_are_noted_not_passed(h: Harness) -> None:
    *_, notes = h.run(set(), phrasing="live", lang="es", expected_video="t.mp4", follower_video="f.mp4")
    argv = h.calls[0][0]
    assert "--lang" not in argv and "--expected-video" not in argv
    assert "Part 5 at this pin writes English only" in notes
    assert "Part 5 at this pin gives no second opinion" in notes


def test_english_and_template_phrasing_pass_nothing_extra(h: Harness) -> None:
    h.run({"--lang", "--expected-video"}, phrasing="template", lang="en", expected_video="t.mp4", follower_video="f.mp4")
    argv = h.calls[0][0]
    assert "--lang" not in argv and "--expected-video" not in argv


def test_private_mode_sends_no_video_and_takes_the_plans_phrasing(h: Harness) -> None:
    plan = private_mode.Plan(active=True, argv=["--phrasing", "local-llm"], env={"PART5_OLLAMA_MODEL": "m"}, model="m")
    h.mp.setattr(private_mode, "plan", lambda **kw: plan)

    @contextmanager
    def turn(p, job_dir=None):  # noqa: ANN001, ANN202
        yield p

    h.mp.setattr(private_mode, "gpu_turn", turn)
    h.run({"--expected-video", "--live"}, phrasing="live", private=True, expected_video="t.mp4", follower_video="f.mp4")
    argv, env = h.calls[0]
    assert "--expected-video" not in argv and "--live" not in argv
    assert argv[argv.index("--phrasing") + 1] == "local-llm"
    assert env["PART5_OLLAMA_MODEL"] == "m"


def test_inactive_private_plan_leaves_the_call_alone(h: Harness) -> None:
    h.run(set(), phrasing="template")
    argv, env = h.calls[0]
    assert argv[argv.index("--phrasing") + 1] == "template"
    assert env == {"PART5_PHRASING_CONCURRENCY": p5_analyse.PHRASING_CONCURRENCY}


def test_env_private_also_drops_the_videos(h: Harness) -> None:
    plan = private_mode.Plan(active=True, argv=["--phrasing", "local-llm"], model="m")
    h.mp.setattr(private_mode, "plan", lambda **kw: plan)
    h.mp.setenv(private_mode.SWITCH_ENV, "1")

    @contextmanager
    def turn(p, job_dir=None):  # noqa: ANN001, ANN202
        yield p

    h.mp.setattr(private_mode, "gpu_turn", turn)
    h.run({"--expected-video", "--follower-video", "--live"}, phrasing="live", expected_video="t.mp4", follower_video="f.mp4")
    argv = h.calls[0][0]
    assert "--expected-video" not in argv and "--follower-video" not in argv and "--live" not in argv


def test_job_flag_false_wins_over_the_env(h: Harness) -> None:
    seen: list[Any] = []
    h.mp.setattr(private_mode, "plan", lambda **kw: seen.append(kw["job_flag"]) or private_mode.Plan(active=False))
    h.mp.setenv(private_mode.SWITCH_ENV, "1")
    h.run({"--expected-video", "--follower-video", "--live"}, phrasing="live", private=False,
          expected_video="t.mp4", follower_video="f.mp4")
    assert seen == [False]
    assert "--expected-video" in h.calls[0][0]


def test_second_opinion_needs_both_video_flags(h: Harness) -> None:
    *_, notes = h.run({"--expected-video", "--live"}, phrasing="live", expected_video="t.mp4", follower_video="f.mp4")
    assert "--expected-video" not in h.calls[0][0]
    assert "Part 5 at this pin gives no second opinion" in notes


def test_capabilities_follow_the_probes(h: Harness) -> None:
    h.mp.setattr(probe, "has_flag", lambda _n, _a, _c, flag, _lk=None: flag in {"--lang", "--expected-video"})
    h.mp.setattr(private_mode, "part5_has_fix", lambda clone: True)
    probe.clear_cache()
    assert p5_analyse.capabilities(h.lock) == {"lang": True, "video": False, "private": True}
    probe.clear_cache()


def test_capabilities_are_all_false_when_the_probe_fails(h: Harness) -> None:
    h.mp.setattr(probe, "has_flag", lambda *a, **k: (_ for _ in ()).throw(OSError("no clone")))
    assert p5_analyse.capabilities(h.lock) == {"lang": False, "video": False, "private": False}


@pytest.mark.parametrize(("text", "flag", "want"), [
    ("  --live         ask the model", "--live", True),
    ("--live-x  other", "--live", False),
    ("--no-live", "--live", False),
    ("[--live]", "--live", True),
    ("--live=BOOL", "--live", True),
    ("--follower-video PATH", "--follower-video", True),
    ("--follower-videos", "--follower-video", False),
])
def test_probe_matches_whole_options(text: str, flag: str, want: bool) -> None:
    assert probe.mentions(text, flag) is want
