"""part2.keys: presence without reading, the single read path, modes, and the value never shown (AC-R03)."""
import logging
import os

import pytest

from part2 import keys

FAKE = "FAKE-KEY-DO-NOT-PRINT-123"


@pytest.fixture
def keydir(tmp_path, monkeypatch):
    d = tmp_path / "operator-keys"
    d.mkdir(mode=0o700)
    os.chmod(d, 0o700)
    monkeypatch.setenv("PART2_KEY_DIR", str(d))
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.delenv("HF_TOKEN", raising=False)
    return d


def put(d, name, value, mode=0o600):
    p = d / name
    p.write_text(value)
    os.chmod(p, mode)
    return p


def test_default_dir_is_the_firm_operator_keys(monkeypatch):
    monkeypatch.delenv("PART2_KEY_DIR", raising=False)
    assert str(keys.key_dir()).endswith(".config/firm/operator-keys")


def test_present_and_read_from_file_strip_newline(keydir):
    put(keydir, "MODEL_API_KEY", FAKE + "\n")
    assert keys.present("MODEL_API_KEY") and keys.check("MODEL_API_KEY") == (True, "file")
    assert keys.read("MODEL_API_KEY") == FAKE


def test_missing_empty_and_unknown(keydir):
    assert keys.check("HF_TOKEN") == (False, f"HF_TOKEN not found in {keydir}")
    put(keydir, "HF_TOKEN", "")
    assert keys.check("HF_TOKEN") == (False, "HF_TOKEN is empty")
    with pytest.raises(keys.KeyMissing, match="HF_TOKEN is empty"):
        keys.read("HF_TOKEN")
    with pytest.raises(ValueError, match="not a key Part 2 reads"):
        keys.present("BASETEN_API_KEY")
    with pytest.raises(ValueError):
        keys.read("BASETEN_API_KEY")


def test_looser_file_mode_counts_as_missing(keydir):
    put(keydir, "MODEL_API_KEY", FAKE, mode=0o644)
    assert keys.check("MODEL_API_KEY") == (False, "MODEL_API_KEY must be mode 600")
    with pytest.raises(keys.KeyMissing) as e:
        keys.read("MODEL_API_KEY")
    assert FAKE not in str(e.value)


def test_looser_dir_mode_counts_as_missing(keydir):
    put(keydir, "MODEL_API_KEY", FAKE)
    os.chmod(keydir, 0o755)
    assert keys.check("MODEL_API_KEY") == (False, f"{keydir} must be mode 700")


def test_env_is_the_second_channel_and_the_file_wins(keydir, monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "from-env")
    assert keys.check("HF_TOKEN") == (True, "env") and keys.read("HF_TOKEN") == "from-env"
    put(keydir, "HF_TOKEN", "from-file")
    assert keys.read("HF_TOKEN") == "from-file"


def test_present_never_opens_the_file(keydir, monkeypatch):
    put(keydir, "MODEL_API_KEY", FAKE)
    import pathlib

    def no_read(*a, **k):
        raise AssertionError("present() must not read the value")

    monkeypatch.setattr(pathlib.Path, "read_text", no_read)
    monkeypatch.setattr(pathlib.Path, "open", no_read)
    assert keys.present("MODEL_API_KEY")


def test_unreadable_dir_is_missing_not_an_error(keydir):
    put(keydir, "MODEL_API_KEY", FAKE)
    os.chmod(keydir, 0o000)
    try:
        if os.access(keydir / "MODEL_API_KEY", os.R_OK):
            pytest.skip("running as a user that ignores directory modes")
        ok, reason = keys.check("MODEL_API_KEY")
        assert not ok and "not readable" in reason
    finally:
        os.chmod(keydir, 0o700)


def test_value_never_logged_printed_or_kept(keydir, capfd, caplog):
    put(keydir, "MODEL_API_KEY", FAKE)
    caplog.set_level(logging.DEBUG)
    assert keys.read("MODEL_API_KEY") == FAKE
    keys.present("MODEL_API_KEY")
    out = capfd.readouterr()
    assert FAKE not in out.out + out.err + caplog.text
    assert not any(isinstance(v, str) and FAKE in v for v in vars(keys).values())
