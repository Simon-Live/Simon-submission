"""Shared test setup: no test reads the operator's key files, spends on the real Meta ledger or takes the host's
GPU lock.

Every test starts with PART2_KEY_DIR pointing at an empty directory (mode 700), MODEL_API_KEY and
HF_TOKEN unset, META_SPEND_LEDGER in a temp dir and PART2_GPU_LOCK in a temp dir (a `part2 run` with the gpu
backend takes the lock around its estimate; a held host lock would make it wait). A test that needs a key writes a
fake one with `fake_key`.
"""
import os

import pytest


@pytest.fixture(autouse=True)
def _isolated_keys_and_ledger(tmp_path_factory, monkeypatch):
    keys = tmp_path_factory.mktemp("operator-keys")
    os.chmod(keys, 0o700)
    monkeypatch.setenv("PART2_KEY_DIR", str(keys))
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.setenv("META_SPEND_LEDGER", str(tmp_path_factory.mktemp("ledger") / "meta_spend.jsonl"))
    monkeypatch.setenv("PART2_GPU_LOCK", str(tmp_path_factory.mktemp("gpu-lock") / "gpu.lock"))
    return keys


def fake_key(name: str, value: str = "fake-key-for-tests") -> None:
    """Write a fake key file into the test key directory (mode 600, as keys.present requires)."""
    path = os.path.join(os.environ["PART2_KEY_DIR"], name)
    with open(path, "w") as f:
        f.write(value)
    os.chmod(path, 0o600)
