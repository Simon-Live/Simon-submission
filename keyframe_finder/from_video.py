"""Turn any video dropped in inbox/ into out/<name>/keyframes.json.

A local quality check runs first. A clip that is too dark, flat, blurred, or
still is reported and not uploaded. A recoverable clip is lifted into the
analysis file. SAM 3.1 tracks every person on that file. Muse Spark names the
phases. Repetition times come from each person's box, so people in the same
frame can be on different phases. A call that would cross the next $5 mark is
not sent.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

import numpy as np

from keyframe_finder.detect import find_repetitions
from keyframe_finder.meta_client import delete_file, name_sections, track_people, upload_video
from keyframe_finder.quality import assess, format_report
from keyframe_finder.schema import dump_json, frame_ms
from keyframe_finder.signal import ffmpeg_exe
from keyframe_finder.spend import SpendWarning, estimate, status

ROOT = Path(__file__).resolve().parents[1]
INBOX = ROOT / "inbox"
WORK = ROOT / "out" / "work"
MAX_FRAMES = 14000
TARGET_FPS = 8.0


def media_info(path):
    proc = subprocess.run(
        [ffmpeg_exe(), "-hide_banner", "-i", str(path)],
        capture_output=True,
        text=True,
    )
    text = proc.stderr or ""
    size = re.search(r"(\d{2,5})x(\d{2,5})", text)
    fps = re.search(r"(\d+(?:\.\d+)?)\s+fps", text) or re.search(
        r"(\d+(?:\.\d+)?)\s+tbr", text
    )
    duration = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", text)
    if not size or not fps or not duration:
        raise RuntimeError(f"could not read video metadata for {path}")
    hours, minutes, seconds = duration.groups()
    return {
        "width": int(size.group(1)),
        "height": int(size.group(2)),
        "fps": float(fps.group(1)),
        "duration_s": int(hours) * 3600 + int(minutes) * 60 + float(seconds),
    }


def analysis_fps(duration_s):
    if duration_s <= 0:
        raise RuntimeError("video duration is zero")
    fps = min(TARGET_FPS, MAX_FRAMES / duration_s)
    if fps < 1:
        raise RuntimeError(
            "This video is longer than SAM 3.1 can take in one request even at 1 fps. "
            "Split it into pieces under about 4 hours and drop those in inbox/."
        )
    return round(fps, 3)


def transcode(src, dest, fps, width=640, filters="", crf=None):
    """Write the analysis file. A fine clip keeps the plain 640px downsample."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if filters:
        # Temporal filters run at the analysis rate, which is what the models see.
        vf = f"fps={fps},scale={width}:-2,{filters}"
        rate = []
    else:
        vf = "scale=640:-2"
        rate = ["-r", str(fps)]
    cmd = [
        ffmpeg_exe(),
        "-y",
        "-loglevel",
        "error",
        "-i",
        str(src),
        "-an",
        "-vf",
        vf,
        *rate,
        "-c:v",
        "libx264",
    ]
    if crf is not None:
        cmd.extend(["-crf", str(crf)])
    cmd.extend(
        [
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(dest),
        ]
    )
    subprocess.run(cmd, check=True)


def display_path(path):
    path = Path(path)
    try:
        return path.absolute().relative_to(ROOT).as_posix()
    except ValueError:
        return path.name


def snake(name):
    cleaned = re.sub(r"[^a-z0-9]+", "_", str(name).strip().lower()).strip("_")
    return cleaned or "phase"


def parse_sections(text, duration_s):
    fallback = [
        {
            "movement": "movement",
            "start_s": 0.0,
            "end_s": duration_s,
            "phase_names": ["start", "bottom", "top"],
        }
    ]
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return fallback
    try:
        payload = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return fallback
    sections = []
    for raw in payload.get("sections") or []:
        names = [snake(name) for name in (raw.get("phase_names") or raw.get("phases") or [])]
        if len(names) not in (3, 5):
            names = ["start", "bottom", "top"]
        start_s = max(0.0, float(raw.get("start_s", 0)))
        end_s = min(duration_s, float(raw.get("end_s", duration_s)))
        if end_s - start_s < 0.5:
            continue
        sections.append(
            {
                "movement": snake(raw.get("movement") or "movement"),
                "start_s": start_s,
                "end_s": end_s,
                "phase_names": names,
            }
        )
    sections.sort(key=lambda section: section["start_s"])
    return sections or fallback


def _fill(series):
    index = np.arange(len(series))
    good = ~np.isnan(series)
    if int(good.sum()) < 4:
        return None
    return np.interp(index, index[good], series[good])


def _extremum(series):
    valid = series[~np.isnan(series)]
    if valid.size == 0:
        return "max_centroid_y"
    middle = float(np.median(valid))
    downward = float(np.percentile(valid, 95) - middle)
    upward = float(middle - np.percentile(valid, 5))
    return "max_centroid_y" if downward >= upward else "min_centroid_y"


def _fallback_rep(series, fps, names, extremum):
    filled = _fill(series)
    if filled is None:
        return []
    bottom = int(np.argmax(filled) if extremum == "max_centroid_y" else np.argmin(filled))
    start, end = 0, len(filled) - 1
    if end - start < max(2, int(0.4 * fps)):
        return []
    if len(names) == 5:
        frames = [start, (start + bottom) // 2, bottom, (bottom + end) // 2, end]
    else:
        frames = [start, bottom, end]
    return [
        {
            "rep": 1,
            "keyframes": [
                {"name": name, "frame": int(frame), "t_ms": frame_ms(frame, fps)}
                for name, frame in zip(names, frames)
            ],
        }
    ]


def repetitions_for(series, fps, sections):
    repetitions = []
    for section in sections:
        start = int(round(section["start_s"] * fps))
        stop = max(start + 1, int(round(section["end_s"] * fps)))
        piece = series[start:stop]
        filled = _fill(piece)
        if filled is None:
            continue
        extremum = _extremum(piece)
        try:
            found = find_repetitions(filled, fps, section["phase_names"], extremum)
        except ValueError:
            found = []
        if not found:
            found = _fallback_rep(piece, fps, section["phase_names"], extremum)
        for rep in found:
            for keyframe in rep["keyframes"]:
                absolute = start + int(keyframe["frame"])
                keyframe["frame"] = absolute
                keyframe["t_ms"] = frame_ms(absolute, fps)
            repetitions.append(
                {
                    "rep": len(repetitions) + 1,
                    "movement": section["movement"],
                    "keyframes": rep["keyframes"],
                }
            )
    return repetitions


def to_source_clock(repetitions, analysis_fps, source_fps):
    converted = []
    for rep in repetitions:
        keyframes = []
        for keyframe in rep["keyframes"]:
            t_ms = frame_ms(keyframe["frame"], analysis_fps)
            keyframes.append(
                {
                    "name": keyframe["name"],
                    "frame": int(round(t_ms / 1000.0 * source_fps)),
                    "t_ms": t_ms,
                }
            )
        converted.append(
            {"rep": rep["rep"], "movement": rep["movement"], "keyframes": keyframes}
        )
    return converted


def people_from_tracks(tracks, n_frames, frame_area, fps, sections):
    people = []
    for object_id, samples in sorted(tracks.items()):
        kept = [sample for sample in samples if sample["c"] is None or sample["c"] >= 0.25]
        if len(kept) < 8:
            continue
        areas = [
            max(0.0, sample["x2"] - sample["x1"]) * max(0.0, sample["y2"] - sample["y1"]) / frame_area
            for sample in kept
        ]
        if not areas or float(np.median(areas)) < 0.01:
            continue
        series = np.full(n_frames, np.nan)
        for sample in kept:
            frame = int(sample["frame"])
            if 0 <= frame < n_frames:
                series[frame] = (sample["y1"] + sample["y2"]) / 2.0
        repetitions = to_source_clock(repetitions_for(series, fps, sections), fps, fps)
        people.append({"id": int(object_id), "repetitions": repetitions})
    return people


def source_clock(people, analysis_fps, source_fps):
    """Rewrite frame indexes from the analysis clip onto the original video."""
    timed = []
    for person in people:
        repetitions = []
        for rep in person["repetitions"]:
            keyframes = []
            for keyframe in rep["keyframes"]:
                t_ms = int(keyframe["t_ms"])
                keyframes.append(
                    {
                        "name": keyframe["name"],
                        "frame": int(round(t_ms / 1000.0 * source_fps)),
                        "t_ms": t_ms,
                    }
                )
            repetitions.append(
                {"rep": rep["rep"], "movement": rep["movement"], "keyframes": keyframes}
            )
        timed.append({"id": person["id"], "repetitions": repetitions})
    return timed


def process(path):
    path = Path(path)
    decision = assess(path)
    print(format_report(decision, path.name), flush=True)
    if decision.verdict == "refused":
        dest = ROOT / "out" / path.stem / "keyframes.json"
        if dest.exists():
            print(f"  The existing {dest.relative_to(ROOT)} was left as it is.", flush=True)
        return None
    info = media_info(path)
    fps = analysis_fps(info["duration_s"])
    frames = max(1, int(round(info["duration_s"] * fps)))
    sam_cost = estimate("sam-3.1", frame=max(50, frames))
    print(
        f"{path.name}: {info['duration_s']:.1f}s at {info['fps']} fps, "
        f"analysis {fps} fps, {frames} frames, SAM about ${sam_cost:.2f}",
        flush=True,
    )
    work = WORK / f"{path.stem}.mp4"
    print("  transcoding", flush=True)
    transcode(
        path,
        work,
        fps,
        width=decision.width,
        filters=decision.filtergraph,
        crf=decision.crf,
    )
    made = media_info(work)
    frames = max(1, int(round(made["duration_s"] * made["fps"])))
    print("  uploading", flush=True)
    file_id = upload_video(work)
    warnings = []
    try:
        tracks, sam_warnings = track_people(file_id, frames)
        warnings.extend(sam_warnings)
        try:
            text, spark_warnings = name_sections(file_id, made["duration_s"])
            warnings.extend(spark_warnings)
            sections = parse_sections(text, made["duration_s"])
        except SpendWarning as exc:
            print(f"\nWARNING: {exc}\n", flush=True)
            sections = parse_sections("", made["duration_s"])
        people = people_from_tracks(
            tracks, frames, made["width"] * made["height"], made["fps"], sections
        )
        people = source_clock(people, made["fps"], info["fps"])
    finally:
        delete_file(file_id)
    document = {
        "video": display_path(path),
        "fps": info["fps"],
        "analysis_fps": made["fps"],
        "quality": decision.as_dict(),
        "people": people,
    }
    dest = ROOT / "out" / path.stem / "keyframes.json"
    dump_json(dest, document)
    print(
        f"  wrote {dest.relative_to(ROOT)} "
        f"({len(people)} people, "
        f"{sum(len(person['repetitions']) for person in people)} repetitions)",
        flush=True,
    )
    for warning in warnings:
        print(f"\nWARNING: {warning}\n", flush=True)
    return dest


def inbox_videos():
    videos = sorted(INBOX.glob("*.mp4"), key=lambda path: path.stat().st_size)
    return videos


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    videos = [Path(arg) for arg in args] or inbox_videos()
    if not videos:
        print("Drop an mp4 into inbox/, then run make keyframes.", flush=True)
        return 1
    videos.sort(key=lambda path: media_info(path)["duration_s"])
    refused = 0
    for video in videos:
        try:
            if process(video) is None:
                refused += 1
        except SpendWarning as exc:
            print(f"\nWARNING: {exc}\n", flush=True)
            print("No further videos were sent.", flush=True)
            print(json.dumps(status(), indent=2), flush=True)
            return 2
    print(json.dumps(status(), indent=2), flush=True)
    if refused:
        print(f"{refused} video(s) were not keyframed because the picture was not usable.", flush=True)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
