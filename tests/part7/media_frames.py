"""Test helper: the coded video frames of a clip, for checks that a remux kept them (ffsafe.md APP-M2).

`media.normalize` remuxes an MP4 H.264 source with a stream copy that drops its metadata, so the file bytes differ from
the source while every coded frame stays the same. The tests compare these hashes instead of the file bytes.
"""

from __future__ import annotations

from pathlib import Path
import subprocess


def coded_frames(path: Path) -> list[str]:
    """The md5 of each coded video packet of `path`, in order (no decode: `-c copy` into the framemd5 muxer)."""
    res = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:v:0", "-c", "copy", "-f", "framemd5", "-"],
                         capture_output=True, text=True, check=True, timeout=60)
    return [line.rsplit(",", 1)[1].strip() for line in res.stdout.splitlines() if line and not line.startswith("#")]
