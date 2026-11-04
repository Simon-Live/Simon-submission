"""The follower video's light (docs/specs/video-light.md, TICKET-247): measured once per take, capped when dark.

Part 5 reads the skeleton, and a dark take still gives a clean skeleton, so nothing upstream sees the darkness.
Part 7 reads the pixels itself: ffmpeg `signalstats` YAVG (mean luma, 0 to 255) on `SAMPLE_FPS` frames per second.
`light = {median_y, dark_share, level}`; `level` is `ok`, `degraded` or `major`.
"""

from __future__ import annotations

import statistics
import subprocess
from pathlib import Path
from typing import Any

from part7 import ffsafe, quality_cap

SAMPLE_FPS = 3
TIMEOUT_S = 120
# Calibrated on the check-7 twins (spec video-light.md): clean pexels-8026937 median Y 167.2 (min 164.7),
# dark twin (eq=brightness=-0.35:gamma=0.6) median Y 43.7 (max 44.5). Both thresholds sit well inside the gap.
DARK_Y = 60.0          # a frame under this is dark
MAJOR_MEDIAN_Y = 60.0  # median under this: the take is too dark to judge
DEGRADED_MEDIAN_Y = 85.0
DEGRADED_DARK_SHARE = 0.25
CAP = 59  # the same cap Part 5's quality block gives (quality_constants.QUALITY_SCORE_CAP)
CAP_CODE = "light_dark"
MAJOR_LABEL = "The video was too dark to judge form reliably"
DEGRADED_NOTE = "The video was dim. Turn on a light in front of you, not behind you."
LEVELS = ("ok", "degraded", "major")
_RANK = {"ok": 0, "degraded": 1, "major": 2}


def classify(median_y: float, dark_share: float) -> str:
    if median_y < MAJOR_MEDIAN_Y:
        return "major"
    if median_y < DEGRADED_MEDIAN_Y or dark_share >= DEGRADED_DARK_SHARE:
        return "degraded"
    return "ok"


def summarise(values: list[float]) -> dict[str, Any] | None:
    """`light` from per-frame YAVG values; None when there is no frame."""
    if not values:
        return None
    median = statistics.median(values)
    share = sum(1 for v in values if v < DARK_Y) / len(values)
    return {"median_y": round(median, 1), "dark_share": round(share, 3), "level": classify(median, share)}


def measure(video: Path | str, *, ffmpeg: str = "ffmpeg") -> dict[str, Any] | None:
    """The light of `video`, or None when it cannot be read (the take is then not judged on light)."""
    graph = f"fps={SAMPLE_FPS},signalstats,metadata=print:key=lavfi.signalstats.YAVG:file=-"
    argv = [ffmpeg, "-v", "error", "-nostdin", "-threads", "1", "-i", str(video), "-an", "-vf", graph, "-f", "null", "-"]
    try:
        run = ffsafe.run(argv, timeout=TIMEOUT_S, text=True)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if run.returncode != 0:
        return None
    values = []
    for line in run.stdout.splitlines():
        if line.startswith("lavfi.signalstats.YAVG="):
            try:
                values.append(float(line.split("=", 1)[1]))
            except ValueError:
                continue
    return summarise(values)


def level_of(light: Any) -> str:
    level = light.get("level") if isinstance(light, dict) else None
    return level if level in LEVELS else "ok"


def worst(*levels: Any) -> str:
    """The worst of several readings: ok < degraded < major. An unknown level is left out."""
    best = max((_RANK.get(lv, 0) for lv in levels if isinstance(lv, str)), default=0)
    return {0: "ok", 1: "degraded", 2: "major"}[best]


def apply(summary: dict[str, Any], light: dict[str, Any] | None) -> dict[str, Any]:
    """`summary` (a job result's score fields) with `light`, the combined `video_level`, and the cap on a `major` light.

    Part 5's `quality.level == "ok"` means only that the skeleton looked fine; `video_level` is the worst of both.
    The `major` quality cap itself is part7/quality_cap.py, applied before this runs.
    """
    if light is None:
        return summary
    out = {**summary, "light": light}
    level = level_of(light)
    quality_level = quality_cap.level_of(summary.get("quality"))
    # Part 5's block absent: only the light was read, so a clean light is "not assessed" overall, never "ok"
    out["video_level"] = quality_cap.NOT_ASSESSED if level == "ok" and quality_level == quality_cap.NOT_ASSESSED \
        else worst(level, quality_level)
    if level == "major":
        out["light_note"] = MAJOR_LABEL
        score = summary.get("score")
        if isinstance(score, (int, float)) and not isinstance(score, bool):
            out["score"] = min(score, CAP)
            if score > CAP:
                out["grade"] = "F"
                out["capped_by"] = [CAP_CODE]
    elif level == "degraded":
        out["light_note"] = DEGRADED_NOTE
    return out
