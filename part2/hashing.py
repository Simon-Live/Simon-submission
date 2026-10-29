"""The sha256 of a file, shared by the stamp, the weights digests and the cache checks.

Spec: docs/specs/part2-images-to-3d.md (Files), docs/specs/check-2.md (Files). TICKET-030.

    digest = hashing.sha256_file(path)          # hex sha256 of the file's bytes; FileNotFoundError when it is missing

The file is read in chunks, so a multi-GB checkpoint never sits in memory; the digest does not depend on the chunk
size. Standard library only, so any module may import it.
"""
import hashlib

CHUNK = 1 << 20


def sha256_file(path, chunk: int = CHUNK) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()
