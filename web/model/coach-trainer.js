// The trainer's video on the coach stage: where it should be, and how fast it should play, for a time on the follower's
// clock. Logic only: no DOM. views/coach-trainer.js draws the pane; coach-view.js keeps it in step with the stage clock.
// The real alignment is Part 5's replay (simon.replay.v1): `exp_to_fol[e]` is the follower frame matched to trainer frame
// `e`, and `expected_t[e]` is that trainer frame's time, which is the time in the entry's video (the entry's animation is
// cut from that video from 0 s). The trainer frame for a follower time is picked the way the 3D compare picks it
// (compare.js pickFrames), so the video and the 3D trainer show the same instant. With no usable replay the time is
// scaled by the two lengths (trainer duration / follower duration): coarse, it assumes an even pace through the take.
import { targetTime } from "./side-by-side.js";

export const DRIFT_S = 0.3;      // how far the trainer may stray from where it should be while playing before it is put back
export const REST_S = 0.04;      // and while paused
export const RATE_WINDOW_S = 0.5; // the local pace is read over this much follower time either side
export const RATE_MIN = 0.25;    // the pace is clamped to what browsers play smoothly
export const RATE_MAX = 4;
const RATE_STEP = 0.05;          // a playbackRate change smaller than this is not worth a stutter

export const TEXT = Object.freeze({ trainer: "Trainer", you: "You", video: "The trainer's video" });

const finite = (x) => (Number.isFinite(x) && x > 0 ? x : 0);

/** The alignment from a raw replay file, or null when it lacks a matched frame list (then timing falls back to scaling). */
export function alignmentOf(replay) {
  if (!replay || typeof replay !== "object") return null;
  const { fps, exp_to_fol: expToFol, expected_t: et } = replay;
  if (!(fps > 0) || !Array.isArray(expToFol) || !expToFol.length || !expToFol.every(Number.isFinite)) return null;
  const times = expToFol.map((_, i) => (Array.isArray(et) && et.length === expToFol.length && Number.isFinite(et[i]) ? et[i] : i / fps));
  const lastFollower = Array.isArray(replay.follower) && replay.follower.length ? replay.follower.length - 1 : Infinity;
  return { fps, expToFol, times, lastFollower };
}

/** The trainer's time (s) for follower time `t`. `align` from alignmentOf, or null to scale by `durations` {trainer, you}. */
export function trainerTime(t, align, durations = {}) {
  const at = Math.max(0, Number(t) || 0);
  if (align) {
    const f = Math.min(align.lastFollower, Math.round(at * align.fps));
    let e = 0;   // the largest e whose follower frame is not above f (the first one before the trainer starts)
    for (let i = align.expToFol.length - 1; i >= 0; i--) {
      if (align.expToFol[i] <= f) { e = i; break; }
    }
    return targetTime(align.times[e], durations.trainer);
  }
  const tr = finite(durations.trainer), you = finite(durations.you);
  return tr && you ? targetTime((at * tr) / you, tr) : targetTime(at, tr);
}

/** The trainer's playback rate around follower time `t`: its local pace, clamped; 0 while it holds a frame
 *  (before the matched part starts, after it ends, or where the follower lingers on one trainer instant). */
export function trainerRate(t, align, durations = {}) {
  const at = Math.max(0, Number(t) || 0);
  const lo = Math.max(0, at - RATE_WINDOW_S);
  const hi = at + RATE_WINDOW_S;
  const pace = (trainerTime(hi, align, durations) - trainerTime(lo, align, durations)) / (hi - lo);
  if (!(pace > 0.05)) return 0;
  return Math.min(RATE_MAX, Math.max(RATE_MIN, Number((Math.round(pace / RATE_STEP) * RATE_STEP).toFixed(2))));
}

/**
 * What to do to the trainer's video for the stage clock at follower time `t`.
 * `video` = {t, paused, rate} as the element reports them. Returns {seek: s|null, play: bool, rate: n|null}:
 * `seek` only when it has strayed, `rate` only when it should change.
 */
export function trainerStep(t, playing, video, align, durations = {}) {
  const want = trainerTime(t, align, durations);
  const rate = playing ? trainerRate(t, align, durations) : 0;
  const run = playing && rate > 0;
  const off = Math.abs((Number(video.t) || 0) - want);
  return {
    seek: off > (run ? DRIFT_S : REST_S) ? want : null,
    play: run,
    rate: run && Math.abs((Number(video.rate) || 1) - rate) >= RATE_STEP / 2 ? rate : null,
  };
}
