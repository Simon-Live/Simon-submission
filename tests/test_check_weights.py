"""AC-B12: envs/gpu-cu128/check_weights.py checks mirrored weights against OFFICIAL_SHA256 in k8s/infer_one.py.

Runs on a copy of the team's file and one-byte fake weights; nothing is downloaded.
"""
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "envs" / "gpu-cu128" / "check_weights.py"
INFER_ONE = ROOT / "k8s" / "infer_one.py"
REPO = "jetjodh/sam-3d-body-dinov3"
FILES = ("model.ckpt", "assets/mhr_model.pt")


def run(infer_one, weights_dir):
    return subprocess.run([sys.executable, str(SCRIPT), "--infer-one", str(infer_one), "--dir", str(weights_dir),
                           "--repo", REPO], capture_output=True, text=True)


@pytest.fixture
def fakes(tmp_path):
    """One-byte stand-ins for both weight files, a different byte each."""
    d = tmp_path / "snapshot"
    for i, name in enumerate(FILES):
        (d / name).parent.mkdir(parents=True, exist_ok=True)
        (d / name).write_bytes(bytes([i]))
    return d


def with_digests_of(fakes_dir, dest):
    """A copy of k8s/infer_one.py whose OFFICIAL_SHA256 values are the fakes' digests."""
    text = INFER_ONE.read_text()
    for name, want in official():
        text = text.replace(want, hashlib.sha256((fakes_dir / name).read_bytes()).hexdigest())
    dest.write_text(text)
    return dest


def official():
    sys.path.insert(0, str(SCRIPT.parent))
    try:
        from check_weights import official_digests
    finally:
        sys.path.pop(0)
    return official_digests(INFER_ONE).items()


def test_digests_are_parsed_from_the_team_file_not_copied():
    digests = dict(official())
    assert set(digests) == set(FILES)
    assert all(len(v) == 64 for v in digests.values())
    assert all(v not in SCRIPT.read_text() for v in digests.values())


def test_mismatch_exits_1_naming_file_and_repo(tmp_path, fakes):
    copy = tmp_path / "infer_one.py"
    shutil.copy(INFER_ONE, copy)
    r = run(copy, fakes)
    assert r.returncode == 1
    assert r.stderr.strip() == f"setup-gpu: model.ckpt from {REPO} does not match the official checksum"
    assert r.stdout == ""


def test_second_file_mismatch_is_named(tmp_path, fakes):
    copy = with_digests_of(fakes, tmp_path / "infer_one.py")
    (fakes / "assets/mhr_model.pt").write_bytes(b"\x07")
    r = run(copy, fakes)
    assert r.returncode == 1
    assert "assets/mhr_model.pt from" in r.stderr and "does not match the official checksum" in r.stderr


def test_match_exits_0_and_prints_digests(tmp_path, fakes):
    copy = with_digests_of(fakes, tmp_path / "infer_one.py")
    r = run(copy, fakes)
    assert r.returncode == 0, r.stderr
    got = json.loads(r.stdout)
    assert got == {name: hashlib.sha256((fakes / name).read_bytes()).hexdigest() for name in FILES}


def test_missing_file_exits_1(tmp_path, fakes):
    copy = with_digests_of(fakes, tmp_path / "infer_one.py")
    (fakes / "model.ckpt").unlink()
    r = run(copy, fakes)
    assert r.returncode == 1
    assert "model.ckpt from" in r.stderr and "is missing" in r.stderr


def test_file_without_official_digests_exits_2(tmp_path, fakes):
    bad = tmp_path / "infer_one.py"
    bad.write_text("OTHER = {}\n")
    r = run(bad, fakes)
    assert r.returncode == 2
    assert "OFFICIAL_SHA256 not found" in r.stderr


def test_digest_literal_is_never_executed(tmp_path, fakes):
    """The team file is parsed with ast; a call in the literal is rejected, not run."""
    marker = tmp_path / "ran"
    bad = tmp_path / "infer_one.py"
    bad.write_text(f"OFFICIAL_SHA256 = {{'model.ckpt': open({str(marker)!r}, 'w').name}}\n")
    r = run(bad, fakes)
    assert r.returncode == 2 and not marker.exists()
