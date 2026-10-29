"""part2/hashing.py: the one sha256-of-a-file helper, and the callers that now share it (TICKET-030).

The digest is hashlib's over the file's bytes for any chunk size, so every stamp, weights digest and cache check
gives the same value it gave with its own copy."""
import hashlib

import pytest

from part2 import coco_set, hashing, stamp
from part2.backends import cpu_rtm

DATA = bytes(range(256)) * 5000 + b"tail"  # over one default chunk


@pytest.mark.parametrize("chunk", [1, 7, 4096, hashing.CHUNK])
def test_sha256_file_is_hashlib_over_the_bytes_for_any_chunk(tmp_path, chunk):
    path = tmp_path / "f.bin"
    path.write_bytes(DATA if chunk > 7 else DATA[:3000])
    want = hashlib.sha256(path.read_bytes()).hexdigest()
    assert hashing.sha256_file(path, chunk=chunk) == want
    assert hashing.sha256_file(str(path), chunk=chunk) == want


def test_an_empty_file_and_a_missing_one(tmp_path):
    (tmp_path / "empty").write_bytes(b"")
    assert hashing.sha256_file(tmp_path / "empty") == hashlib.sha256(b"").hexdigest()
    with pytest.raises(FileNotFoundError):
        hashing.sha256_file(tmp_path / "nothere")


def test_the_callers_share_it_and_keep_their_missing_file_rules(tmp_path):
    path = tmp_path / "w.onnx"
    path.write_bytes(DATA)
    want = hashlib.sha256(DATA).hexdigest()
    assert coco_set.sha256_file is hashing.sha256_file
    assert stamp.sha256_file(path) == want and stamp.sha256_file(tmp_path / "nothere") is None
    cpu_rtm._SHA_CACHE.clear()
    assert cpu_rtm._sha256(path) == want and cpu_rtm._sha256(tmp_path / "nothere") is None
    assert list(cpu_rtm._SHA_CACHE.values()) == [want]  # cached by path, size and mtime, as before
