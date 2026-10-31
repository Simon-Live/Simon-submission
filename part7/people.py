"""The people job: who is in the clip (people.md "Part 7 server", TICKET-057, TICKET-058).

Normalize and trim the upload, find everyone with Part 2 (`track`, else a full `multi` run), and write
the crops, `frame.jpg` with the numbered boxes and the people list with `auto_id`. Later jobs name this job
(`PersonSel.people_work`) to reuse its trimmed clip and tracks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import logging
from pathlib import Path
import shutil
import subprocess
from typing import Any

from part7 import applog, config, crop, media, modules, runner, stagelog
from part7.jobs import JobContext, JobFailed, JobFn
from part7.parts import p2_pose

AUTO_COVERAGE = 0.6  # exactly one person at or above this is chosen without asking
MIN_COVERAGE = 0.1  # tracks seen in less of the clip are tracker noise and are not offered
MAX_PEOPLE = 12
GROUP_MAX_SECONDS = 30  # people.md "Limits"
GROUP_MAX_FOLLOWERS = 8
CROP_HEIGHT = 240
FRAME_WIDTH = 1280
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
NO_ONE = "No one was found in this clip. Record again with the person in frame."
REASON_UNREADABLE = "the video could not be read"
NOTE_NO_TRACK = "Part 2 at this pin has no track command, a full multi-person run found the people"
NOTE_NO_IDS = "Part 2 at this pin cannot limit 3D to chosen people, 3D ran for everyone and Part 3 --person chose"
OPEN_TRACKERS = ("open", "bytetrack")


@dataclass
class PersonSel:
    """Which person a chain run is about, and where the people job's media and tracks live."""

    id: str
    people_work: Path | None = None  # work folder of the people job: clip.mp4, tracks.json, pose3d_all.json
    pose3d: Path | None = None  # 3D already computed for the chosen people (group job)
    ids: list[str] = field(default_factory=list)  # people that need 3D; empty means just `id`


# ----- the clip ---------------------------------------------------------------------------------
def prepare_clip(ctx: JobContext, raw: Path, trim: dict[str, int] | None, name: str = "clip.mp4") -> Path:
    """Normalize `raw` to H.264 MP4 and cut it to `trim`; the result is `<work>/<name>`.

    The one clip path of every job (people.md "One clip path"): the people job writes `clip.mp4`, which trainer,
    follow and group jobs copy in (`reused_clip`); a trainer or follow job without a people job writes
    `video.mp4` here itself.
    """
    ctx.set_stage("upload")
    clip = ctx.work / name
    cap = config.clip_max_side()  # TICKET-067: Part 2 `track` time grows with the pixel count
    try:
        src = media.probe(raw)
        cut = f"trim {trim['start_ms']}-{trim['end_ms']} ms" if trim else "no trim"
        size = scale_decision(src, cap, cut=bool(trim))
        applog.log(f"clip in: {stagelog.video_facts(raw)} {src['codec']}, {cut}, {size}", ctx.id, ctx.dir)
        if trim:
            whole = media.normalize(raw, ctx.work / "normalized.mp4")
            media.trim(whole, clip, trim["start_ms"], trim["end_ms"], max_side=cap)
            whole.unlink(missing_ok=True)
        else:
            media.normalize(raw, clip, max_side=cap)
        duration_ms = media.probe(clip)["duration_ms"]
        applog.log(f"clip out: {stagelog.video_facts(clip)}, from {src['width']}x{src['height']}", ctx.id, ctx.dir)
    except (ValueError, RuntimeError, OSError) as exc:
        applog.log(f"clip could not be prepared: {applog.cause(exc)}", ctx.id, ctx.dir, logging.WARNING)
        raise JobFailed("upload", REASON_UNREADABLE) from None
    ctx._queue.update(ctx.id, trim=trim, duration_ms=duration_ms)
    return clip


def scale_decision(meta: dict[str, Any], cap: int, *, cut: bool) -> str:
    """The clip-in log text of the size rule (`media.clip_size`), from the displayed size of the probed source.

    `scale to <w>x<h> (<rule>)` when the clip changes size, else `size kept (<rule>)`; a rotated or non-square
    pixel source is judged by the size a player shows, so the line names the size `clip out` reports.
    """
    if cap <= 0:
        rule = f"long side cap off, trim keeps {media.MAX_CLIP_HEIGHT} px tall at most" if cut else "long side cap off"
    else:
        rule = f"long side cap {cap} px, {media.MAX_CLIP_HEIGHT} px tall at most"
    shown = media.display_size(meta) if cap > 0 else media.upright_size(meta)  # the legacy rule keeps the pixel shape
    out = media.clip_size(meta, cap, cut=cut) or shown
    return f"size kept ({rule})" if out == shown else f"scale to {out[0]}x{out[1]} ({rule})"


def reused_clip(ctx: JobContext, sel: PersonSel) -> Path:
    """Copy the people job's trimmed clip in as this job's `video.mp4`."""
    ctx.set_stage("upload")
    src = (sel.people_work or ctx.work) / "clip.mp4"
    dst = ctx.work / "video.mp4"
    try:
        shutil.copyfile(src, dst)
    except OSError:
        applog.log(f"people job clip {src} is gone", ctx.id, ctx.dir, logging.WARNING)
        raise JobFailed("upload", "the chosen clip is no longer available, choose the person again") from None
    applog.log(f"clip reused from people job {applog.job_id_of(src)}: {stagelog.video_facts(dst)}, person {sel.id}"
               + (f", ids {','.join(sel.ids)}" if sel.ids else ""), ctx.id, ctx.dir)
    return dst


# ----- reading tracks ---------------------------------------------------------------------------
def frame_times(root: Path) -> dict[int, float]:
    """`frame -> seconds` from the `frames.json` Part 2 wrote under `root`; empty when there is none."""
    for path in sorted(root.glob("**/frames.json")):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
            return {int(f["frame"]): float(f["t_ms"]) / 1000.0 for f in doc["frames"]}
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return {}


def _scaled(box: list[float], kx: float, ky: float) -> list[int]:
    return [round(box[0] * kx), round(box[1] * ky), round(box[2] * kx), round(box[3] * ky)]


def summarize(frames: list[dict[str, Any]], width: int, height: int) -> list[dict[str, Any]]:
    """The offered people, by coverage descending: `{id, coverage, frames, box_mid, best_frame}`.

    `box_mid` is the box nearest the middle of the clip, `best_frame` the frame of the largest, surest box;
    both in video pixels.
    """
    ids = sorted({str(p.get("id")) for f in frames for p in f["people"] if isinstance(p, dict)})
    sw, sh = crop.track_size(frames) or (width, height)
    kx, ky = width / sw, height / sh
    middle = (frames[len(frames) // 2].get("frame", 0)) if frames else 0
    people: list[dict[str, Any]] = []
    for pid in ids:
        boxes = crop.boxes_of(frames, pid)
        coverage = len({n for n, _, _ in boxes}) / len(frames)
        if coverage < MIN_COVERAGE:
            continue
        mid = min(boxes, key=lambda item: abs(item[0] - middle))
        best = max(boxes, key=lambda item: item[1][2] * item[1][3] * (item[2] or 0.5))
        people.append(
            {"id": pid, "coverage": round(coverage, 3), "frames": len({n for n, _, _ in boxes}),
             "box_mid": _scaled(mid[1], kx, ky), "best_frame": best[0], "best_box": _scaled(best[1], kx, ky)}
        )
    people.sort(key=lambda p: -p["coverage"])
    return people[:MAX_PEOPLE]


def auto_id(people: list[dict[str, Any]]) -> str | None:
    """The only person with coverage of at least `AUTO_COVERAGE`, else None."""
    sure = [p for p in people if p["coverage"] >= AUTO_COVERAGE]
    return sure[0]["id"] if len(sure) == 1 else None


# ----- images -----------------------------------------------------------------------------------
def _ffmpeg_still(clip: Path, t: float, vf: str, dst: Path) -> bool:
    res = subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{max(t, 0.0):.3f}", "-i", str(clip), "-frames:v", "1",
         "-vf", vf, "-q:v", "3", str(dst)],
        capture_output=True, text=True, timeout=60, check=False,
    )
    return res.returncode == 0 and dst.is_file()


def person_crop(clip: Path, t: float, box: list[int], dst: Path, width: int, height: int) -> bool:
    """A JPEG of `box` (padded 5%) at time `t`, `CROP_HEIGHT` px tall."""
    x, y, w, h = box
    px, py = int(w * 0.05), int(h * 0.05)
    x0, y0 = max(0, x - px), max(0, y - py)
    cw, ch = max(2, min(width - x0, w + 2 * px)), max(2, min(height - y0, h + 2 * py))
    return _ffmpeg_still(clip, t, f"crop={cw}:{ch}:{x0}:{y0},scale=-2:{CROP_HEIGHT}", dst)


def middle_frame(clip: Path, t: float, people: list[dict[str, Any]], dst: Path) -> bool:
    """The clip's middle frame with a numbered box per person; boxes only when text cannot be drawn."""
    boxes = ",".join(
        f"drawbox=x={b[0]}:y={b[1]}:w={b[2]}:h={b[3]}:color=yellow@0.9:t=4"
        for b in (p["box_mid"] for p in people)
    )
    labels = ",".join(
        f"drawtext=fontfile={FONT}:text={p['id']}:x={p['box_mid'][0] + 8}:y={p['box_mid'][1] + 6}"
        ":fontsize=h/14:fontcolor=black:box=1:boxcolor=yellow@0.9:boxborderw=6"
        for p in people
    )
    scale = f"scale='min({FRAME_WIDTH},iw)':-2"
    for chain_ in (f"{boxes},{labels},{scale}", f"{boxes},{scale}") if people else (scale,):
        if _ffmpeg_still(clip, t, chain_, dst):
            return True
    return False


# ----- Part 2 -----------------------------------------------------------------------------------
def _find_people(
    ctx: JobContext, clip: Path, backend: str, lock: modules.Modules | None, state: Path | str | None,
    steps: list[runner.Step],
) -> Path:
    """Run Part 2 until `tracks.json` exists; return its path in the job's work folder.

    The Part 2 steps are added to `steps`, so the stage line names their exits (`2:<exit>`, TICKET-067): a
    failed named tracker attempt and the fallback that followed it are both listed.
    """
    ctx.set_stage("track")
    lk = lock or modules.load()
    try:
        if p2_pose.capabilities(lk, state)["track"]:
            step, found = p2_pose.track(clip, ctx.work, backend=backend, lock=lk, state=state)
            if step.get("first_try"):
                steps.append(step["first_try"])  # the failed tracker attempt; its exit shows in the stage line
        else:
            ctx.add_note(NOTE_NO_TRACK)
            step, pose = p2_pose.run(clip, ctx.work, backend=backend, lock=lk, state=state, multi=True)
            found = pose.with_name("tracks.json")
            if pose.is_file():
                shutil.copyfile(pose, ctx.work / "pose3d_all.json")  # a later job reuses it (see `pose_for`)
    except TimeoutError:
        raise JobFailed("track", "the GPU is busy, try again later") from None
    except RuntimeError:
        raise JobFailed("track", "the people finder is not available") from None
    steps.append(step)
    if step["exit"] != 0 or not found.is_file():
        raise JobFailed("track", "the people finder timed out" if step.get("timed_out") else "the people finder failed")
    tracks = ctx.work / "tracks.json"
    shutil.copyfile(found, tracks)
    return tracks


def _note_tracker(ctx: JobContext, tracks: Path) -> None:
    try:
        name = str((json.loads(tracks.read_text(encoding="utf-8")).get("provenance") or {}).get("tracker") or "")
    except (OSError, ValueError, AttributeError):
        return
    if any(word in name for word in OPEN_TRACKERS):
        ctx.add_note(f"people were found with the fallback tracker {name}")


def pose_for(
    sel: PersonSel, ids: list[str], video: Path, work: Path, backend: str, lk: modules.Modules, state: Path | str | None
) -> tuple[runner.Step, Path, str | None]:
    """3D for `ids` of the people job: Part 2 `--tracks --ids` when the pin has it, else everyone.

    Returns `(step, pose3d.json, note)`; a note names the fallback (people.md "Part 2 follow-up").
    """
    tracks = (sel.people_work or work) / "tracks.json"
    if tracks.is_file() and p2_pose.capabilities(lk, state)["ids"]:
        step, pose = p2_pose.run(video, work, backend=backend, lock=lk, state=state, tracks=tracks, ids=ids)
        return (step, pose, None)
    stored = (sel.people_work or work) / "pose3d_all.json"
    if stored.is_file():
        pose = work / "part2" / "pose3d.json"
        pose.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(stored, pose)
        step = runner.Step(
            part=2, commit=lk.sha12(2), argv=["reuse", "pose3d_all.json"], cwd=str(work), exit=0, timed_out=False,
            duration_s=0.0, log="", stdout="",
        )
        return (step, pose, NOTE_NO_IDS)
    step, pose = p2_pose.run(video, work, backend=backend, lock=lk, state=state, multi=True)
    return (step, pose, NOTE_NO_IDS)


# ----- the job ----------------------------------------------------------------------------------
def people_job(
    raw: Path,
    *,
    trim: dict[str, int] | None = None,
    lock: modules.Modules | None = None,
    state: Path | str | None = None,
    backend: str = "gpu",
) -> JobFn:
    """Return the job function of `POST api/people`."""

    def run(ctx: JobContext) -> dict[str, Any]:
        clip = prepare_clip(ctx, raw, trim)
        meta = media.probe(clip)
        steps: list[runner.Step] = []
        with stagelog.stage(ctx.work, "track", steps, video=stagelog.video_facts(clip), backend=backend):
            tracks = _find_people(ctx, clip, backend, lock, state, steps)
        _note_tracker(ctx, tracks)
        ctx.set_stage("people")
        try:
            frames = crop.load_tracks(tracks)
        except ValueError:
            raise JobFailed("track", "the people finder wrote no result") from None
        people = summarize(frames, meta["width"], meta["height"]) if frames else []
        if not people:
            raise JobFailed("track", NO_ONE)
        out = ctx.dir / "people"
        out.mkdir(parents=True, exist_ok=True)
        times = frame_times(ctx.work)
        for person in people:
            t = times.get(person["best_frame"], person["best_frame"] / p2_pose.FPS)
            person_crop(clip, t, person["best_box"], out / f"{person['id']}.jpg", meta["width"], meta["height"])
        middle = meta["duration_s"] / 2
        if not middle_frame(clip, middle, people, out / "frame.jpg"):
            raise JobFailed("track", "the picture of the clip could not be made")
        public = [{k: v for k, v in p.items() if k not in ("best_frame", "best_box")} for p in people]
        result = {"people": public, "frame": "people/frame.jpg", "auto_id": auto_id(people)}
        (ctx.work / "people.json").write_text(json.dumps(result), encoding="utf-8")
        found = ", ".join(f"{p['id']} (coverage {p['coverage']}, box {p['box_mid']})" for p in people)
        applog.log(f"people found in {len(frames)} tracked frames: {found}; auto_id {result['auto_id']}", ctx.id, ctx.dir)
        return {"result": result}

    return run
