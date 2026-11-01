"""Mode scoring (ADR-0008, amended): Part 5's native `--profile`, path selection and a real Part 5 run."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from part7 import modules
from part7.parts import p5_analyse, probe
from support import make_lock
from test_trainer_chain_and_harness import step


# ----- p5_analyse path selection (Part 5 faked) ----------------------------------------------------------
def _analyse(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, help_flags: str, mode: str | None) -> tuple[list[list[str]], list[str], Path]:
    probe.clear_cache()
    (tmp_path / "clone").mkdir(parents=True)
    lk = make_lock()
    monkeypatch.setattr(type(lk), "path", lambda self, n: tmp_path / "clone")
    argvs: list[list[str]] = []

    def fake(part: Any, argv: list[str], **kw: Any) -> Any:
        argvs.append(list(argv))
        if "--out" in argv:
            Path(argv[argv.index("--out") + 1]).write_text(json.dumps({"status": {"code": "ok"}, "score": {"value": 5}, "faults": []}))
        return step(5, 0, help_flags)

    monkeypatch.setattr(p5_analyse.runner, "run", fake)
    _, analysis, _, notes = p5_analyse.run(tmp_path / "e.json", tmp_path / "f.json", tmp_path / "w", lock=lk,
                                           state=tmp_path / "s", mode=mode)
    probe.clear_cache()
    return argvs, notes, analysis


def test_profile_flag_wins_when_part5_offers_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    argvs, notes, analysis = _analyse(tmp_path, monkeypatch, "--replay --profile", "rehab")
    argv = argvs[-1]
    assert argv[argv.index("--profile"):][:2] == ["--profile", "rehab"] and "-m" in argv
    assert notes == []
    assert "profile" not in json.loads(analysis.read_text())  # Part 5 writes its own
    assert "part 5 scoring: Part 5 --profile rehab" in (tmp_path / "w" / "steps" / "part7.log").read_text()


def test_part5_profile_is_not_overwritten(tmp_path: Path) -> None:
    out = tmp_path / "a.json"
    out.write_text(json.dumps({"profile": "from-part5"}))
    p5_analyse._add_profile(out, "dance")
    assert json.loads(out.read_text()) == {"profile": "from-part5"}


@pytest.mark.parametrize("mode", [None, "fitness"])
def test_plain_cli_for_fitness_and_no_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str | None) -> None:
    argvs, notes, analysis = _analyse(tmp_path, monkeypatch, "--replay", mode)
    assert "-m" in argvs[-1] and "--profile" not in argvs[-1]
    assert not any("unavailable" in n for n in notes)
    assert json.loads(analysis.read_text()).get("profile") == mode


@pytest.mark.parametrize("mode", ["dance", "rehab"])
def test_part5_without_profile_gets_the_plain_cli_and_a_note(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str) -> None:
    argvs, notes, analysis = _analyse(tmp_path, monkeypatch, "--replay", mode)
    assert "--profile" not in argvs[-1]
    assert p5_analyse.NOTE_UNAVAILABLE.format(mode=mode) in notes
    assert "profile" not in json.loads(analysis.read_text())  # nothing was changed, nothing is claimed


# ----- the real Part 5 on its own fixtures -------------------------------------------------------
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
        pytest.skip("pinned Part 5 has no --profile")
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
