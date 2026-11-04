"""Trainer narration becomes timed cues (docs/specs/narration.md, TICKET-146).

The trainer talks while recording. `attach` takes the audio of the uploaded clip (the normalized clip has none:
`media.py` re-encodes with `-an`), has Muse Voice Transcribe 1.0 turn it into phrases with times, snaps each start
to the first voiced frame, attaches each phrase to the movement section that holds most of it and writes
`narration.json` next to the entry's files. Without audio, without speech or on any API failure there is no file
and one log line; a trainer job never fails because of narration.

Under BYOK-only (prod) the transcript comes from the trainer's own Modal account instead (`narration_own`, a11y B3),
and an entry left without `narration.json` has the sound removed from its public video (`narration_own.drop_audio`).
"""

from __future__ import annotations

import array
import json
import math
import os
from pathlib import Path
import shutil
import tempfile
import time
import wave
from typing import Any

from part7 import applog, ffsafe, media, narration_api, narration_own

FORMAT = "simon.narration.v1"
FILE_NAME = "narration.json"
CLIPS_DIR = "narration"  # <entry>/narration/cue-<index>.wav: the trainer's own words, cut from the upload (TICKET-270)
CLIP_TOLERANCE_MS = 50
CLIP_MAX_MS = 15000  # a longer phrase keeps its text and has no clip
MAX_CLIPS = 12
SAMPLE_RATE = 16000
FRAME_S = 0.01
SILENCE_DBFS = -50.0  # a track whose loudest frame is below this has no speech worth paying to transcribe
ONSET_DB = -30.0  # a phrase starts at its first frame within this many dB of its own loudest frame
BUDGET_S = 60.0  # all narration work for one trainer job; past it the rest is skipped, never waited for
MIN_SECTION_MS = 2000  # the same rules as web/practice.js deriveSections
SLICE_MS = 4000
MIN_SECTIONS, MAX_SECTIONS = 2, 8


# ----- sections (a port of web/practice.js deriveSections: both sides cut the same ranges) --------------------
def _mark_ms(mark: Any, fps: Any) -> float | None:
    if not isinstance(mark, dict):
        return None
    for key, scale in (("t_ms", 1.0), ("t", 1000.0)):
        if isinstance(mark.get(key), (int, float)) and not isinstance(mark.get(key), bool):
            return float(mark[key]) * scale
    frame = mark.get("frame")
    if isinstance(frame, (int, float)) and isinstance(fps, (int, float)) and fps > 0:
        return frame / fps * 1000.0
    return None


def rep_starts(doc: Any) -> list[int]:
    """Start (ms) of each repetition of the first person in a Part 1 keyframes file, sorted and unique."""
    people = doc.get("people") if isinstance(doc, dict) else None
    people = [p for p in people or [] if isinstance(p, dict)]
    person = next((p for p in people if p.get("id") == 0), people[0] if people else None)
    reps = [r for r in (person or {}).get("repetitions") or [] if isinstance(r, dict)]
    starts = []
    for rep in reps:
        times = [t for t in (_mark_ms(k, doc.get("fps")) for k in rep.get("keyframes") or []) if t is not None]
        if times:
            starts.append(round(min(times)))
    return sorted(set(starts))


def _equal_slices(duration_ms: int) -> list[list[int]]:
    n = min(MAX_SECTIONS, max(MIN_SECTIONS, round(duration_ms / SLICE_MS)))
    return [[round(duration_ms * i / n), round(duration_ms * (i + 1) / n)] for i in range(n)]


def _from_starts(starts: list[int], duration_ms: int) -> list[list[int]]:
    cuts = [0, *[s for s in starts if 0 < s < duration_ms], duration_ms]
    spans = [[a, b] for a, b in zip(cuts, cuts[1:])]

    def merge(i: int) -> None:
        spans[i:i + 2] = [[spans[i][0], spans[i + 1][1]]]

    i = 0
    while i < len(spans) and len(spans) > 1:
        if spans[i][1] - spans[i][0] >= MIN_SECTION_MS:
            i += 1
            continue
        merge(i - 1 if i == len(spans) - 1 else i)
        i = 0
    while len(spans) > MAX_SECTIONS:
        best = 0
        for j in range(1, len(spans) - 1):
            if spans[j + 1][1] - spans[j][0] < spans[best + 1][1] - spans[best][0]:
                best = j
        merge(best)
    return spans


def derive_sections(doc: Any, duration_ms: int) -> list[dict[str, int]]:
    """Sections `{start_ms, end_ms, index, count}`: one per group of repetitions, else equal slices of about 4 s."""
    if duration_ms < 2000:
        return []
    spans = _from_starts(rep_starts(doc), duration_ms)
    if len(spans) < MIN_SECTIONS:
        spans = _equal_slices(duration_ms)
    return [{"start_ms": a, "end_ms": b, "index": i + 1, "count": len(spans)} for i, (a, b) in enumerate(spans)]


def keyframe_marks(doc: Any) -> list[dict[str, Any]]:
    """`[{name, t}]` in time order from a keyframes file (`keyframes` list, else the repetitions' keyframes)."""
    fps = doc.get("fps") if isinstance(doc, dict) else None
    raw = list(doc.get("keyframes") or []) if isinstance(doc, dict) else []
    if not raw:
        for rep in (r for p in (doc.get("people") or [] if isinstance(doc, dict) else []) if isinstance(p, dict)
                    for r in p.get("repetitions") or []):
            raw += [k for k in (rep.get("keyframes") or []) if isinstance(k, dict)]
    out = []
    for k in raw:
        ms = _mark_ms(k, fps)
        if ms is not None and isinstance(k.get("name"), str):
            out.append({"name": k["name"], "t": round(ms / 1000.0, 3)})
    return sorted(out, key=lambda m: m["t"])


# ----- attaching phrases ---------------------------------------------------------------------------------------
def _overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def attach_cue(turn: dict[str, Any], sections: list[dict[str, int]], marks: list[dict[str, Any]], index: int) -> dict | None:
    """One cue for `turn`: the section holding most of it (earlier on a tie), the sections it also touches, and the
    last keyframe at or before its start. None when it lies outside every section."""
    start, end = turn["start_s"], turn["end_s"]
    spans = [(s, _overlap(start, end, s["start_ms"] / 1000.0, s["end_ms"] / 1000.0)) for s in sections]
    touched = [(s, o) for s, o in spans if o > 0]
    if not touched:
        return None
    home = max(touched, key=lambda p: (p[1], -p[0]["index"]))[0]
    before = [m for m in marks if m["t"] <= start]
    cue = {
        "index": index, "start_s": start, "end_s": end, "text": turn["text"], "section": dict(home),
        "also_sections": [s["index"] for s, _ in touched if s is not home],
        "keyframe": before[-1] if before else None,
    }
    for key in ("api_start_s", "api_end_s"):
        if key in turn:
            cue[key] = turn[key]
    return cue


def attach_all(turns: list[dict[str, Any]], sections: list[dict[str, int]], marks: list[dict[str, Any]]) -> list[dict]:
    cues = [attach_cue(t, sections, marks, i) for i, t in enumerate(turns)]
    return [c for c in cues if c is not None]


# ----- audio ---------------------------------------------------------------------------------------------------
def has_audio(src: Path | str, timeout: float = 60.0) -> bool:
    res = ffsafe.run(
        ["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of", "csv=p=0", str(src)],
        timeout=max(1.0, timeout), text=True,
    )
    return res.returncode == 0 and bool(res.stdout.strip())


def extract_audio(
    src: Path | str, dst: Path | str, start_ms: int = 0, end_ms: int | None = None, deadline: float | None = None,
) -> Path | None:
    """Mono 16 kHz WAV of `src` from `start_ms` to `end_ms`; None when the clip has no audio track."""
    left = (lambda: 180.0) if deadline is None else (lambda: deadline - time.monotonic())
    if not has_audio(src, min(60.0, left())):
        return None
    seek = ["-ss", f"{start_ms / 1000:.3f}"] if start_ms else []
    length = ["-t", f"{(end_ms - start_ms) / 1000:.3f}"] if end_ms is not None else []
    res = ffsafe.run(
        ["ffmpeg", "-y", "-loglevel", "error", *seek, "-i", str(src), *length, "-vn", "-ac", "1",
         "-ar", str(SAMPLE_RATE), "-c:a", "pcm_s16le", str(dst)],
        timeout=max(1.0, left()), text=True,
    )
    if res.returncode != 0 or not Path(dst).is_file():
        raise RuntimeError(f"ffmpeg audio extract failed: {res.stderr[-200:]}")
    return Path(dst)


def frame_levels(wav_path: Path | str) -> list[float]:
    """RMS (0 to 1 of full scale) of each 10 ms frame of a mono 16-bit WAV."""
    with wave.open(str(wav_path), "rb") as w:
        rate, data = w.getframerate(), w.readframes(w.getnframes())
    samples = array.array("h")
    samples.frombytes(data[: len(data) // 2 * 2])
    hop = max(1, int(rate * FRAME_S))
    return [
        math.sqrt(sum(s * s for s in samples[i:i + hop]) / len(samples[i:i + hop])) / 32768.0
        for i in range(0, len(samples) - hop + 1, hop)
    ]


def loudest_dbfs(levels: list[float]) -> float:
    return 20 * math.log10(max(levels)) if levels and max(levels) > 0 else -math.inf


def snap(turn: dict[str, Any], levels: list[float]) -> dict[str, Any]:
    """The turn with its start and end moved to the first and last voiced frame inside it (the API times stay in
    `api_start_s` and `api_end_s`); unchanged when the turn has no voiced frame."""
    a, b = int(turn["start_s"] / FRAME_S), int(math.ceil(turn["end_s"] / FRAME_S))
    window = levels[a:b]
    out = dict(turn, api_start_s=turn["start_s"], api_end_s=turn["end_s"])
    if not window or max(window) <= 0:
        return out
    thr = max(window) * 10 ** (ONSET_DB / 20)
    voiced = [i for i, v in enumerate(window) if v >= thr]
    out["start_s"] = round((a + voiced[0]) * FRAME_S, 3)
    out["end_s"] = round(max(out["start_s"] + FRAME_S, (a + voiced[-1] + 1) * FRAME_S), 3)
    return out


# ----- the trainer's own words as short wav files (TICKET-270) ------------------------------------------------
def clip_name(cue: dict[str, Any]) -> str:
    return f"cue-{int(cue['index'])}.wav"


def cut_clips(raw: Path | str, entry_dir: Path | str, doc: dict[str, Any], start_ms: int = 0,
              deadline: float | None = None) -> int:
    """Cut each cue's real audio (its snapped start to its end) from the upload into `<entry>/narration/cue-<n>.wav`
    and add `clip: {file, ms}` to the cue. A clip whose length is not the cue's within 50 ms is deleted, and a cue
    that is too long, past the end of the audio or unreadable keeps its text and has no clip. Returns the clip count;
    an upload with no audio track writes nothing."""
    folder = Path(entry_dir) / CLIPS_DIR
    shutil.rmtree(folder, ignore_errors=True)
    made = 0
    for cue in doc["cues"][:MAX_CLIPS]:
        first, last = start_ms + round(cue["start_s"] * 1000), start_ms + round(cue["end_s"] * 1000)
        if not 0 < last - first <= CLIP_MAX_MS:
            continue
        target = folder / clip_name(cue)
        try:
            folder.mkdir(exist_ok=True)
            if extract_audio(raw, target, first, last, deadline) is None:
                break
            got_ms = narration_api.wav_seconds(target) * 1000
        except Exception:  # one bad clip never costs the others, or the cues
            target.unlink(missing_ok=True)
            continue
        if abs(got_ms - (last - first)) > CLIP_TOLERANCE_MS:
            target.unlink(missing_ok=True)
            continue
        cue["clip"] = {"file": target.name, "ms": round(got_ms)}
        made += 1
    if not made:
        shutil.rmtree(folder, ignore_errors=True)
    return made


# ----- the entry point -----------------------------------------------------------------------------------------
def build(
    audio: Path | str, keyframes: Any, duration_ms: int, *, ledger: Path | str | None = None, call: str = "narration",
    keys_dir: Path | str | None = None, opener: Any = None, deadline: float | None = None,
) -> dict[str, Any] | None:
    """The narration document for a trainer WAV, or None when nobody spoke. Raises `NarrationError` on API failure."""
    levels = frame_levels(audio)
    if loudest_dbfs(levels) < SILENCE_DBFS:
        return None
    extra: dict[str, Any] = {"opener": opener} if opener is not None else {}
    if deadline is not None:
        left = deadline - time.monotonic()
        if left < 1.0:
            raise narration_api.NarrationError("the 60 s narration budget is used up")
        extra["timeout"] = left
    own = narration_own.wanted()
    if own:
        extra.setdefault("timeout", narration_own.BUDGET_S)
    transcribe = narration_own.transcribe if own else narration_api.transcribe
    result = transcribe(audio, ledger=ledger, call=call, keys_dir=keys_dir, **extra)
    sections = derive_sections(keyframes, duration_ms)
    cues = attach_all([snap(t, levels) for t in result["turns"]], sections, keyframe_marks(keyframes))
    if not cues:
        return None
    return {
        "format": FORMAT, "source": narration_own.source() if own else narration_api.MODEL, "duration_s": round(duration_ms / 1000.0, 3),
        "sections": sections, "cues": cues, "text": result["text"], "estimated_usd": result["estimated_usd"],
    }


def attach(raw: Path | str, entry_dir: Path | str, **kw: Any) -> Path | None:
    """`_attach`; under BYOK-only an entry left without cues loses the sound of its public video (a11y B3)."""
    found = _attach(raw, entry_dir, **kw)
    if found is None and narration_own.wanted():
        narration_own.drop_audio(entry_dir, kw.get("job"), kw.get("job_dir"))
    return found


def attach_then_show(raw: Path | str, entry_dir: Path | str, on_entry: Any, **kw: Any) -> Path | None:
    """`attach`, then the entry's held-back access row may be published (`on_entry.ready`, entry_access.Link): a trainer
    or group movement is shown to others only once it has captions or no sound (go-live R4, review S-B1, a11y B3)."""
    found = attach(raw, entry_dir, **kw)
    ready = getattr(on_entry, "ready", None)
    if ready is not None:
        ready()
    return found


def _attach(
    raw: Path | str,
    entry_dir: Path | str,
    *,
    video: Path | str,
    keyframes: Path | str | None = None,
    files: Any = None,
    trim: dict[str, int] | None = None,
    job: str | None = None,
    job_dir: Path | str | None = None,
    ledger: Path | str | None = None,
    keys_dir: Path | str | None = None,
    opener: Any = None,
) -> Path | None:
    """Write `<entry_dir>/narration.json` from the uploaded clip's own audio; None (and a log line) otherwise.

    `files` is the chain result's `files` value (any shape; `keyframes` is read from it inside the guard). The
    spend ledger is the one of the state directory the job lives in (`<state>/jobs/<id>/...`), else the default.
    The whole thing is held to BUDGET_S: past it the rest is skipped and the job goes on without cues.
    """
    entry = Path(entry_dir)
    target = entry / FILE_NAME

    def note(msg: str) -> None:
        applog.log(f"narration: {msg}", job, job_dir)

    if os.environ.get("SIMON7_NARRATION", "").lower() == "off":
        return None
    try:
        deadline = time.monotonic() + (narration_own.BUDGET_S if narration_own.wanted() else BUDGET_S)
        keyframes = keyframes or (files.get("keyframes") if isinstance(files, dict) else None)
        if ledger is None and job_dir is not None:
            root = applog.job_root(job_dir)
            if root.parent.name == "jobs":
                ledger = narration_api.ledger_path(root.parent.parent)
        duration_ms = int(media.probe(video)["duration_ms"])  # the entry clip's clock: cue times are on it
        start = int((trim or {}).get("start_ms", 0))
        end = start + duration_ms
        with tempfile.TemporaryDirectory(prefix="narration-") as tmp:
            audio = extract_audio(raw, Path(tmp) / "voice.wav", start, end, deadline)
            if audio is None:
                note("the clip has no audio track, no cues")
                return None
            try:
                doc = json.loads(Path(keyframes).read_text(encoding="utf-8")) if keyframes else {}
            except (OSError, ValueError):
                doc = {}
            built = build(audio, doc, duration_ms, ledger=ledger, call=f"narration:{entry.name}",
                          keys_dir=keys_dir, opener=opener, deadline=deadline)
            if built is not None:
                cut_clips(raw, entry, built, start, deadline)
        if built is None:
            shutil.rmtree(entry / CLIPS_DIR, ignore_errors=True)
            note("no speech found in the audio, no cues")
            return None
        target.write_text(json.dumps(built, indent=2) + "\n", encoding="utf-8")
        clips = sum(1 for c in built["cues"] if "clip" in c)
        note(f"{len(built['cues'])} cues in {len(built['sections'])} sections, {clips} clips, about ${built['estimated_usd']:.4f}")
        return target
    except Exception as exc:  # narration is optional: whatever fails, the trainer job goes on without it
        note(f"skipped, {applog.cause(exc)}")
        target.unlink(missing_ok=True)
        shutil.rmtree(entry / CLIPS_DIR, ignore_errors=True)
        return None
