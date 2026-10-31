"""Mode scoring in Part 7 (ADR-0008): rules variants, the runner, path selection and a real Part 5 run."""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any

import pytest

from part7 import mode_rules, modules
from part7.parts import p5_analyse, probe
from support import make_lock
from test_trainer_chain_and_harness import _capture_runner, step

RUNNER = Path(p5_analyse._MODE_RUNNER)
BASE: dict[str, Any] = {
    "default": {"threshold_deg": 10.0, "min_fraction": 0.38, "min_run_frames": 4, "min_overlap": 0.3},
    "measures": {m: {"threshold_deg": 10.0 + i} for i, m in enumerate(
        [*mode_rules.DANCE_STYLE, *mode_rules.REHAB_RANGE, "neck_only"])},
    "explained_by": {"_comment": "x", "thigh_out": ["foot_out"], "forearm_out": ["upper_arm_out"],
                     "head_forward": ["trunk_lean_forward"]},
    "explained_by_opposite": {"thigh_out": ["knee_valgus"]},
    "guard": {"max_residual": 0.5},
    "score": {"version": "simon.score.v1", "slope": 5.9, "cap": 31.1, "base": 16, "bands": [[0, "F"]]},
}

CAUSES = {"foot_out", "upper_arm_out", "trunk_lean_forward", "knee_valgus"}


# ----- variant derivation -------------------------------------------------------------------------------
def test_fitness_and_none_equal_the_base() -> None:
    assert mode_rules.derive(BASE, "fitness") == BASE and mode_rules.derive(BASE, None) == BASE


def test_derive_never_edits_its_input() -> None:
    before = json.dumps(BASE, sort_keys=True)
    mode_rules.derive(BASE, "rehab")
    assert json.dumps(BASE, sort_keys=True) == before


def test_dance_multipliers() -> None:
    out = mode_rules.derive(BASE, "dance")
    for m in set(mode_rules.DANCE_STYLE) - CAUSES:
        assert out["measures"][m]["threshold_deg"] == pytest.approx(BASE["measures"][m]["threshold_deg"] * 1.5)
    for m in (*(set(mode_rules.REHAB_RANGE) - CAUSES), "neck_only"):
        assert out["measures"][m] == BASE["measures"][m]
    assert out["default"] == BASE["default"] and out["score"]["slope"] == pytest.approx(5.31)


def test_rehab_multipliers() -> None:
    out = mode_rules.derive(BASE, "rehab")
    for m in set(mode_rules.REHAB_RANGE) - CAUSES:
        assert out["measures"][m]["threshold_deg"] == pytest.approx(BASE["measures"][m]["threshold_deg"] * 1.25)
    for m in (*(set(mode_rules.DANCE_STYLE) - CAUSES), "neck_only"):
        assert out["measures"][m]["threshold_deg"] == pytest.approx(BASE["measures"][m]["threshold_deg"] * 1.6)
    assert out["default"]["threshold_deg"] == pytest.approx(16.0) and out["default"]["min_run_frames"] == 6
    assert out["default"]["min_fraction"] == 0.38 and out["score"]["slope"] == pytest.approx(4.72)


def test_causes_are_found_and_never_loosened() -> None:
    assert mode_rules.causes_of(BASE) == CAUSES
    for mode in ("dance", "rehab"):
        out = mode_rules.derive(BASE, mode)
        for m in CAUSES:
            assert out["measures"][m]["threshold_deg"] == BASE["measures"][m]["threshold_deg"]
            assert out["measures"][m]["min_run_frames"] == 4  # pinned, though the rehab default moves to 6


def test_a_cause_without_its_own_entry_is_pinned_to_the_default() -> None:
    base = {"default": {"threshold_deg": 10.0, "min_run_frames": 4}, "measures": {},
            "explained_by": {"thigh_out": ["foot_out"]}}
    out = mode_rules.derive(base, "rehab")
    assert out["measures"]["foot_out"] == {"threshold_deg": 10.0, "min_run_frames": 4}
    assert out["default"]["threshold_deg"] == 16.0


@pytest.mark.parametrize("mode", ["dance", "rehab"])
def test_a_mode_is_never_tighter_than_fitness(mode: str) -> None:
    out = mode_rules.derive(BASE, mode)
    for name, entry in BASE["measures"].items():
        assert out["measures"][name]["threshold_deg"] >= entry["threshold_deg"]
    assert out["default"]["threshold_deg"] >= BASE["default"]["threshold_deg"]
    assert out["default"]["min_run_frames"] >= BASE["default"]["min_run_frames"]
    assert out["score"]["slope"] <= BASE["score"]["slope"]
    for key in ("guard", "bands"):  # guard, cap, base, bands are untouched
        assert out.get(key, out["score"].get(key)) == BASE.get(key, BASE["score"].get(key))
    assert out["score"]["cap"] == BASE["score"]["cap"] and out["score"]["base"] == BASE["score"]["base"]


def test_a_measure_missing_from_the_base_takes_the_default_threshold() -> None:
    base = {"default": {"threshold_deg": 10.0, "min_run_frames": 4}, "measures": {}}
    assert mode_rules.derive(base, "rehab")["measures"]["elbow_flexion"]["threshold_deg"] == 12.5
    assert mode_rules.derive(base, "dance")["measures"]["foot_out"]["threshold_deg"] == 15.0
    assert "elbow_flexion" not in mode_rules.derive(base, "dance")["measures"]


def test_a_base_without_score_knobs_keeps_working() -> None:
    out = mode_rules.derive({"default": {"threshold_deg": 10.0}, "measures": {}}, "rehab")
    assert "score" not in out


def test_variant_is_read_from_the_clone_rules_file(tmp_path: Path) -> None:
    (tmp_path / "part5").mkdir()
    (tmp_path / "part5" / "rules.json").write_text(json.dumps(BASE))
    path = mode_rules.write_variant(tmp_path, "dance", tmp_path / "w" / "rules-dance.json")
    assert json.loads(path.read_text()) == mode_rules.derive(BASE, "dance")


# ----- the runner, against a fake Part 5 package --------------------------------------------------------
FAKE = {
    "__init__.py": "",
    "detect.py": "def load_rules(path=None):\n    return {'who': 'standard'}\n",
    "score.py": "from .detect import load_rules\n",
    "pipeline.py": "from .detect import load_rules\ndef run():\n    return load_rules()\n",
    "cli.py": textwrap.dedent('''
        import json, sys
        from . import pipeline, score
        def main(argv=None):
            out = argv[argv.index("--out") + 1]
            json.dump({"argv": argv, "rules": pipeline.run(), "score_rules": score.load_rules()}, open(out, "w"))
            return 3
    '''),
}


def _fake_part5(root: Path, drop: str | None = None) -> Path:
    pkg = root / "part5"
    pkg.mkdir(parents=True)
    for name, text in FAKE.items():
        if name != drop:
            (pkg / name).write_text(text)
    return root


def _run_runner(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(RUNNER), *args], cwd=cwd, capture_output=True, text=True, timeout=60)


def test_runner_patches_every_load_rules_and_passes_argv_through(tmp_path: Path) -> None:
    clone = _fake_part5(tmp_path / "clone")
    rules = tmp_path / "r.json"
    rules.write_text(json.dumps({"who": "variant"}))
    out = tmp_path / "out.json"
    done = _run_runner(clone, "--rules", str(rules), "analyse", "--expected", "e", "--out", str(out), "--replay", "r")
    assert done.returncode == 3, done.stderr  # Part 5's own exit code comes back
    doc = json.loads(out.read_text())
    assert doc["argv"] == ["analyse", "--expected", "e", "--out", str(out), "--replay", "r"]
    assert doc["rules"] == {"who": "variant"} and doc["score_rules"] == {"who": "variant"}


def test_runner_probe_ok_and_unavailable(tmp_path: Path) -> None:
    ok = _run_runner(_fake_part5(tmp_path / "a"), "--probe")
    assert ok.returncode == 0 and "part5.pipeline" in ok.stdout
    for missing in ("pipeline.py", "detect.py"):
        bad = _run_runner(_fake_part5(tmp_path / missing, drop=missing), "--probe")
        assert bad.returncode == 1 and "unavailable" in bad.stdout


def test_runner_refuses_missing_rules_argument(tmp_path: Path) -> None:
    assert _run_runner(_fake_part5(tmp_path / "c"), "analyse").returncode == 2


# ----- p5_analyse path selection (runner faked) ----------------------------------------------------------
def _analyse(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, help_flags: str, mode: str | None,
             runner_exit: int = 0, mode_faults: tuple[str, ...] = (), std_faults: tuple[str, ...] = ()) -> tuple[list[list[str]], list[str], Path]:
    probe.clear_cache()
    clone_rules = tmp_path / "clone" / "part5"
    clone_rules.mkdir(parents=True)
    (clone_rules / "rules.json").write_text(json.dumps(BASE))
    lk = make_lock()
    monkeypatch.setattr(type(lk), "path", lambda self, n: tmp_path / "clone")

    def out_for(argv: list[str]) -> Any:
        if "--probe" in argv:
            return step(5, runner_exit)
        return step(5, 0, help_flags)

    argvs: list[list[str]] = []

    def fake(part: Any, argv: list[str], **kw: Any) -> Any:
        argvs.append(list(argv))
        if "--out" in argv:
            faults = mode_faults if "--rules" in argv else std_faults
            Path(argv[argv.index("--out") + 1]).write_text(json.dumps({
                "status": {"code": "ok"}, "score": {"value": 5 + 5 * ("--rules" in argv)},
                "faults": [{"measure": m, "side": "left"} for m in faults]}))
        return out_for(argv)

    monkeypatch.setattr(p5_analyse.runner, "run", fake)
    _, analysis, _, notes = p5_analyse.run(tmp_path / "e.json", tmp_path / "f.json", tmp_path / "w", lock=lk,
                                           state=tmp_path / "s", mode=mode)
    probe.clear_cache()
    return argvs, notes, analysis


def test_profile_flag_wins_when_part5_offers_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    argvs, notes, analysis = _analyse(tmp_path, monkeypatch, "--replay --profile", "rehab")
    argv = argvs[-1]
    assert argv[argv.index("--profile"):][:2] == ["--profile", "rehab"] and "-m" in argv
    assert not any("--probe" in a for a in argvs) and notes == []
    assert "profile" not in json.loads(analysis.read_text())  # Part 5 writes its own


@pytest.mark.parametrize("mode", ["dance", "rehab"])
def test_mode_runner_path_for_dance_and_rehab(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str) -> None:
    argvs, notes, analysis = _analyse(tmp_path, monkeypatch, "--replay", mode)
    argv = argvs[-1]
    assert str(RUNNER) in argv and "--profile" not in argv and "-m" not in argv
    variant = Path(argv[argv.index("--rules") + 1])
    assert json.loads(variant.read_text()) == mode_rules.derive(BASE, mode)
    assert argv[argv.index("--rules") + 2] == "analyse" and "--expected" in argv
    assert not any("unavailable" in n for n in notes)
    doc = json.loads(analysis.read_text())
    assert doc["profile"] == mode and doc["profile_source"] == "part7-rules" and doc["score"] == {"value": 10}
    log = (tmp_path / "w" / "steps" / "part7.log").read_text()
    assert f"part 5 scoring: Part 7 {mode} rules" in log and f"{mode} rules kept" in log
    standard = [a for a in argvs if "-m" in a and "--out" in a]
    assert len(standard) == 1 and standard[0].index("--out") and argvs.index(standard[0]) < argvs.index(argv)


def test_mode_adding_a_fault_falls_back_to_the_standard_result(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    argvs, notes, analysis = _analyse(tmp_path, monkeypatch, "--replay", "dance",
                                      mode_faults=("foot_out", "elbow_flexion"), std_faults=("foot_out",))
    doc = json.loads(analysis.read_text())
    assert doc["score"] == {"value": 5} and [f["measure"] for f in doc["faults"]] == ["foot_out"]
    assert doc["profile"] == "fitness" and doc["profile_source"] == "part7-rules"
    assert mode_rules.NOTE_ADDS_FAULT in notes
    assert "Mode rules would add a fault the standard rules do not; standard rules used" in notes
    assert "dropped, standard rules used" in (tmp_path / "w" / "steps" / "part7.log").read_text()


def test_mode_with_fewer_faults_is_kept(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, notes, analysis = _analyse(tmp_path, monkeypatch, "--replay", "rehab",
                                  mode_faults=("foot_out",), std_faults=("foot_out", "elbow_flexion"))
    doc = json.loads(analysis.read_text())
    assert doc["score"] == {"value": 10} and doc["profile"] == "rehab" and mode_rules.NOTE_ADDS_FAULT not in notes


def test_part5_profile_is_not_overwritten(tmp_path: Path) -> None:
    out = tmp_path / "a.json"
    out.write_text(json.dumps({"profile": "from-part5"}))
    p5_analyse._add_profile(out, "dance")
    assert json.loads(out.read_text()) == {"profile": "from-part5"}


@pytest.mark.parametrize("mode", [None, "fitness"])
def test_plain_cli_for_fitness_and_no_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str | None) -> None:
    argvs, notes, analysis = _analyse(tmp_path, monkeypatch, "--replay", mode)
    assert "-m" in argvs[-1] and "--rules" not in argvs[-1] and not any("--probe" in a for a in argvs)
    assert not any("unavailable" in n for n in notes)
    assert json.loads(analysis.read_text()).get("profile") == mode


def test_unpatchable_part5_falls_back_with_the_note(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    argvs, notes, analysis = _analyse(tmp_path, monkeypatch, "--replay", "rehab", runner_exit=1)
    assert "-m" in argvs[-1] and "--rules" not in argvs[-1]
    assert mode_rules.NOTE_UNAVAILABLE.format(mode="rehab") in notes
    assert "Scoring rules for rehab unavailable in this Part 5; standard rules used" in notes
    assert "profile" not in json.loads(analysis.read_text())  # nothing was changed, nothing is claimed


def test_probe_result_is_cached_per_clone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    probe.clear_cache()
    calls: list[Any] = []
    monkeypatch.setattr(p5_analyse.runner, "run", lambda *a, **k: calls.append(a) or step(5, 0))
    assert p5_analyse.mode_runner_ok(tmp_path) and p5_analyse.mode_runner_ok(tmp_path) and len(calls) == 1
    probe.clear_cache()


# ----- the real pinned Part 5 on its own fixtures -------------------------------------------------------
TAKES = (
    ("dance", "dance_45_good_08_elbow_bent-right+arms_wider-both"),
    ("dance", "dance_45_good_03_foot_out-right"),
    ("exercise", "exercise_45_good_08_trunk_lean-center+arms_wider-right"),
    ("exercise", "exercise_45_low_07_knee_caving-right"),
)


def _faults(doc: dict[str, Any]) -> set[tuple[str, str]]:
    return {(f["measure"], f["side"]) for f in doc["faults"]}


def _unmatched(mode_doc: dict[str, Any], fit_doc: dict[str, Any]) -> list[tuple[str, str, Any, Any]]:
    """Mode faults with no fitness fault of the same measure, side and direction whose follower span holds theirs.

    Part 5 (profiles AC-PROF-16): under dance and rehab a fault reports the counted run that overlaps fitness's
    run, so its start can move later but never outside fitness's follower frames. `at_s` is not compared: it is
    rounded to 0.1 s while the frames are exact.
    """
    out = []
    for f in mode_doc["faults"]:
        lo, hi = f["follower_frames"]
        if not any(g["measure"] == f["measure"] and g["side"] == f["side"] and g.get("direction") == f.get("direction")
                   and g["follower_frames"][0] <= lo and hi <= g["follower_frames"][1] for g in fit_doc["faults"]):
            out.append((f["measure"], f["side"], f.get("direction"), f["follower_frames"]))
    return out


@pytest.mark.parametrize("kind,take", TAKES)
def test_real_part5_native_profiles(tmp_path: Path, kind: str, take: str) -> None:
    """TICKET-094: at Part 5 d655d50 the probe finds `--profile`; no Part 7 rules run and no part7 field is added."""
    lk = modules.load()
    base = lk.path("5") / "fixtures" / "input"
    if not (base / "followers" / kind / take / "skeleton.json").is_file() or not (lk.path("5") / "part5").is_dir():
        pytest.skip("Part 5 submodule not checked out")
    probe.clear_cache()
    if not probe.has_flag(5, p5_analyse._ANALYSE_ARGV, lk.path("5"), "--profile", lk):
        pytest.skip("pinned Part 5 has no --profile (older pin: the Part 7 runner is the fallback)")
    got: dict[str, dict[str, Any]] = {}
    for mode in (None, "fitness", "dance", "rehab"):
        _, path, code, notes = p5_analyse.run(
            base / "expected" / kind / "animation.json", base / "followers" / kind / take / "skeleton.json",
            tmp_path / str(mode), lock=lk, mode=mode)
        assert code == "ok" and not any("unavailable" in n or "would add" in n for n in notes), notes
        got[str(mode)] = json.loads(path.read_text())
    plain, fit = got["None"], got["fitness"]
    assert plain["profile"] == "fitness" and fit["profile"] == "fitness"  # no mode: Part 5 reports fitness
    assert fit["score"] == plain["score"] and _faults(fit) == _faults(plain)
    for mode in ("dance", "rehab"):
        doc = got[mode]
        assert doc["profile"] == mode and "profile_source" not in doc, "native profile adds no part7 field"
        assert 0 <= doc["score"]["value"] <= 100 and doc["score"]["grade"], doc["score"]
        assert not _unmatched(doc, fit), (mode, _unmatched(doc, fit))
