"""Tests for `part7.check7` with fake runners (check-7.md AC-K1, K3, K4, K5, K7, K8)."""

from __future__ import annotations

import inspect
import json
from pathlib import Path
import subprocess
from typing import Any

import pytest

from part7 import check7, config, modules
from support import stub_modules


def _lock() -> modules.Modules:
    return stub_modules(Path("unused-modules"))


def _fault(side: str = "left", mag: float = 20.0, at_s: float = 2.0, timed: bool = True) -> dict[str, Any]:
    f: dict[str, Any] = {"measure": "upper_arm_out", "side": side, "direction": "too_high",
                         "magnitude_deg": mag, "at_s": at_s, "expected_frames": [5]}
    if timed:
        f["text_timed"] = "Arm too high at 2s"
    return f


def _analysis(faults: list[dict[str, Any]], score: int | None = 80, status: str = "ok") -> dict[str, Any]:
    return {"status": {"code": status}, "faults": faults,
            "score": None if score is None else {"value": score, "grade": "B"}}


CLIPS = [
    {"id": "t", "role": "trainer", "url": "u", "licence": "Pexels License", "clip_sha256": "a"},
    {"id": "f1", "role": "follower", "url": "u", "licence": "l", "clip_sha256": "b"},
    {"id": "f2", "role": "follower", "url": "u", "licence": "l", "clip_sha256": "c"},
    {"id": "m", "role": "mismatch", "url": "u", "licence": "l", "clip_sha256": "d"},
]
MOV = {"id": "lateral-raise", "name": "Lateral raise", "rule_ok": True, "excluded_list_sha": "e", "grep_hits": []}
ENTRY = {"id": "e1", "files_source": "import", "video_uri_present": True, "keyframes_part": 1,
         "provenance_parts": {"keyframes": 1, "skeleton": 3, "animation": 4},
         "doctor_exit": 0, "skeleton_doctor_exit": 0, "animation_validate_exit": 0}


@pytest.fixture(autouse=True)
def clip_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for c in CLIPS:
        (tmp_path / f"{c['id']}.mp4").write_bytes(c["id"].encode())
    monkeypatch.chdir(tmp_path)


class FakeApp:
    def __init__(self, results: dict[str, dict[str, Any]]) -> None:
        self.results = results
        self.calls: list[str] = []

    def trainer(self, clip: Path, name: str) -> dict[str, Any]:
        self.calls.append("trainer")
        return {"job": "j0", "entry_id": "e1", "entry": {}}

    def follow(self, clip: Path, entry_id: str) -> dict[str, Any]:
        self.calls.append(clip.name)
        return {"job": "j" + clip.name, "analysis": self.results[clip.name]}


class FakeDirect:
    def __init__(self, results: dict[str, dict[str, Any]], commit_ok: bool = True) -> None:
        self.results = results
        self.steps = [{"path": "direct", "clip": "x", "part": 5, "commit": "555555555555" if commit_ok else "bad",
                       "argv": ["a"], "exit": 0, "duration_s": 1.0}]

    def trainer(self, clip: Path, keyframes: Path | None, work: Path) -> dict[str, Any]:
        return {"animation": work / "animation.json"}

    def follower(self, clip: Path, animation: Path, work: Path) -> dict[str, Any]:
        return {"analysis": self.results[clip.name], "exit": 0}


def _run(app_res: dict[str, dict[str, Any]], direct_res: dict[str, dict[str, Any]], *,
         mov: dict[str, Any] = MOV, entry: dict[str, Any] = ENTRY, app_pins: dict[str, str] | None = None,
         commit_ok: bool = True) -> dict[str, Any]:
    return check7.run_check(
        FakeApp(app_res), FakeDirect(direct_res, commit_ok), CLIPS, lambda c: Path(f"{c['id']}.mp4"), mov, _lock(),
        lambda t, c: {"entry": entry, "keyframes_path": None, "work": Path("w"), "part7_commit": "c" * 40},
        app_pins=app_pins,
    )


def _good() -> dict[str, dict[str, Any]]:
    return {"f1.mp4": _analysis([_fault()]), "f2.mp4": _analysis([_fault(side="right")]),
            "m.mp4": _analysis([], score=None, status="different_movement")}


def test_all_gates_pass_and_metrics_shape() -> None:
    m = _run(_good(), _good())
    assert m["pass"] is True
    assert m["gates"]["followers_matched"] == "2/2" and m["gates"]["faults_compared"] == 2
    assert m["gates"]["score_equal"] and m["gates"]["at_s_equal"] and m["gates"]["app_result_complete"]
    assert "refusal_both" not in m["gates"] and m["gates"]["mismatch_equal"] is True
    assert m["reported"]["mismatch_warnings"] == [["different_movement"]]
    assert m["tolerance"] == {"deg_abs": 2.0, "m_abs": 0.01, "rel": 0.10}
    json.dumps(m)


def test_vacuous_pass_fails_faults_compared_gate() -> None:
    res = {"f1.mp4": _analysis([]), "f2.mp4": _analysis([]), "m.mp4": _analysis([], score=None, status="different_movement")}
    m = _run(res, json.loads(json.dumps(res)))
    assert m["gates"]["faults_compared"] == 0 and m["pass"] is False


def test_score_difference_fails_score_gate() -> None:
    d = _good()
    d["f1.mp4"] = _analysis([_fault()], score=79)
    m = _run(_good(), d)
    assert m["gates"]["score_equal"] is False and m["pass"] is False


def test_at_s_difference_fails_at_s_gate() -> None:
    d = _good()
    d["f1.mp4"] = _analysis([_fault(at_s=2.1)])
    m = _run(_good(), d)
    assert m["gates"]["at_s_equal"] is False and m["pass"] is False


def test_missing_text_timed_in_app_result_fails() -> None:
    a = _good()
    a["f1.mp4"] = _analysis([_fault(timed=False)])
    m = _run(a, _good())
    assert m["gates"]["app_result_complete"] is False and m["pass"] is False


def test_missing_fault_fails_follower_match() -> None:
    d = _good()
    d["f2.mp4"] = _analysis([])
    m = _run(_good(), d)
    assert m["gates"]["followers_matched"] == "1/2" and m["pass"] is False


def test_module_shas_differ_between_paths_fails() -> None:
    m = _run(_good(), _good(), commit_ok=False)
    assert m["gates"]["pins_consistent"] is False and m["pass"] is False
    m = _run(_good(), _good(), app_pins={**_lock().shas_short(), "3": "000000000000"})
    assert m["gates"]["pins_consistent"] is False and m["pass"] is False


def test_entry_gate_requires_import_video_and_doctors() -> None:
    assert _run(_good(), _good(), entry={**ENTRY, "files_source": "processor"})["gates"]["entry_ok"] is False
    assert _run(_good(), _good(), entry={**ENTRY, "video_uri_present": False})["gates"]["entry_ok"] is False
    assert _run(_good(), _good(), entry={**ENTRY, "doctor_exit": 1})["gates"]["entry_ok"] is False
    assert _run(_good(), _good(), entry={**ENTRY, "keyframes_part": 3})["gates"]["entry_ok"] is True


def test_mismatch_take_scored_ok_with_a_good_grade_fails_mismatch_equal() -> None:
    res = _good()
    res["m.mp4"] = _analysis([_fault()], score=70)  # grade B, no warning: not an F
    m = _run(res, json.loads(json.dumps(res)))
    assert m["gates"]["mismatch_equal"] is False and m["pass"] is False


def test_mismatch_take_new_schema_f_with_equal_warnings_passes() -> None:
    res = _good()
    res["m.mp4"] = {"status": {"code": "ok"}, "faults": [_fault()], "warnings": [{"code": "low_match", "text": "x"}],
                    "score": {"value": 41, "grade": "F"}}
    m = _run(res, json.loads(json.dumps(res)))
    assert m["gates"]["mismatch_equal"] is True and m["pass"] is True
    assert m["reported"]["mismatch_warnings"] == [["low_match"]]


def test_mismatch_take_unequal_warnings_fail() -> None:
    a = _good()
    a["m.mp4"] = {"status": {"code": "ok"}, "faults": [], "warnings": [{"code": "low_match"}], "score": {"value": 41, "grade": "F"}}
    d = json.loads(json.dumps(a))
    d["m.mp4"]["warnings"] = [{"code": "not_enough_visible"}]
    m = _run(a, d)
    assert m["gates"]["mismatch_equal"] is False and m["pass"] is False


def test_mismatch_statuses_differ_fails_mismatch_equal() -> None:
    d = _good()
    d["m.mp4"] = _analysis([_fault()], score=70)
    m = _run(_good(), d)
    assert m["gates"]["mismatch_equal"] is False and m["pass"] is False


def test_movement_grep_hit_fails_never_configured(tmp_path: Path) -> None:
    clone = tmp_path / "1@aaaaaaaaaaaa"
    clone.mkdir()
    subprocess.run(["git", "init", "-q", str(clone)], check=True)
    (clone / "x.txt").write_text("handles lateral-raise here\n")
    subprocess.run(["git", "-C", str(clone), "add", "x.txt"], check=True)
    from part7 import movement

    hits = movement.grep_clones_for_movement("lateral-raise", "Lateral raise", parts_root=tmp_path)
    assert hits
    m = _run(_good(), _good(), mov={**MOV, "grep_hits": hits})
    assert m["gates"]["movement_never_configured"] is False and m["pass"] is False


def test_app_path_never_calls_parts_directly() -> None:
    src = inspect.getsource(check7.AppClient)
    for banned in ("p2_pose", "p3_skeleton", "p4_animate", "p5_analyse", "p6_catalog", "runner", "chain", "subprocess"):
        assert banned not in src
    assert "urlrequest" in src


def test_direct_path_uses_only_cli_adapters() -> None:
    src = inspect.getsource(check7.DirectPath)
    assert "urlrequest" not in src and "AppClient" not in src


def test_missing_prerequisite_exits_2_with_json(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(modules, "load", _lock)
    monkeypatch.setattr(check7, "gpu_visible", lambda: False)
    assert check7.cli_check() == 2
    out, err = capsys.readouterr()
    assert err.strip() == "check-7: nvidia-smi found no GPU"
    body = json.loads(out)
    assert body["pass"] is False and body["missing"] == "check-7: nvidia-smi found no GPU"


def test_clone_missing_names_the_part(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(check7, "gpu_visible", lambda: True)
    assert check7.prerequisites(_lock(), state=tmp_path) == "check-7: run make setup-parts (part 1 missing)"


def test_video_missing_names_the_clip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(check7, "gpu_visible", lambda: True)
    lk = stub_modules(tmp_path / "modules")
    for n in range(1, 7):
        lk.path(n).mkdir(parents=True)
    monkeypatch.setattr(check7.setup_parts, "setup_all", lambda **kw: {"ok": True, "parts": {}})
    monkeypatch.setattr(check7.videos, "verify_all", lambda state=None: ["videos: pexels-1 clip.mp4 is missing (run make videos)"])
    assert check7.prerequisites(lk, state=tmp_path) == "check-7: run make videos (pexels-1 missing or changed)"


def _lock_with_clones(tmp_path: Path) -> modules.Modules:
    lk = stub_modules(tmp_path / "modules")
    for n in range(1, 7):
        lk.path(n).mkdir(parents=True)
    return lk


def test_part_setup_runs_for_every_part_before_the_videos_check(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(check7, "gpu_visible", lambda: True)
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(check7.setup_parts, "setup_all", lambda **kw: calls.append(kw) or {"ok": True, "parts": {}})
    monkeypatch.setattr(check7.videos, "verify_all", lambda state=None: [])
    lk = _lock_with_clones(tmp_path)
    assert check7.prerequisites(lk, state=tmp_path) is None
    assert len(calls) == 1 and calls[0]["lock"] is lk and "only" not in calls[0]


def test_part_setup_failure_is_a_missing_prerequisite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                      capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(check7, "gpu_visible", lambda: True)
    bad = {"ok": False, "parts": {"1": {"ok": True, "error": None}, "3": {"ok": False, "error": "part 3: setup step failed"}}}
    monkeypatch.setattr(check7.setup_parts, "setup_all", lambda **kw: bad)
    monkeypatch.setattr(check7.videos, "verify_all", lambda state=None: pytest.fail("videos checked after a setup failure"))
    lk = _lock_with_clones(tmp_path)
    assert check7.prerequisites(lk, state=tmp_path) == "check-7: part setup failed: part 3: setup step failed"
    monkeypatch.setattr(modules, "load", lambda: lk)
    assert check7.cli_check() == 2
    out, err = capsys.readouterr()
    assert err.startswith("check-7: part setup failed: ")
    assert json.loads(out)["pass"] is False


def test_clone_supports_finds_flag(tmp_path: Path) -> None:
    (tmp_path / "cli.py").write_text('p.add_argument("--keyframes-densify")\n')
    assert check7.clone_supports(tmp_path, "--keyframes-densify")
    assert not check7.clone_supports(tmp_path, "--replay")


def test_passes_requires_every_gate() -> None:
    base = {"entry_ok": True, "followers_matched": "2/2", "ok_status_both_paths": 1, "faults_compared": 1}
    assert check7.passes(base)
    assert not check7.passes({**base, "followers_matched": "1/2"})
    assert not check7.passes({**base, "faults_compared": 0})
    assert not check7.passes({**base, "entry_ok": False})


class _ServeStarted(Exception):
    """Raised by the fake `Popen`: the test only needs the serve call's env."""


def test_the_check_serves_with_the_clip_size_cap_off(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # TICKET-067 (check-7.md step 2): the direct path reads the test clip as is, so the app may not resize it
    seen: dict[str, Any] = {}

    def popen(argv: list[str], **kw: Any) -> None:
        seen.update(argv=argv, env=kw["env"])
        raise _ServeStarted

    monkeypatch.setenv("SIMON7_CLIP_MAX_SIDE", "960")
    monkeypatch.setattr(check7.modules, "load", _lock)
    monkeypatch.setattr(check7, "prerequisites", lambda lock: None)
    monkeypatch.setattr(check7.videos, "load_manifest", lambda: {"clips": CLIPS})
    monkeypatch.setattr(check7.movement, "check_movement", lambda: MOV)
    monkeypatch.setattr(check7.config, "check_dir", lambda: tmp_path)
    monkeypatch.setattr(check7.subprocess, "Popen", popen)
    with pytest.raises(_ServeStarted):
        check7.cli_check()
    assert "serve" in seen["argv"]
    assert seen["env"]["SIMON7_CLIP_MAX_SIDE"] == "0" and seen["env"]["SIMON7_PHRASING"] == check7.PHRASING
