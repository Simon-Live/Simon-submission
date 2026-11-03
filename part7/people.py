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

from part7 import applog, config, crop, media, modules, quality, runner, stagelog
from part7 import track_resample
from part7.jobs import JobContext, JobFailed, JobFn
from part7.parts import p2_pose

AUTO_COVERAGE = 0.6  # exactly one person at or above this is chosen without asking
MIN_COVERAGE = 0.1  # tracks seen in less of the clip are tracker noise and are not offered
# A track whose box barely moves over the clip is a thing (a poster, a reflection), not a person moving: its box
# centre, width and height each vary (10th to 90th percentile) by less than this share of its own height.
# Measured on a 10 s take: the person 0.50; two objects SAM 3.1 tracked on the wall 0.03 and 0.04.
MIN_MOTION = 0.10
MIN_PRESENT_ENV = "SIMON7_PEOPLE_MIN_PRESENT_S"  # TICKET-198: a participant is in the take at least this long
MIN_PRESENT_S = 2.0
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
TRACK_FPS_FILE = "track_fps.json"
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


def min_present_s() -> float:
    return applog.env_float(MIN_PRESENT_ENV, MIN_PRESENT_S)


def _candidates(frames: list[dict[str, Any]], width: int, height: int, fps: float | None) -> list[dict[str, Any]]:
    """Every track seen in at least `MIN_COVERAGE` of the clip, with its motion and (given `fps`) seconds present."""
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
        motion = _motion([box for _, box, _ in boxes])
        mid = min(boxes, key=lambda item: abs(item[0] - middle))
        best = max(boxes, key=lambda item: item[1][2] * item[1][3] * (item[2] or 0.5))
        people.append(
            {"id": pid, "coverage": round(coverage, 3), "frames": len({n for n, _, _ in boxes}),
             "box_mid": _scaled(mid[1], kx, ky), "best_frame": best[0], "best_box": _scaled(best[1], kx, ky),
             "motion": motion, "present_s": round(len({n for n, _, _ in boxes}) / fps, 2) if fps else None}
        )
    return people


@dataclass
class Selection:
    """Who is offered, from the candidates: the one predicate of `summarize` and the 10 fps repeat (TICKET-202)."""

    offered: list[dict[str, Any]]
    participants: list[dict[str, Any]]  # moving and in the take for `min_present_s()`
    dropped: list[dict[str, Any]]  # moving, too brief to be a participant, and not offered because someone qualifies

    @property
    def dropped_s(self) -> float:
        return round(float(sum(p["present_s"] for p in self.dropped)), 2)

    @property
    def split_suspect(self) -> bool:
        """Brief moving tracks that together cover more than `min_present_s()`: one member the tracker cut in pieces."""
        return bool(self.dropped) and self.dropped_s > min_present_s()


def select(people: list[dict[str, Any]], fps: float | None) -> Selection:
    """Apply the movement filter, and with `fps` the presence filter. A take with no participant keeps the movers
    (and everyone when nothing moves), as before TICKET-198."""
    moving = [p for p in people if p["motion"] >= MIN_MOTION]
    if not fps:  # only people who move are offered; a clip where nothing moves keeps everyone rather than no one
        return Selection(moving or people, [], [])
    need = min_present_s()
    participants = [p for p in moving if p["present_s"] >= need]
    if participants:
        return Selection(participants, participants, [p for p in moving if p["present_s"] < need])
    return Selection(moving or people, [], [])


def summarize(frames: list[dict[str, Any]], width: int, height: int, fps: float | None = None) -> list[dict[str, Any]]:
    """The offered people, by coverage descending: `{id, coverage, frames, box_mid, best_frame}`.

    `box_mid` is the box nearest the middle of the clip, `best_frame` the frame of the largest, surest box;
    both in video pixels. With `fps` (the rate the frames were tracked at) only participants are offered: a track in
    the take for at least `min_present_s()` seconds that also passes the movement filter; a take with no participant
    keeps the movement filter alone (and everyone when nothing moves), as before TICKET-198.
    """
    people = list(select(_candidates(frames, width, height, fps), fps).offered)
    people.sort(key=lambda p: -p["coverage"])
    return people[:MAX_PEOPLE]


def _motion(boxes: list[list[float]]) -> float:
    """How much a track's box moves over the clip: the largest 10th-to-90th percentile spread of its centre x,
    centre y, width and height, as a share of its median height (0 for a box that never changes)."""
    if len(boxes) < 2:
        return 0.0
    def spread(values: list[float]) -> float:
        v = sorted(values)
        return v[int(0.9 * (len(v) - 1))] - v[int(0.1 * (len(v) - 1))]
    heights = sorted(b[3] for b in boxes)
    h = heights[len(heights) // 2] or 1.0
    series = ([b[0] + b[2] / 2 for b in boxes], [b[1] + b[3] / 2 for b in boxes], [b[2] for b in boxes], [b[3] for b in boxes])
    return round(max(spread(s) for s in series) / h, 3)


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
def _why(step: runner.Step) -> str:
    """Part 2's last meaningful line of a failed step, from its log (else its output)."""
    return stagelog.last_meaningful(step.get("log")) or stagelog.tail(step.stdout, 1) or f"exit {step.get('exit')}"


def _finder_failure(ctx: JobContext, step: runner.Step) -> str:
    """The track failure reason; after a failed first tracker it names both reasons and logs both log paths."""
    first = step.get("first_try")
    if not first:
        return "the people finder failed"
    applog.log(f"track: first attempt {stagelog.step_failure(first)}; retry {stagelog.step_failure(step)}",
               applog.job_id_of(ctx.work), ctx.work, logging.WARNING)
    return f"the people finder failed: first attempt: {_why(first)}; retry: {_why(step)}"


def _find_people(
    ctx: JobContext, clip: Path, backend: str, lock: modules.Modules | None, state: Path | str | None,
    steps: list[runner.Step], fps: int | None = None, work: Path | None = None,
) -> Path:
    """Run Part 2 until `tracks.json` exists; return its path in the job's work folder.

    The Part 2 steps are added to `steps`, so the stage line names their exits (`2:<exit>`, TICKET-067): a
    failed named tracker attempt and the fallback that followed it are both listed.
    """
    ctx.set_stage("track")
    lk = lock or modules.load()
    where = work or ctx.work  # the TICKET-198 repeat at 10 fps writes in its own folder
    try:
        if p2_pose.capabilities(lk, state)["track"]:
            kw = {"fps": fps} if fps else {}
            step, found = p2_pose.track(clip, where, backend=backend, lock=lk, state=state, **kw)
            if step.get("first_try"):
                steps.append(step["first_try"])  # the failed tracker attempt; its exit shows in the stage line
        else:
            ctx.add_note(NOTE_NO_TRACK)
            step, pose = p2_pose.run(clip, ctx.work, backend=backend, lock=lk, state=state, multi=True)
            found = pose.with_name("tracks.json")
            if pose.is_file():
                shutil.copyfile(pose, ctx.work / "pose3d_all.json")  # a later job reuses it (see `pose_for`)
    except TimeoutError:
        raise JobFailed("track", "the GPU is busy, try again in a few minutes") from None
    except RuntimeError:
        raise JobFailed("track", "the people finder is not available") from None
    steps.append(step)
    if step["exit"] != 0 or not found.is_file():
        raise JobFailed("track", "the people finder timed out" if step.get("timed_out") else _finder_failure(ctx, step))
    tracks = ctx.work / "tracks.json"
    shutil.copyfile(found, tracks)
    if (found.parent / "frames.json").is_file():  # top level sorts first in `frame_times`: the kept attempt's times
        shutil.copyfile(found.parent / "frames.json", ctx.work / "frames.json")
    return tracks


def _selection(tracks: Path, meta: dict[str, Any], fps: int) -> Selection | None:
    """The shared selection of a tracks file; None for an unreadable or empty one."""
    try:
        frames = crop.load_tracks(tracks)
    except ValueError:
        return None
    return select(_candidates(frames, meta["width"], meta["height"], fps), fps) if frames else None


def _has_participant(tracks: Path, meta: dict[str, Any], fps: int) -> bool:
    """True when `select` finds a participant (present `min_present_s()` and moving); an unreadable file counts as no."""
    found = _selection(tracks, meta, fps)
    return bool(found and found.participants)


def _repeat_reason(tracks: Path, meta: dict[str, Any], fps: int) -> str | None:
    """Why the low-rate result is not trusted: no participant, or a member that looks cut into brief pieces."""
    found = _selection(tracks, meta, fps)
    if not found or not found.participants:
        return f"no participant at {fps} fps (present {min_present_s()} s and moving)"
    if found.split_suspect:
        return (f"{len(found.dropped)} brief moving tracks at {fps} fps cover {found.dropped_s} s together "
                f"(over {min_present_s()} s): one member may be split")
    return None


def _track_people(
    ctx: JobContext, clip: Path, meta: dict[str, Any], mode: str | None, backend: str,
    lock: modules.Modules | None, state: Path | str | None, steps: list[runner.Step],
) -> Path:
    """Find the people at the rate the take's mode asks for (TICKET-198); a take (single or group) with no participant
    at its low rate is tracked once more at `FALLBACK_TRACK_FPS`. The rate kept is written to `track_fps.json`."""
    fps, kind = p2_pose.track_fps_for(mode)
    applog.log(f"people tracking at {fps} fps ({kind})", ctx.id, ctx.dir)
    tracks = _find_people(ctx, clip, backend, lock, state, steps, fps)
    # a pin without `track` ran a full multi run at the 3D rate: the rate does not apply and there is nothing to repeat
    has_track = p2_pose.capabilities(lock or modules.load(), state)["track"]
    if not has_track:
        fps = p2_pose.FPS
    reason = _repeat_reason(tracks, meta, fps) if has_track and fps < p2_pose.FALLBACK_TRACK_FPS else None
    if reason:
        applog.log(f"{reason}: tracking again at {p2_pose.FALLBACK_TRACK_FPS} fps ({kind})", ctx.id, ctx.dir)
        tracks, fps = _repeat_fast(ctx, clip, backend, lock, state, steps, tracks, fps)
    (ctx.work / TRACK_FPS_FILE).write_text(json.dumps({"fps": fps, "mode": kind}), encoding="utf-8")
    return tracks


def _repeat_fast(
    ctx: JobContext, clip: Path, backend: str, lock: modules.Modules | None, state: Path | str | None,
    steps: list[runner.Step], tracks: Path, fps: int,
) -> tuple[Path, int]:
    """The one repeat at `FALLBACK_TRACK_FPS`. It starts from no `frames.json` so frame times never mix rates; when it
    fails or times out the usable low-rate result and its frame times stay and the failure is logged (TICKET-202)."""
    kept = ctx.work / "frames.json"
    aside = ctx.work / "frames.lowrate.json"
    if kept.is_file():
        kept.replace(aside)
    try:
        fast = _find_people(ctx, clip, backend, lock, state, steps, p2_pose.FALLBACK_TRACK_FPS, ctx.work / "retry_fps")
    except JobFailed as exc:
        if aside.is_file():
            aside.replace(kept)
        applog.anomaly("people_retry_failed", job=ctx.id, job_dir=ctx.dir, fps=p2_pose.FALLBACK_TRACK_FPS, error=str(exc))
        return tracks, fps
    aside.unlink(missing_ok=True)
    return fast, p2_pose.FALLBACK_TRACK_FPS


def tracked_fps(people_work: Path) -> int:
    """The rate the people job tracked at (`track_fps.json`); `p2_pose.TRACK_FPS` for a job from before TICKET-198."""
    try:
        value = int(json.loads((people_work / TRACK_FPS_FILE).read_text(encoding="utf-8"))["fps"])
        if value > 0:
            return value
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return p2_pose.TRACK_FPS


def _note_tracker(ctx: JobContext, tracks: Path) -> None:
    try:
        name = str((json.loads(tracks.read_text(encoding="utf-8")).get("provenance") or {}).get("tracker") or "")
    except (OSError, ValueError, AttributeError):
        return
    if any(word in name for word in OPEN_TRACKERS):
        ctx.add_note(f"people were found with the fallback tracker {name}")


def _resampled(
    tracks: Path, work: Path, rate: float, video: Path, frame_time: dict[int, float] | None, lk: modules.Modules
) -> Path:
    """`tracks` at the 3D rate over exactly the frames Part 2 samples from `video` (TICKET-203): the times
    `part2 frame-times` lists; a pin without it falls back to Part 7's copy of the rule on the ffprobe timestamps, and
    that to an even spacing at the clip's stated rate."""
    at = p2_pose.frame_times(video, work, p2_pose.FPS, lk)
    if at is None:
        at = track_resample.probe_sample_times(video, p2_pose.FPS)
    if at is None:
        meta = media.probe(video)
        at = track_resample.uniform_sample_times(meta["duration_s"], meta["fps"], p2_pose.FPS)
    return track_resample.write_at_rate(tracks, work / f"tracks_{p2_pose.FPS}fps.json", rate, p2_pose.FPS,
                                        media.probe(video)["duration_s"], frame_time, out_times=at)


def _frames_mismatch(work: Path) -> bool:
    """True when Part 2's log says the tracks and its sampled frames differ (`--tracks` has an entry/no entry for frame)."""
    try:
        text = (work / "steps" / "part2.log").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return "--tracks" in text and ("that this input lacks" in text or "has no entry for frame" in text)


def _retrack_for_3d(
    video: Path, work: Path, backend: str, lk: modules.Modules, state: Path | str | None, ids: list[str],
    failed: runner.Step, failed_pose: Path,
) -> tuple[runner.Step, Path]:
    """Part 2 refused the resampled tracks: track the clip at the 3D rate (no resampling) and run 3D once more. When the
    re-track fails or loses a wanted person, the first failure stands (TICKET-203)."""
    applog.anomaly("tracks_frame_mismatch", "Part 2 refused the resampled tracks; tracking again at the 3D rate",
                   job=applog.job_id_of(work), job_dir=work, fps=p2_pose.FPS)
    try:
        t_step, found = p2_pose.track(video, work / "retrack_3d", backend=backend, lock=lk, state=state, fps=p2_pose.FPS)
        if t_step["exit"] != 0 or not found.is_file():
            return failed, failed_pose
        have = {str(p.get("id")) for f in json.loads(found.read_text(encoding="utf-8")).get("frames", [])
                for p in f.get("people", []) if isinstance(p, dict)}
    except (OSError, ValueError, TimeoutError):
        return failed, failed_pose
    if not {str(i) for i in ids} <= have:
        applog.anomaly("tracks_frame_mismatch", "the re-track lost a wanted person; the first failure stands",
                       job=applog.job_id_of(work), job_dir=work)
        return failed, failed_pose
    return p2_pose.run(video, work, backend=backend, lock=lk, state=state, tracks=found, ids=ids)


def pose_for(
    sel: PersonSel, ids: list[str], video: Path, work: Path, backend: str, lk: modules.Modules, state: Path | str | None
) -> tuple[runner.Step, Path, str | None]:
    """3D for `ids` of the people job: Part 2 `--tracks --ids` when the pin has it, else everyone.

    Returns `(step, pose3d.json, note)`; a note names the fallback (people.md "Part 2 follow-up").
    """
    tracks = (sel.people_work or work) / "tracks.json"
    rate = tracked_fps(sel.people_work or work)
    resampled = tracks.is_file() and rate != p2_pose.FPS
    if resampled:  # people tracked at another rate than the 3D run (#62, TICKET-198)
        tracks = _resampled(tracks, work, rate, video, frame_times(sel.people_work or work) or None, lk)
        applog.log(f"people tracks at {rate} fps resampled to {p2_pose.FPS} fps for the 3D run", applog.job_id_of(work), work)
    if tracks.is_file() and p2_pose.capabilities(lk, state)["ids"]:
        step, pose = p2_pose.run(video, work, backend=backend, lock=lk, state=state, tracks=tracks, ids=ids)
        if resampled and step["exit"] != 0 and _frames_mismatch(work):
            step, pose = _retrack_for_3d(video, work, backend, lk, state, ids, step, pose)
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
    mode: str | None = None,
) -> JobFn:
    """Return the job function of `POST api/people`. `mode` is "single" or "group" (None: group, TICKET-198)."""

    def run(ctx: JobContext) -> dict[str, Any]:
        clip = prepare_clip(ctx, raw, trim)
        meta = media.probe(clip)
        steps: list[runner.Step] = []
        with stagelog.stage(ctx.work, "track", steps, video=stagelog.video_facts(clip), backend=backend):
            tracks = _track_people(ctx, clip, meta, mode, backend, lock, state, steps)
        _note_tracker(ctx, tracks)
        ctx.set_stage("people")
        try:
            frames = crop.load_tracks(tracks)
        except ValueError:
            raise JobFailed("track", "the people finder wrote no result") from None
        people = summarize(frames, meta["width"], meta["height"], tracked_fps(ctx.work)) if frames else []
        if not people:
            raise JobFailed("track", NO_ONE)
        out = ctx.dir / "people"
        out.mkdir(parents=True, exist_ok=True)
        times = frame_times(ctx.work)
        for person in people:
            t = times.get(person["best_frame"], person["best_frame"] / tracked_fps(ctx.work))
            person_crop(clip, t, person["best_box"], out / f"{person['id']}.jpg", meta["width"], meta["height"])
        middle = meta["duration_s"] / 2
        if not middle_frame(clip, middle, people, out / "frame.jpg"):
            raise JobFailed("track", "the picture of the clip could not be made")
        chosen = select(_candidates(frames, meta["width"], meta["height"], tracked_fps(ctx.work)), tracked_fps(ctx.work))
        applog.log(f"dropped moving tracks: {len(chosen.dropped)}, {chosen.dropped_s} s in total", ctx.id, ctx.dir)
        public = [{k: v for k, v in p.items() if k not in ("best_frame", "best_box", "present_s")} for p in people]
        result = {"people": public, "frame": "people/frame.jpg", "auto_id": auto_id(people)}
        signals = quality.people_quality(tracks)
        if signals:
            result["people_quality"] = {p["id"]: signals[p["id"]] for p in public if p["id"] in signals}
        (ctx.work / "people.json").write_text(json.dumps(result), encoding="utf-8")
        found = ", ".join(f"{p['id']} (coverage {p['coverage']}, box {p['box_mid']}, motion {p['motion']})" for p in people)
        applog.log(f"people found in {len(frames)} tracked frames: {found}; auto_id {result['auto_id']}", ctx.id, ctx.dir)
        tracked = {str(q.get("id")) for f in frames for q in f["people"] if isinstance(q, dict)}
        still = sorted(tracked - {p["id"] for p in people})
        if still:
            applog.log(f"passer-by, not offered (did not move, or in the take under {min_present_s()} s): "
                       f"tracks {', '.join(still)}", ctx.id, ctx.dir)
        return {"result": result}

    return run
