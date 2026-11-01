"""Shared fixtures and fakes of the tracker tests (test_trackers.py, test_trackers_adapters.py): an empty key dir,
private ledgers, no network, fake frames, fake trackers and a fake Meta client. Each test module imports the names it
uses; pytest finds the `env` fixture in the module that imports it.
"""
import json
import os
import types
from pathlib import Path

import pytest

from part2 import meta_api, trackers


FAKE = "FAKE-KEY-DO-NOT-PRINT-123"
H, W = 24, 64
MASK = [[1, 1], [1, 1]]


# --- fixtures ---------------------------------------------------------------------------------------

@pytest.fixture
def env(tmp_path, monkeypatch):
    """Empty key dir, private ledgers, no tracker named, no parity record."""
    d = tmp_path / "keys"
    d.mkdir()
    os.chmod(d, 0o700)
    monkeypatch.setenv("PART2_KEY_DIR", str(d))
    monkeypatch.setenv("META_SPEND_LEDGER", str(tmp_path / "ledger.jsonl"))
    monkeypatch.setenv("PART2_GPU_LOCK", str(tmp_path / "gpu.lock"))
    for name in ("MODEL_API_KEY", "HF_TOKEN", "PART2_TRACKER", "META_BUDGET_USD", "PART2_JOB_LEDGER",
                 "PART2_JOB_BUDGET_USD"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(trackers, "PARITY_FILE", tmp_path / "no-parity.json")
    monkeypatch.setattr(meta_api, "_request", _no_network)
    return types.SimpleNamespace(keys=d, tmp=tmp_path)


def _no_network(*a, **k):
    raise AssertionError("no network call may be made")


def put_key(d, name, value=FAKE):
    p = Path(d) / name
    p.write_text(value + "\n")
    os.chmod(p, 0o600)


def make_frames(tmp_path, n=4, fps=5.0, start=0):
    d = tmp_path / f"frames{n}"
    d.mkdir()
    recs = [{"frame": start + i, "t_ms": i * 1000.0 / fps, "file": f"{i:06d}.jpg"} for i in range(n)]
    for r in recs:
        (d / r["file"]).write_bytes(b"x")
    (d / "frames.json").write_text(json.dumps({"source": "test", "frames": recs}))
    return d, recs


def ledger_line(path, usd):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps({"ts": 0, "model": "sam-3.1", "what": "test", "usd": usd}) + "\n")


def fake_tracker(name, calls, ok=(True, "")):
    class Fake(trackers.Tracker):
        def __init__(self, **_):
            pass

        def available(self, n_frames=None):
            return ok

        def detect(self, frames_dir, recs):
            calls.append(name)
            return {r["frame"]: [{"id": 9, "bbox": [0, 0, 2, 2], "mask": MASK, "confidence": 0.5}] for r in recs}

    Fake.name = name
    return Fake


def api_client(seen):
    def client(frames_dir, recs, budget=None):
        seen.append(os.environ.get("MODEL_API_KEY"))
        return {r["frame"]: [{"id": 5 if i % 2 == 0 else 2, "bbox": [1, 1, 2, 2], "mask": MASK, "confidence": 0.9}]
                for i, r in enumerate(recs)}
    return client


def windows(secret, w=8):
    return [secret[i:i + w] for i in range(len(secret) - w + 1)]
