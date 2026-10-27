"""Turn one movement video into keyframes.json for every tracked person.

SAM 3.1 tracks up to 16 people. Muse Spark names the phases. Box motion fills
in the times when Spark's JSON cannot be used. A call that would cross the
next $5 spend mark is not sent.
"""

import json
import subprocess
from pathlib import Path

import numpy as np

from keyframe_finder.api import iter_sse, open_stream, post_json, upload_video
from keyframe_finder.detect import find_repetitions
from keyframe_finder.sam_parse import BoxParser
from keyframe_finder.schema import dump_json, frame_ms
from keyframe_finder.quality import QualityRefusal, assess, format_report
from keyframe_finder.signal import ffmpeg_exe, probe
from keyframe_finder.spend import estimate, price_usage, record, status, would_warn

ROOT = Path(__file__).resolve().parents[1]
SAM_MODEL = "sam-3.1"
SPARK_MODEL = "muse-spark-1.3"
TARGET_FPS = 5
MAX_SAM_FRAMES = 14000
ANALYSIS_WIDTH = 640


class SpendLimit(RuntimeError):
    def __init__(self, message, marks):
        super().__init__(message)
        self.marks = marks


def analysis_fps(duration_s):
    if duration_s <= 0:
        raise RuntimeError("video duration is 0")
    fps = TARGET_FPS
    if duration_s * fps > MAX_SAM_FRAMES:
        fps = MAX_SAM_FRAMES / duration_s
    return fps


def make_proxy(source, dest, fps, width=ANALYSIS_WIDTH, filters="", crf=None):
    dest.parent.mkdir(parents=True, exist_ok=True)
    if filters or width != ANALYSIS_WIDTH:
        vf = f"fps={fps},scale={width}:-2"
        if filters:
            vf = vf + "," + filters
    else:
        vf = f"scale={ANALYSIS_WIDTH}:-2,fps={fps}"
    cmd = [
        ffmpeg_exe(),
        "-y",
        "-loglevel",
        "error",
        "-i",
        str(source),
        "-an",
        "-vf",
        vf,
        "-c:v",
        "libx264",
    ]
    if crf is not None:
        cmd.extend(["-crf", str(crf)])
    cmd.extend(["-pix_fmt", "yuv420p", "-movflags", "+faststart", str(dest)])
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode() or f"could not prepare {source}")
    return probe(dest)


def sam_cost(frames):
    return estimate(SAM_MODEL, frame=max(int(frames), 50))


def spark_prompt(duration_s, fps, people):
    return (
        "This clip is a movement video. "
        f"It lasts {duration_s:.2f} seconds at {fps:.3f} frames per second. "
        f"A tracker found {people} people. "
        "Return JSON only, no markdown, with this shape: "
        '{"people":[{"id":1,"repetitions":[{"rep":1,"keyframes":[{"name":"start","t_ms":0}]}]}]}. '
        "Number people from the viewer's left to right, starting at 1. "
        "Include every person, up to 10. "
        "Split each person's motion into repetitions or sections. "
        "Keyframe names are snake_case phases of that movement, such as start, bottom, and top. "
        "t_ms is milliseconds from the start of the clip. "
        "Times must fall inside the clip and increase within a repetition."
    )


def count_spark_tokens(file_id, prompt):
    payload = {
        "model": SPARK_MODEL,
        "input": [
            {
                "type": "message",
                "role": "user",
                "content": [
                    {"type": "input_text", "text": prompt},
                    {"type": "input_file", "file_id": file_id},
                ],
            }
        ],
    }
    counted = post_json("/responses/input_tokens", payload, timeout=300)
    return int(counted["input_tokens"])


def spark_cost(input_tokens, output_tokens=4000):
    return price_usage(SPARK_MODEL, input_tokens=input_tokens, output_tokens=output_tokens)


def refuse_if_over(additional, note):
    marks = would_warn(additional)
    if not marks:
        return
    total = status()["usd"] + additional
    reached = ", ".join(f"${mark}" for mark in marks)
    raise SpendLimit(
        f"{note} is estimated at ${additional:.2f} and would bring this repo to "
        f"${total:.2f}, crossing {reached}. The call was not sent.",
        marks,
    )


def track_people(file_id):
    payload = {
        "model": SAM_MODEL,
        "stream": True,
        "metadata": {"mask_encoding": "one_bit"},
        "input": [
            {
                "type": "message",
                "role": "user",
                "content": [
                    {"type": "input_text", "text": "person"},
                    {"type": "input_video", "file_id": file_id},
                ],
            }
        ],
    }
    parser = BoxParser()
    seen = 0
    with open_stream(payload) as response:
        for event in iter_sse(response):
            kind = event.get("type", "")
            if kind == "response.output_text.delta":
                parser.feed(event.get("delta", ""))
                frames = max((box["frame"] for boxes in parser.tracks.values() for box in boxes), default=0)
                if frames // 200 > seen:
                    seen = frames // 200
                    print(f"  sam frame {frames}", flush=True)
            elif kind == "error":
                raise RuntimeError(event.get("message") or "SAM stream failed")
    return parser.tracks


def visible_runs(boxes, length):
    present = np.zeros(length, dtype=bool)
    cy = np.full(length, np.nan)
    cx = np.full(length, np.nan)
    for box in boxes:
        index = int(box["frame"])
        if index < 0 or index >= length:
            continue
        present[index] = True
        cy[index] = (box["y1"] + box["y2"]) / 2
        cx[index] = (box["x1"] + box["x2"]) / 2
    runs = []
    start = None
    gap = 0
    for index in range(length):
        if present[index]:
            if start is None:
                start = index
            gap = 0
            continue
        if start is None:
            continue
        gap += 1
        if gap > 2:
            stop = index - gap
            if stop >= start:
                runs.append((start, stop, cy[start : stop + 1].copy(), cx[start : stop + 1].copy()))
            start = None
            gap = 0
    if start is not None:
        stop = length - 1 - gap
        if stop >= start:
            runs.append((start, stop, cy[start : stop + 1].copy(), cx[start : stop + 1].copy()))
    return runs


def geometric_reps(boxes, length, fps):
    repetitions = []
    rep_number = 1
    centers = []
    for start, stop, cy, cx in visible_runs(boxes, length):
        finite = np.isfinite(cy)
        if finite.any():
            centers.append(float(np.nanmedian(cx)))
        if stop - start + 1 < max(3, int(fps)):
            continue
        filled = cy.copy()
        known = np.flatnonzero(np.isfinite(filled))
        if known.size == 0:
            continue
        filled = np.interp(np.arange(len(filled)), known, filled[known])
        found = find_repetitions(filled, fps, ["start", "bottom", "top"], "max_centroid_y")
        if not found:
            found = [
                {
                    "rep": 1,
                    "keyframes": [
                        {"name": "start", "frame": 0, "t_ms": frame_ms(0, fps)},
                        {"name": "end", "frame": len(filled) - 1, "t_ms": frame_ms(len(filled) - 1, fps)},
                    ],
                }
            ]
        for rep in found:
            shifted = []
            for keyframe in rep["keyframes"]:
                proxy_frame = start + int(keyframe["frame"])
                shifted.append(
                    {
                        "name": keyframe["name"],
                        "proxy_frame": proxy_frame,
                        "t_ms": frame_ms(proxy_frame, fps),
                    }
                )
            repetitions.append({"rep": rep_number, "keyframes": shifted})
            rep_number += 1
    order = float(np.median(centers)) if centers else 0.0
    return repetitions, order


def to_source_frames(repetitions, source_fps):
    converted = []
    for rep in repetitions:
        keyframes = []
        for keyframe in rep["keyframes"]:
            t_ms = int(keyframe["t_ms"])
            keyframes.append(
                {
                    "name": str(keyframe["name"]),
                    "frame": int(round(t_ms / 1000 * source_fps)),
                    "t_ms": t_ms,
                }
            )
        converted.append({"rep": rep["rep"], "keyframes": keyframes})
    return converted


def extract_json(text):
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("Spark did not return JSON")
    return json.loads(text[start : end + 1])


def output_text(body):
    parts = []
    for item in body.get("output", []):
        if item.get("type") != "message":
            continue
        for block in item.get("content", []):
            if block.get("type") == "output_text":
                parts.append(block.get("text") or "")
    return "\n".join(parts)


def ask_spark(file_id, prompt):
    payload = {
        "model": SPARK_MODEL,
        "max_output_tokens": 4000,
        "reasoning": {"effort": "low"},
        "input": [
            {
                "type": "message",
                "role": "user",
                "content": [
                    {"type": "input_text", "text": prompt},
                    {"type": "input_file", "file_id": file_id},
                ],
            }
        ],
    }
    body = post_json("/responses", payload, timeout=900)
    usage = body.get("usage") or {}
    details = usage.get("input_tokens_details") or {}
    cost = price_usage(
        SPARK_MODEL,
        input_tokens=usage.get("input_tokens") or 0,
        output_tokens=usage.get("output_tokens") or 0,
        cached_tokens=details.get("cached_tokens") or 0,
    )
    return extract_json(output_text(body)), cost


def spark_people(document, duration_ms):
    people = []
    for person in document.get("people", []):
        repetitions = []
        for rep in person.get("repetitions", []):
            keyframes = []
            for keyframe in rep.get("keyframes", []):
                t_ms = int(keyframe.get("t_ms", -1))
                name = str(keyframe.get("name", "")).strip()
                if not name or t_ms < 0 or t_ms > duration_ms:
                    continue
                keyframes.append({"name": name, "t_ms": t_ms})
            if keyframes:
                keyframes.sort(key=lambda item: item["t_ms"])
                repetitions.append({"rep": len(repetitions) + 1, "keyframes": keyframes})
        if repetitions:
            people.append(repetitions)
    return people


def quote_video(source, proxy_path, decision=None):
    _width, _height, source_fps = probe(source)
    duration = _duration_seconds(source)
    fps = analysis_fps(duration)
    width = ANALYSIS_WIDTH if decision is None else decision.width
    filters = "" if decision is None else decision.filtergraph
    crf = None if decision is None else decision.crf
    proxy_w, proxy_h, proxy_fps = make_proxy(source, proxy_path, fps, width, filters, crf)
    file_id = upload_video(proxy_path)
    prompt = spark_prompt(duration, proxy_fps, people=1)
    tokens = count_spark_tokens(file_id, prompt)
    frames = max(1, int(round(duration * proxy_fps)))
    costs = {
        "sam_usd": sam_cost(frames),
        "spark_usd": spark_cost(tokens),
        "frames": frames,
        "spark_input_tokens": tokens,
    }
    return {
        "source_fps": source_fps,
        "duration_s": duration,
        "proxy_fps": proxy_fps,
        "proxy_size": (proxy_w, proxy_h),
        "file_id": file_id,
        "costs": costs,
    }


def _duration_seconds(path):
    proc = subprocess.run(
        [ffmpeg_exe(), "-hide_banner", "-i", str(path)],
        capture_output=True,
        text=True,
    )
    import re

    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", proc.stderr)
    if not match:
        raise RuntimeError(f"could not read duration of {path}")
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def convert(source, dest):
    source = Path(source)
    dest = Path(dest)
    decision = assess(source)
    print(format_report(decision, source.name), flush=True)
    if decision.verdict == "refused":
        raise QualityRefusal(decision.message)
    proxy_path = ROOT / "out" / "proxy" / f"{source.stem}.mp4"
    quoted = quote_video(source, proxy_path, decision)
    costs = quoted["costs"]
    planned = costs["sam_usd"] + costs["spark_usd"]
    print(
        f"{source.name}: SAM ${costs['sam_usd']:.2f} for {costs['frames']} frames, "
        f"Spark about ${costs['spark_usd']:.2f} for {costs['spark_input_tokens']} input tokens",
        flush=True,
    )
    refuse_if_over(planned, source.name)
    frames = costs["frames"]
    billed = sam_cost(frames)
    tracks = track_people(quoted["file_id"])
    warnings = record(billed, f"{source.name} person tracking, {frames} frames", model=SAM_MODEL)
    _emit(warnings)
    people = []
    for sam_id, boxes in sorted(tracks.items()):
        repetitions, order = geometric_reps(boxes, frames, quoted["proxy_fps"])
        if not repetitions:
            continue
        people.append({"sam_id": sam_id, "order": order, "repetitions": repetitions})
    people.sort(key=lambda person: person["order"])
    method = "sam"
    prompt = spark_prompt(quoted["duration_s"], quoted["proxy_fps"], len(people))
    tokens = count_spark_tokens(quoted["file_id"], prompt)
    spark_estimate = spark_cost(tokens)
    try:
        refuse_if_over(spark_estimate, f"Spark on {source.name}")
    except SpendLimit as exc:
        print(f"WARNING: {exc}", flush=True)
        spark_estimate = None
    spark_warnings = []
    if spark_estimate is not None and people:
        try:
            document, actual = ask_spark(quoted["file_id"], prompt)
            if actual is not None:
                spark_warnings = record(actual, f"{source.name} phase names", model=SPARK_MODEL)
            named = spark_people(document, int(quoted["duration_s"] * 1000))
            if len(named) == len(people):
                for person, repetitions in zip(people, named):
                    person["repetitions"] = repetitions
                method = "sam+spark"
        except (RuntimeError, ValueError, json.JSONDecodeError) as exc:
            print(f"  spark fallback for {source.name}: {exc}", flush=True)
    _emit(spark_warnings)
    document = {
        "video": source.name,
        "fps": quoted["source_fps"],
        "method": method,
        "quality": decision.as_dict(),
        "people": [
            {
                "id": index,
                "repetitions": to_source_frames(person["repetitions"], quoted["source_fps"]),
            }
            for index, person in enumerate(people, start=1)
        ],
    }
    dump_json(dest, document)
    return document, warnings + spark_warnings


def _emit(warnings):
    for warning in warnings:
        print(f"WARNING: {warning}", flush=True)
