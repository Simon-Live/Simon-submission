"""Fake Part 4 processors: test data for the processor seam, not a production path.

`process(recording, report)` reports three stages (`processing:keyframes`, `processing:skeleton`,
`processing:animation`), pauses `SIMON6_FAKE_STAGE_S` seconds at each (default 1.2) and returns
Part 4 v1 files: the `simon.keyframes.v1`, keyframe-only `simon.skeleton.v1` and
`simon.animation.v1` golden files of `fixtures/conformance/formats/`, declaring Part 4 as their
producer (`parts`, AC-C09). `fail` reports
`processing:pose` and fails the job. Both ignore the recording's content: nothing is computed.

Run with `python3 -m part6 serve --processor fixtures.processors.part4_fake:process` (or `:fail`).
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

FORMATS = Path(__file__).resolve().parents[1] / "conformance" / "formats"
STAGES = ("keyframes", "skeleton", "animation")
STAGE_ENV = "SIMON6_FAKE_STAGE_S"
DEFAULT_STAGE_S = 1.2
PART = 4    # the producer this fake declares for every file it returns
FAILURE = "failed:pose: no person found in the video"
# Which golden each stage's file comes from: (kind, format id, must be a key-poses-only file).
WANTED = {"keyframes": ("simon.keyframes.v1", False), "skeleton": ("simon.skeleton.v1", True),
          "animation": ("simon.animation.v1", False)}


def stage_seconds():
    """Seconds to pause at each stage, from SIMON6_FAKE_STAGE_S (0 or more)."""
    raw = os.environ.get(STAGE_ENV)
    if raw is None or raw.strip() == "":
        return DEFAULT_STAGE_S
    try:
        seconds = float(raw)
    except ValueError:
        raise ValueError(f"{STAGE_ENV} must be a number of seconds, got {raw!r}") from None
    if not seconds >= 0:
        raise ValueError(f"{STAGE_ENV} must be 0 or more, got {raw!r}")
    return seconds


def _is_wanted(case, kind):
    format_id, keys_only = WANTED[kind]
    expect = case.get("expect") or {}
    if case.get("kind") != kind or expect.get("format") != format_id:
        return False
    return not keys_only or (not expect.get("frame_count") and bool(expect.get("key_count")))


def golden(kind):
    """The parsed golden file for one kind, found through cases.json."""
    listing = json.loads((FORMATS / "cases.json").read_text(encoding="utf-8"))
    cases = listing["cases"] if isinstance(listing, dict) else listing
    for case in cases:
        if _is_wanted(case, kind):
            return json.loads((FORMATS / case["file"]).read_text(encoding="utf-8"))
    raise FileNotFoundError(f"no {WANTED[kind][0]} golden for {kind} in {FORMATS / 'cases.json'}")


def process(recording, report=None):
    files = {kind: golden(kind) for kind in STAGES}
    pause = stage_seconds()
    for stage in STAGES:
        if report:
            report(f"processing:{stage}")
        time.sleep(pause)
    return dict(files, parts={kind: PART for kind in STAGES})


def fail(recording, report=None):
    if report:
        report("processing:pose")
    return {"status": FAILURE}
