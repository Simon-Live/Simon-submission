"""Tests for `part7.parts.*` adapters (TICKET-005, 010, AC-H5, AC-H8, AC-H10, AC-008)."""

from __future__ import annotations

import json
from pathlib import Path
import stat
import sys
import pytest

from part7 import config, modules, setup_parts
from support import stub_modules
from part7.parts import (
    p1_keyframes,
    p2_pose,
    p3_skeleton,
    p4_animate,
    p5_analyse,
    p6_catalog,
)


def _stub_lock(state: Path) -> modules.Modules:
    lk = stub_modules(state / "modules")
    for n in range(1, 7):
        lk.path(n).mkdir(parents=True, exist_ok=True)
    return lk


def test_p1_spend_cap_reads_the_part_1_module_ledger(state_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-H10: a `.meta-spend.json` of >= $5 in the Part 1 module triggers the spend cap."""
    monkeypatch.setenv("SIMON7_MODULES_DIR", str(state_dir / "modules"))
    module1 = state_dir / "modules" / "part-1"
    module1.mkdir(parents=True)
    assert p1_keyframes.total_spend_usd(state_dir) == 0.0
    (module1 / ".meta-spend.json").write_text(json.dumps({"total_usd": 5.05}), encoding="utf-8")

    assert p1_keyframes.total_spend_usd(state_dir) == pytest.approx(5.05)

    video = state_dir / "clip.mp4"
    video.write_bytes(b"fake-video-bytes")
    step, kf_path, note = p1_keyframes.run(video, state_dir / "work", state=state_dir)
    assert step is None
    assert kf_path is None
    assert note == "spend cap"


def test_p1_missing_key_and_secret_never_leaks(tmp_path: Path, state_dir: Path) -> None:
    """AC-008, AC-H5: Fake key fed through Part 1 adapter is absent from every file under job work dir."""
    lk = _stub_lock(state_dir)
    clone1 = lk.path("1")
    video = tmp_path / "trainer.mp4"
    video.write_bytes(b"trainer-clip-bytes")

    empty_keys = tmp_path / "empty_keys"
    empty_keys.mkdir()
    step, kf, note = p1_keyframes.run(
        video,
        tmp_path / "work_nokey",
        lock=lk,
        state=state_dir,
        keys_dir=empty_keys,
    )
    assert step is None
    assert kf is None
    assert note == "key frames from Part 3, Part 1 unavailable"

    # Now create a stub keyframe_finder.from_video in clone1 that prints the secret from .env
    # and verifies .env mode is 0600, then writes out/<stem>/keyframes.json
    kf_pkg = clone1 / "keyframe_finder"
    kf_pkg.mkdir(parents=True, exist_ok=True)
    (kf_pkg / "__init__.py").write_text("", encoding="utf-8")
    (kf_pkg / "from_video.py").write_text(
        "import json, os, pathlib, stat, sys\n"
        "env_file = pathlib.Path('.env')\n"
        "assert env_file.is_file(), '.env must exist during Part 1 run'\n"
        "assert stat.S_IMODE(env_file.stat().st_mode) == 0o600\n"
        "print('Loaded env:', env_file.read_text())\n"
        "rel = pathlib.Path(sys.argv[1])\n"
        "out_dir = pathlib.Path('out') / rel.stem\n"
        "out_dir.mkdir(parents=True, exist_ok=True)\n"
        "(out_dir / 'keyframes.json').write_text(json.dumps({'format': 'simon.keyframes/part1', 'people': []}))\n",
        encoding="utf-8",
    )

    kdir = tmp_path / "keys"
    kdir.mkdir()
    fake_secret = "SECRET_META_KEY_DO_NOT_LOG_987654"
    (kdir / "MODEL_API_KEY").write_text(fake_secret, encoding="utf-8")

    work_dir = tmp_path / "job_work"
    step, kf_path, note = p1_keyframes.run(
        video,
        work_dir,
        lock=lk,
        state=state_dir,
        keys_dir=kdir,
    )
    assert step is not None and step["exit"] == 0
    assert kf_path is not None and kf_path.is_file()
    assert note is None
    assert not (clone1 / ".env").exists()
    assert not list((clone1 / "inbox").glob("p7-*.mp4"))

    # AC-008: Assert fake_secret is absent from every file under work_dir
    files_checked = 0
    for fpath in work_dir.rglob("*"):
        if fpath.is_file():
            files_checked += 1
            text = fpath.read_text(encoding="utf-8", errors="replace")
            assert fake_secret not in text, f"Secret leaked in {fpath}"
    assert files_checked >= 2


def test_p3_retries_with_every_5_on_180_degree_refusal(tmp_path: Path, state_dir: Path) -> None:
    """AC-H8: Part 3 180-degree refusal retries once with `every:5`."""
    lk = _stub_lock(state_dir)
    clone3 = lk.path("3")
    p3_pkg = clone3 / "part3"
    p3_pkg.mkdir(parents=True, exist_ok=True)
    (p3_pkg / "__init__.py").write_text("", encoding="utf-8")
    (p3_pkg / "__main__.py").write_text(
        "import pathlib, sys\n"
        "args = sys.argv[1:]\n"
        "kf = args[args.index('--keyframes') + 1]\n"
        "out = pathlib.Path(args[args.index('--out') + 1])\n"
        "kf_out = pathlib.Path(args[args.index('--keyframes-out') + 1])\n"
        "if kf == 'every:10':\n"
        "    print('left_shoulder turns 195.0 degrees (over 180) between keys 10 and 20', file=sys.stderr)\n"
        "    sys.exit(2)\n"
        "out.write_text('{\"format\": \"simon.skeleton.v1\"}')\n"
        "kf_out.write_text('{\"format\": \"simon.keyframes.v1\"}')\n"
        "sys.exit(0)\n",
        encoding="utf-8",
    )

    pose3d = tmp_path / "pose3d.json"
    pose3d.write_text("{}", encoding="utf-8")
    steps, skel, kf_v1, note = p3_skeleton.part4(
        pose3d,
        "every:10",
        tmp_path / "work3",
        lock=lk,
        state=state_dir,
    )
    assert len(steps) == 2
    assert steps[0]["exit"] == 2
    assert steps[1]["exit"] == 0
    assert "every:5" in steps[1]["argv"]
    assert note == "retried Part 3 with every:5"
    assert skel.is_file()
    assert kf_v1.is_file()


def test_p4_and_p5_adapters(tmp_path: Path, state_dir: Path) -> None:
    lk = _stub_lock(state_dir)
    clone4 = lk.path("4")
    mod_dir = clone4 / "src" / "simon_anim"
    mod_dir.mkdir(parents=True, exist_ok=True)
    (mod_dir / "__init__.py").write_text("", encoding="utf-8")
    (mod_dir / "contract.py").write_text("import sys; sys.exit(0)\n", encoding="utf-8")
    (mod_dir / "animate.py").write_text(
        "import pathlib, sys\n"
        "out = pathlib.Path(sys.argv[sys.argv.index('--out') + 1])\n"
        "out.write_text('{\"format\": \"simon.animation.v1\", \"producer\": \"part4\"}')\n",
        encoding="utf-8",
    )

    skel = tmp_path / "skeleton.json"
    kf_v1 = tmp_path / "keyframes.v1.json"
    skel.write_text("{}", encoding="utf-8")
    kf_v1.write_text("{}", encoding="utf-8")

    v_step = p4_animate.validate("skeleton", skel, tmp_path / "work4", lock=lk, state=state_dir)
    assert v_step["exit"] == 0
    a_step, anim_path = p4_animate.run(skel, kf_v1, tmp_path / "work4", lock=lk, state=state_dir)
    assert a_step["exit"] == 0
    assert anim_path.is_file()

    # Part 5 exit 3 (different_movement) is treated as written and extracts status.code
    clone5 = lk.path("5")
    p5_dir = clone5 / "part5"
    p5_dir.mkdir(parents=True, exist_ok=True)
    (p5_dir / "__init__.py").write_text("", encoding="utf-8")
    (p5_dir / "__main__.py").write_text(
        "import json, pathlib, sys\n"
        "out = pathlib.Path(sys.argv[sys.argv.index('--out') + 1])\n"
        "out.write_text(json.dumps({'format': 'simon.analysis.v1', 'status': {'code': 'different_movement', 'text': 'Refused'}, 'faults': []}))\n"
        "sys.exit(3)\n",
        encoding="utf-8",
    )
    # Use python3 directly in PATH by stubbing uv in tmp_path/bin if needed, or test via real uv
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    uv_stub = bin_dir / "uv"
    uv_stub.write_text(
        f"#!/bin/sh\nshift\nexec {sys.executable} \"$@\"\n",
        encoding="utf-8",
    )
    uv_stub.chmod(0o755)
    old_path = os.environ.get("PATH", "")
    os.environ["PATH"] = f"{bin_dir}:{old_path}"
    try:
        step5, analysis_path, code, _notes = p5_analyse.run(
            anim_path,
            skel,
            tmp_path / "work5",
            lock=lk,
            state=state_dir,
        )
    finally:
        os.environ["PATH"] = old_path

    assert step5["exit"] == 3
    assert analysis_path.is_file()
    assert code == "different_movement"


import os


def test_p6_catalog_child_against_real_part6_clone(tmp_path: Path) -> None:
    """Test `p6_catalog.Child` start, health, list_entries, get_entry, ensure_running, and stop."""
    real_lock = modules.load()
    real_state = Path.home() / ".local" / "state" / "simon-part-7"
    if not real_lock.path("6").is_dir():
        pytest.skip("Real Part 6 clone not materialized")

    cat_dir = tmp_path / "catalog"
    child = p6_catalog.Child(
        catalog_dir=cat_dir,
        base_path="/simon-part-7/",
        lock=real_lock,
        parts_state=real_state,
    )
    try:
        port = child.start()
        assert port > 0
        assert child.base_path == "/simon-part-7/catalog"
        h = child.health()
        assert h is not None and h.get("ok") is True
        entries = child.list_entries()
        assert len(entries) >= 1
        first_id = entries[0]["id"]
        manifest = child.get_entry(first_id)
        assert manifest is not None and manifest["id"] == first_id

        # Simulate child crash and verify ensure_running restarts it once
        assert child._proc is not None
        child._proc.terminate()
        child._proc.wait(timeout=3.0)
        assert child.ensure_running() is True
        assert child.health() is not None
    finally:
        child.stop()


def test_real_parts_2_to_6_handoffs_end_to_end(tmp_path: Path) -> None:
    """Run real Parts 2 (doctor), 3, 4, 5, and 6 adapters against Part 2's single pose3d fixture."""
    real_lock = modules.load()
    real_state = Path.home() / ".local" / "state" / "simon-part-7"
    # TICKET-080: a fresh checkout has no part environments; run Part 7's own setup (idempotent per sha and checkout).
    setup = setup_parts.setup_all(lock=real_lock, state=real_state, only=("2", "3", "4", "5", "6"))
    if not setup["ok"]:
        errors = {p: i["error"] for p, i in setup["parts"].items() if i.get("error")}
        pytest.fail(f"part setup failed: {errors}")
    pose3d = real_lock.path("2") / "fixtures" / "output" / "single" / "pose3d.json"
    if not pose3d.is_file():
        pytest.skip("Real Part 2 pose3d fixture not present")

    work = tmp_path / "e2e_work"
    doc2 = p2_pose.doctor(pose3d, work, lock=real_lock, state=real_state)
    assert doc2["exit"] == 0

    steps3, skel_path, kf_v1_path, _ = p3_skeleton.part4(
        pose3d,
        "every:10",
        work,
        lock=real_lock,
        state=real_state,
    )
    assert steps3[-1]["exit"] == 0
    assert p3_skeleton.doctor(skel_path, "part4", work, lock=real_lock, state=real_state)["exit"] == 0

    assert p4_animate.validate("skeleton", skel_path, work, lock=real_lock, state=real_state)["exit"] == 0
    assert p4_animate.validate("keyframes", kf_v1_path, work, lock=real_lock, state=real_state)["exit"] == 0
    step4, anim_path = p4_animate.run(skel_path, kf_v1_path, work, lock=real_lock, state=real_state)
    assert step4["exit"] == 0
    assert p4_animate.validate("animation", anim_path, work, lock=real_lock, state=real_state)["exit"] == 0

    step3_f, follower_path = p3_skeleton.part5(pose3d, work, lock=real_lock, state=real_state)
    assert step3_f["exit"] == 0
    assert p3_skeleton.doctor(follower_path, "part5", work, lock=real_lock, state=real_state)["exit"] == 0

    assert p5_analyse.doctor(anim_path, work, consumer="part5", lock=real_lock, state=real_state)["exit"] == 0
    assert p5_analyse.doctor(follower_path, work, consumer="part5", lock=real_lock, state=real_state)["exit"] == 0
    step5, analysis_path, status_code, _notes = p5_analyse.run(
        anim_path,
        follower_path,
        work,
        lock=real_lock,
        state=real_state,
    )
    assert step5["exit"] in (0, 3)
    assert status_code == "ok"
    assert p5_analyse.doctor(analysis_path, work, consumer="part7", lock=real_lock, state=real_state)["exit"] == 0

    # Test Part 6 import_entry and doctor on the resulting entry
    cat_dir = tmp_path / "catalog"
    imp_step, manifest = p6_catalog.import_entry(
        cat_dir,
        work / "part4",
        "Squat Test",
        "exercise",
        {"keyframes": 3, "skeleton": 3, "animation": 4},
        work,
        lock=real_lock,
        state=real_state,
    )
    assert imp_step["exit"] == 0
    assert manifest is not None
    assert manifest["files_source"] == "import"
    doc6 = p6_catalog.doctor(cat_dir / manifest["id"], work, lock=real_lock, state=real_state)
    assert doc6["exit"] == 0

