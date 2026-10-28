"""Decide whether a video is clear enough to keyframe, and how to lift it.

The check is local. SAM and Spark never see a clip that fails it, and they
never see the original file: they see the analysis file this module describes.
"""

import math
import re
import subprocess

import numpy as np

from keyframe_finder.signal import ffmpeg_exe

# Below this short side a person has no pose left after the analysis scale.
MIN_SHORT_SIDE = 144
# Gym footage in the sample set sits near 157. The dance studio sits near 62.
FINE_BRIGHTNESS = 90
TARGET_BRIGHTNESS = 110
# YMAX - YMIN. Percentile spread misses a person who fills little of the frame.
MIN_SPREAD = 12
RECOVERABLE_SPREAD = 18
# blurdetect on a sharp 320px sample of these clips sits near 6. Heavy blur is ~23.
SOFT_BLUR = 9.0
UNUSABLE_BLUR = 20.0
# Identical frames land at 0. A real held pose still wobbles above this.
FROZEN_MOTION = 0.02
SAMPLE_FPS = 2
SAMPLE_WIDTH = 320

_FRAME = re.compile(r"frame:\d+\s+pts:\d+\s+pts_time:")
_KV = re.compile(
    r"lavfi\.(signalstats\.(?:YAVG|YMIN|YMAX|YDIF)|blur|scd\.score|freezedetect\.freeze_duration)"
    r"=(-?nan|[0-9.eE+-]+)"
)


class QualityRefusal(RuntimeError):
    """The picture cannot be keyframed. The API was not called."""


class Measurement:
    def __init__(
        self,
        width,
        height,
        frames,
        yavg,
        span,
        blur,
        ydif,
        yavg_std,
        black,
        noise,
        scene_cuts,
        flicker,
        freeze_s,
    ):
        self.width = width
        self.height = height
        self.frames = frames
        self.yavg = yavg
        self.span = span
        self.blur = blur
        self.ydif = ydif
        self.yavg_std = yavg_std
        self.black = black
        self.noise = noise
        self.scene_cuts = scene_cuts
        self.flicker = flicker
        self.freeze_s = freeze_s


class Decision:
    def __init__(self, verdict, measurement, filters, width, crf, message, preview=None):
        self.verdict = verdict
        self.measurement = measurement
        self.filters = filters
        self.width = width
        self.crf = crf
        self.message = message
        self.preview = preview

    @property
    def filtergraph(self):
        return ",".join(self.filters)

    def as_dict(self):
        measured = self.measurement
        return {
            "verdict": self.verdict,
            "brightness": round(measured.yavg, 1),
            "spread": round(measured.span, 1),
            "blur": None if measured.blur is None else round(measured.blur, 2),
            "motion": round(measured.ydif, 3),
            "near_black": round(measured.black, 3),
            "noise": round(measured.noise, 2),
            "flicker": round(measured.flicker, 2),
            "analysis_width": self.width,
            "filters": list(self.filters),
        }


def assess(path):
    """Measure path and, when a lift could help, preview that lift."""
    width, height = _picture_size(path)
    if min(width, height) < MIN_SHORT_SIDE:
        measurement = Measurement(
            width, height, 0, 0.0, 0.0, None, 0.0, 0.0, 1.0, 0.0, 0, 0.0, 0.0
        )
        return _refuse(
            measurement,
            f"Keyframing stopped. This video is {width}×{height}. "
            f"The short side is under {MIN_SHORT_SIDE} pixels, so a person has no pose left to find. "
            "No API call was made.",
        )
    measurement = measure(path)
    reason = _hard_reason(measurement)
    if reason:
        return _refuse(measurement, reason)
    filters, analysis_width, crf = _plan(measurement)
    if not filters:
        return Decision("fine", measurement, [], 640, None, "")
    preview = measure(path, extra=",".join(filters))
    if not _preview_ok(measurement, preview, filters):
        return _refuse(measurement, _preview_message(measurement, preview), preview)
    return Decision("enhanced", measurement, filters, analysis_width, crf, "", preview)


def measure(path, extra=""):
    width, height = _picture_size(path)
    sample_h = _sample_height(width, height)
    parts = [f"fps={SAMPLE_FPS}", f"scale={SAMPLE_WIDTH}:{sample_h}"]
    if extra:
        parts.append(extra)
    parts.extend(
        [
            "signalstats",
            "blurdetect",
            "scdet",
            "blackframe=amount=98:threshold=32",
            "freezedetect=noise=0.003:duration=2",
            "metadata=print",
        ]
    )
    proc = subprocess.run(
        [
            ffmpeg_exe(),
            "-hide_banner",
            "-loglevel",
            "info",
            "-i",
            str(path),
            "-an",
            "-vf",
            ",".join(parts),
            "-f",
            "rawvideo",
            "-pix_fmt",
            "gray",
            "pipe:1",
        ],
        capture_output=True,
    )
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", errors="replace")[-1500:]
        raise RuntimeError(f"could not measure video quality for {path}\n{detail}")
    stats = _parse_stats(proc.stderr.decode("utf-8", errors="replace"))
    gray = _frames(proc.stdout, sample_h)
    if gray is None or gray.shape[0] == 0 or not stats:
        raise RuntimeError(f"no frames could be read from {path}")
    yavg = _median(stats, "signalstats.YAVG")
    ymin = _median(stats, "signalstats.YMIN")
    ymax = _median(stats, "signalstats.YMAX")
    ydif_values = [
        item["signalstats.YDIF"]
        for item in stats
        if "signalstats.YDIF" in item
    ]
    # The first sample has no previous frame, so its difference is always 0.
    if len(ydif_values) > 1:
        ydif_values = ydif_values[1:]
    blur_values = [item["blur"] for item in stats if "blur" in item and np.isfinite(item["blur"])]
    yavg_values = [item["signalstats.YAVG"] for item in stats if "signalstats.YAVG" in item]
    cuts = sum(1 for item in stats if item.get("scd.score", 0.0) >= 10.0)
    freeze_s = sum(item.get("freezedetect.freeze_duration", 0.0) for item in stats)
    flicker = _flicker(stats)
    return Measurement(
        width=width,
        height=height,
        frames=int(gray.shape[0]),
        yavg=yavg,
        span=max(0.0, ymax - ymin),
        blur=float(np.median(blur_values)) if blur_values else None,
        ydif=float(np.median(ydif_values)) if ydif_values else 0.0,
        yavg_std=float(np.std(yavg_values)) if yavg_values else 0.0,
        black=_black_fraction(gray),
        noise=_flat_noise(gray),
        scene_cuts=cuts,
        flicker=flicker,
        freeze_s=freeze_s,
    )


def format_report(decision, name):
    measured = decision.measurement
    if measured.frames == 0 and decision.verdict == "refused":
        lines = [f"{name}: quality check", "  verdict: refused", decision.message]
        return "\n".join(lines)
    blur = "no edges" if measured.blur is None else f"{measured.blur:.1f}"
    lines = [
        f"{name}: quality check",
        (
            f"  brightness {measured.yavg:.0f}/255, spread {measured.span:.0f}, "
            f"blur {blur}, motion {measured.ydif:.2f}, "
            f"near-black {measured.black:.0%}, noise {measured.noise:.1f}, "
            f"flicker {measured.flicker:.1f}"
        ),
    ]
    if measured.scene_cuts:
        lines.append(f"  scene cuts: {measured.scene_cuts}")
    if decision.verdict == "fine":
        lines.append("  verdict: fine")
        lines.append("  analysis file: 640px wide, no enhancement")
    elif decision.verdict == "enhanced":
        lines.append("  verdict: enhanced")
        lines.append(
            f"  analysis file: {decision.width}px wide, filters {decision.filtergraph}"
        )
        if decision.preview is not None:
            lines.append(
                "  preview after lift: "
                f"brightness {decision.preview.yavg:.0f}/255, "
                f"spread {decision.preview.span:.0f}"
            )
    else:
        lines.append("  verdict: refused")
        lines.append(decision.message)
    return "\n".join(lines)


def _refuse(measurement, message, preview=None):
    return Decision("refused", measurement, [], 640, None, message, preview)


def _hard_reason(measurement):
    frozen = (
        measurement.frames >= 4
        and measurement.ydif < FROZEN_MOTION
        and measurement.yavg_std < 0.5
        and measurement.span >= MIN_SPREAD
    )
    if frozen:
        return (
            "Keyframing stopped. The picture does not change from frame to frame, "
            "so there is no movement to keyframe. "
            + (
                f"ffmpeg marked {measurement.freeze_s:.0f}s as frozen. "
                if measurement.freeze_s >= 1
                else ""
            )
            + "No API call was made."
        )
    if measurement.blur is not None and measurement.blur >= UNUSABLE_BLUR:
        return (
            "Keyframing stopped. The picture is too blurred to see a pose "
            f"(blur score {measurement.blur:.1f}; a sharp frame of these samples sits near 6). "
            "Sharpening cannot recover it. No API call was made."
        )
    if measurement.blur is None and measurement.span < MIN_SPREAD:
        return (
            "Keyframing stopped. No edges were found, and the bright-to-dark spread "
            f"is only {measurement.span:.0f}. There is no person to track. No API call was made."
        )
    if measurement.span < MIN_SPREAD:
        return (
            "Keyframing stopped. Median brightness is "
            f"{measurement.yavg:.0f}/255 and the bright-to-dark spread is only "
            f"{measurement.span:.0f}. There is no person-shaped contrast to lift. "
            "No API call was made."
        )
    return ""


def _plan(measurement):
    filters = []
    dark = measurement.yavg < FINE_BRIGHTNESS and measurement.span >= RECOVERABLE_SPREAD
    # Whole-clip brightness range is a scene change. Flicker is the fast residual.
    if measurement.flicker >= 8:
        filters.append("deflicker=size=5:mode=am")
    if dark or measurement.noise >= 10:
        spatial = 2.5 if measurement.noise >= 10 else 1.5
        temporal = 4 if measurement.noise >= 10 else 2
        filters.append(
            "hqdn3d="
            f"luma_spatial={spatial}:chroma_spatial={spatial}:luma_tmp={temporal}:chroma_tmp={temporal}"
        )
    if dark:
        gamma = _gamma(measurement.yavg)
        contrast = 1.0 if measurement.span >= 70 else min(1.35, 90.0 / max(measurement.span, 20))
        brightness = 0.04 if measurement.yavg < 45 else 0.0
        eq = [f"gamma={gamma:.2f}"]
        if contrast > 1.05:
            eq.append(f"contrast={contrast:.2f}")
        if brightness > 0:
            eq.append(f"brightness={brightness:.2f}")
        filters.append("eq=" + ":".join(eq))
    if measurement.blur is not None and SOFT_BLUR <= measurement.blur < UNUSABLE_BLUR:
        filters.append("cas=strength=0.4")
    if not filters:
        return [], 640, None
    width = 960 if dark else 640
    return filters, width, 18


def _flicker(stats):
    """Std of brightness after a short average, ignoring scene cuts."""
    series = []
    cuts = []
    for item in stats:
        if "signalstats.YAVG" not in item:
            continue
        series.append(item["signalstats.YAVG"])
        cuts.append(item.get("scd.score", 0.0) >= 10.0)
    series = np.asarray(series, dtype=np.float64)
    cuts = np.asarray(cuts, dtype=bool)
    if series.size < 8:
        return 0.0
    trend = np.convolve(series, np.ones(5) / 5.0, mode="valid")
    residual = series[2:-2] - trend
    near_cut = cuts[1:-3] | cuts[2:-2] | cuts[3:-1]
    keep = ~near_cut
    if int(keep.sum()) < 5:
        return 0.0
    return float(residual[keep].std())


def _gamma(yavg):
    source = min(max(yavg, 8.0), 250.0) / 255.0
    target = TARGET_BRIGHTNESS / 255.0
    if source >= target:
        return 1.0
    gamma = math.log(source) / math.log(target)
    return float(min(1.8, max(1.0, gamma)))


def _preview_ok(before, after, filters):
    lifted = any(item.startswith("eq=") for item in filters)
    if lifted:
        if after.span < RECOVERABLE_SPREAD:
            return False
        if after.yavg < 40 and after.yavg < before.yavg + 15:
            return False
    if after.blur is not None and after.blur >= UNUSABLE_BLUR:
        return False
    return True


def _preview_message(before, after):
    if after.blur is not None and after.blur >= UNUSABLE_BLUR:
        return (
            "Keyframing stopped. A preview lift left the picture too blurred to see a pose "
            f"(blur score {after.blur:.1f}). Sharpening cannot recover it. No API call was made."
        )
    return (
        "Keyframing stopped. Median brightness was "
        f"{before.yavg:.0f}/255 and the bright-to-dark spread was {before.span:.0f}. "
        f"A preview lift left brightness at {after.yavg:.0f}/255 with a spread of {after.span:.0f}, "
        "which is still too flat for SAM to see a person. No API call was made."
    )


def _picture_size(path):
    proc = subprocess.run(
        [ffmpeg_exe(), "-hide_banner", "-i", str(path)],
        capture_output=True,
        text=True,
    )
    match = re.search(r"(\d{2,5})x(\d{2,5})", proc.stderr or "")
    if not match:
        raise RuntimeError(f"could not read video size for {path}")
    return int(match.group(1)), int(match.group(2))


def _sample_height(width, height):
    scaled = int(round(height * SAMPLE_WIDTH / float(width)))
    scaled -= scaled % 2
    return max(2, scaled)


def _parse_stats(text):
    frames = []
    current = None
    for line in text.splitlines():
        if _FRAME.search(line):
            if current:
                frames.append(current)
            current = {}
            continue
        found = _KV.search(line)
        if found and current is not None:
            raw = found.group(2)
            current[found.group(1)] = float(raw)
    if current:
        frames.append(current)
    return frames


def _median(stats, key):
    values = [item[key] for item in stats if key in item and np.isfinite(item[key])]
    if not values:
        return 0.0
    return float(np.median(values))


def _frames(raw, height):
    frame_bytes = SAMPLE_WIDTH * height
    if frame_bytes <= 0:
        return None
    count = len(raw) // frame_bytes
    if count == 0:
        return None
    gray = np.frombuffer(raw, dtype=np.uint8, count=count * frame_bytes)
    return gray.reshape(count, height, SAMPLE_WIDTH)


def _black_fraction(gray):
    return float(np.mean(gray < 20, axis=(1, 2)).mean())


def _flat_noise(gray):
    frame = gray.astype(np.float32)
    left = frame[:, :, :-2]
    mid = frame[:, :, 1:-1]
    right = frame[:, :, 2:]
    span = np.maximum(np.maximum(left, mid), right) - np.minimum(np.minimum(left, mid), right)
    residual = mid - (left + mid + right) / 3.0
    flat = span <= 4
    if int(flat.sum()) < 500:
        return 0.0
    return float(residual[flat].std())
