"""Turn any video dropped in inbox/ into out/<name>/keyframes.json.

A local quality check runs first. A clip that is too dark, flat, blurred, or
still is reported and not uploaded. A recoverable clip is lifted into the
analysis file. SAM 3.1 tracks every person on that file and returns a mask.
Muse Spark names the phases. Repetition times come from how each person's
silhouette changes, so a motion inside a still box still counts, and people in
the same frame can be on different phases. A call that would cross the next $5
mark is not sent.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

import numpy as np

from keyframe_finder.detect import find_repetitions
from keyframe_finder.mask_motion import (
    find_motion_bounds,
    frames_for_bounds,
    mask_distance,
)
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
# A short clip can be watched more often without a large SAM bill.
SHORT_CLIP_S = 20.0
SHORT_FPS = 15.0
# Ignore a figure that is only a sliver of the frame, or only on screen briefly.
MIN_AREA_RATIO = 0.02
MIN_AREA_OF_LARGEST = 0.25
MIN_TRACK_S = 1.0
# A person who leaves and comes back nearby is the same track.
STITCH_GAP_S = 0.75
STITCH_CENTER = 0.12
STITCH_SHAPE = 0.55


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
    target = SHORT_FPS if duration_s <= SHORT_CLIP_S else TARGET_FPS
    fps = min(target, MAX_FRAMES / duration_s)
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
            "source": "fallback",
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
                "source": "spark",
            }
        )
    sections.sort(key=lambda section: section["start_s"])
    if sections:
        return sections
    return fallback


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


def section_for(sections, time_s):
    """The named exercise that covers this moment. The nearest one if none do."""
    if not sections:
        return None
    for section in sections:
        if section["start_s"] <= time_s < section["end_s"]:
            return section
    return min(
        sections,
        key=lambda section: min(
            abs(time_s - section["start_s"]),
            abs(time_s - section["end_s"]),
        ),
    )


def repetitions_from_masks(grids, centers, fps, sections):
    """Find moves on the whole clip, then attach the name for that moment."""
    bounds = find_motion_bounds(grids, fps, centers)
    repetitions = []
    for start, middle, end in bounds:
        when = ((start + end) / 2.0) / float(fps)
        section = section_for(sections, when)
        names = section["phase_names"] if section else ["start", "bottom", "top"]
        movement = section["movement"] if section else "movement"
        try:
            used_names = names
            frames = frames_for_bounds(grids, fps, used_names, start, middle, end, centers)
        except ValueError:
            used_names = ["start", "bottom", "top"]
            frames = frames_for_bounds(grids, fps, used_names, start, middle, end, centers)
            movement = "movement"
        keyframes = [
            {"name": name, "frame": int(frame), "t_ms": frame_ms(frame, fps)}
            for name, frame in zip(used_names, frames)
        ]
        repetitions.append(
            {
                "rep": len(repetitions) + 1,
                "movement": movement,
                "keyframes": keyframes,
            }
        )
    return repetitions


def _sample_center(sample, width, height):
    frame_w = sample.get("frame_w") or width
    frame_h = sample.get("frame_h") or height
    if not frame_w or not frame_h:
        return None
    return (
        ((sample["x1"] + sample["x2"]) / 2.0) / float(frame_w),
        ((sample["y1"] + sample["y2"]) / 2.0) / float(frame_h),
    )


def _track_view(object_id, samples, n_frames, frame_area, width, height):
    kept = [sample for sample in samples if sample["c"] is None or sample["c"] >= 0.25]
    if len(kept) < 8:
        return None
    areas = [
        max(0.0, sample["x2"] - sample["x1"]) * max(0.0, sample["y2"] - sample["y1"]) / frame_area
        for sample in kept
    ]
    if not areas or float(np.median(areas)) < 0.01:
        return None
    frames = []
    for sample in kept:
        frame = int(sample["frame"])
        if 0 <= frame < n_frames:
            frames.append(frame)
    if not frames:
        return None
    return {
        "id": int(object_id),
        "samples": kept,
        "median_area": float(np.median(areas)),
        "first": min(frames),
        "last": max(frames),
        "width": width,
        "height": height,
        "n_frames": n_frames,
    }


def _end_center(view):
    ordered = sorted(view["samples"], key=lambda sample: int(sample["frame"]))
    for sample in reversed(ordered):
        center = _sample_center(sample, view["width"], view["height"])
        if center is not None:
            return center, sample.get("grid")
    return None, None


def _start_center(view):
    ordered = sorted(view["samples"], key=lambda sample: int(sample["frame"]))
    for sample in ordered:
        center = _sample_center(sample, view["width"], view["height"])
        if center is not None:
            return center, sample.get("grid")
    return None, None


def _same_person(host, guest, fps):
    if guest["first"] <= host["last"]:
        return False
    if guest["first"] - host["last"] > STITCH_GAP_S * float(fps):
        return False
    host_center, host_grid = _end_center(host)
    guest_center, guest_grid = _start_center(guest)
    if host_center is None or guest_center is None:
        return False
    dx = host_center[0] - guest_center[0]
    dy = host_center[1] - guest_center[1]
    if ((dx * dx) + (dy * dy)) ** 0.5 > STITCH_CENTER:
        return False
    if host_grid is not None and guest_grid is not None:
        if mask_distance(host_grid, guest_grid) > STITCH_SHAPE:
            return False
    return True


def stitch_tracks(views, fps):
    """Join a track that ends to one that begins nearby with a similar shape."""
    merged = []
    for view in sorted(views, key=lambda item: (item["first"], item["id"])):
        host = next((item for item in merged if _same_person(item, view, fps)), None)
        if host is None:
            merged.append(view)
            continue
        host["samples"].extend(view["samples"])
        host["last"] = max(host["last"], view["last"])
        host["median_area"] = max(host["median_area"], view["median_area"])
    return merged


def keep_exercisers(views, fps):
    """Drop a passerby and a figure much smaller than the person actually moving."""
    if not views:
        return []
    stayed = []
    for view in views:
        duration_s = (view["last"] - view["first"] + 1) / float(fps)
        share = duration_s / (view["n_frames"] / float(fps))
        if duration_s < MIN_TRACK_S and share < 0.15:
            continue
        stayed.append(view)
    if not stayed:
        return []
    largest = max(view["median_area"] for view in stayed)
    return [
        view
        for view in stayed
        if view["median_area"] >= MIN_AREA_RATIO
        and view["median_area"] >= MIN_AREA_OF_LARGEST * largest
    ]


def _series_for(view):
    n_frames = view["n_frames"]
    series = np.full(n_frames, np.nan)
    grids = [None] * n_frames
    centers = [None] * n_frames
    for sample in view["samples"]:
        frame = int(sample["frame"])
        if frame < 0 or frame >= n_frames:
            continue
        series[frame] = (sample["y1"] + sample["y2"]) / 2.0
        grid = sample.get("grid")
        if grid is not None:
            grids[frame] = grid
        centers[frame] = _sample_center(sample, view["width"], view["height"])
    return series, grids, centers


def people_from_tracks(tracks, n_frames, frame_area, fps, sections, width, height):
    views = []
    for object_id, samples in sorted(tracks.items()):
        view = _track_view(object_id, samples, n_frames, frame_area, width, height)
        if view is not None:
            views.append(view)
    views = keep_exercisers(stitch_tracks(views, fps), fps)
    people = []
    for view in sorted(views, key=lambda item: (item["first"], item["id"])):
        series, grids, centers = _series_for(view)
        if sum(grid is not None for grid in grids) >= 8:
            repetitions = repetitions_from_masks(grids, centers, fps, sections)
        else:
            repetitions = repetitions_for(series, fps, sections)
        repetitions = to_source_clock(repetitions, fps, fps)
        if not repetitions:
            continue
        people.append({"id": int(view["id"]), "repetitions": repetitions})
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


def save_silhouettes(dest, tracks, width, height):
    """Keep the decoded shapes and where they sat, so a later timing change is free."""
    arrays = {}
    for object_id, samples in tracks.items():
        frames = []
        packed = []
        centers_x = []
        centers_y = []
        for sample in samples:
            grid = sample.get("grid")
            if grid is None:
                continue
            center = _sample_center(sample, width, height)
            frames.append(int(sample["frame"]))
            packed.append(np.packbits(np.asarray(grid, dtype=np.uint8).reshape(-1)))
            centers_x.append(np.nan if center is None else center[0])
            centers_y.append(np.nan if center is None else center[1])
        if not frames:
            continue
        key = str(int(object_id))
        arrays[f"frames_{key}"] = np.asarray(frames, dtype=np.int32)
        arrays[f"grids_{key}"] = np.stack(packed)
        arrays[f"cx_{key}"] = np.asarray(centers_x, dtype=np.float32)
        arrays[f"cy_{key}"] = np.asarray(centers_y, dtype=np.float32)
    if not arrays:
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(dest, **arrays)


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
        save_silhouettes(ROOT / "out" / path.stem / "silhouettes.npz", tracks, made["width"], made["height"])
        try:
            text, spark_warnings = name_sections(file_id, made["duration_s"])
            warnings.extend(spark_warnings)
            (ROOT / "out" / path.stem).mkdir(parents=True, exist_ok=True)
            (ROOT / "out" / path.stem / "spark.txt").write_text(text, encoding="utf-8")
            sections = parse_sections(text, made["duration_s"])
            named = ", ".join(section["movement"] for section in sections[:6])
            print(f"  spark sections {len(sections)}: {named}", flush=True)
        except SpendWarning as exc:
            print(f"\nWARNING: {exc}\n", flush=True)
            sections = parse_sections("", made["duration_s"])
        people = people_from_tracks(
            tracks,
            frames,
            made["width"] * made["height"],
            made["fps"],
            sections,
            made["width"],
            made["height"],
        )
        people = source_clock(people, made["fps"], info["fps"])
    finally:
        delete_file(file_id)
    spark_names = "spark" if any(section.get("source") == "spark" for section in sections) else "fallback"
    document = {
        "video": display_path(path),
        "fps": info["fps"],
        "analysis_fps": made["fps"],
        "spark_names": spark_names,
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
