// The trainer's ghost over the live camera preview, as data (docs/specs/follow-ghost.md, TICKET-264). Reads the
// `simon.skeleton2d.v1` document of `GET api/ghost/<entry>.json` (part7/ghost.py: the trainer's own joints, the body's
// height scaled to 1) and says which frame to draw at a clock and where its points land on the preview. No DOM, no
// fetch, no storage, and no pose model: the ghost is the trainer's data, placed by the person's "stand in the outline".
import { validSkeleton } from "./skeleton-frame.js";

export const SCALE = { start: 0.8, min: 0.5, max: 1, step: 0.1 };
export const FOOT_LINE = 0.95; // the ghost's feet rest this far down the preview

/** True for a ghost the preview can draw (the route says `available` and the frames are a valid skeleton). */
export const usableGhost = (doc) => Boolean(doc && doc.available !== false && validSkeleton(doc));

/** The ghost's length in seconds (the last frame's time), 0 for a one-frame ghost. */
export const ghostDuration = (doc) => (doc.frames.length ? doc.frames[doc.frames.length - 1].t : 0);

/**
 * The ghost clock in seconds. `refS` is the docked reference video's own clock (it loops with the clip), used whenever
 * it is a number; otherwise the recording clock `elapsedMs` loops inside the ghost; before recording it is 0.
 */
export function ghostClock(refS, elapsedMs, durationS) {
  if (Number.isFinite(refS)) return Math.max(0, refS);
  if (!Number.isFinite(elapsedMs)) return 0;
  const t = Math.max(0, elapsedMs) / 1000;
  return durationS > 0 ? t % durationS : t;
}

/** The index of the frame nearest `t` (the earlier one on a tie). */
export function frameIndexAt(doc, t) {
  const fr = doc.frames;
  let lo = 0, hi = fr.length - 1;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (fr[mid].t < t) lo = mid + 1; else hi = mid;
  }
  return lo > 0 && Math.abs(fr[lo - 1].t - t) <= Math.abs(fr[lo].t - t) ? lo - 1 : lo;
}

/** A scale one step bigger (`dir` 1) or smaller (-1), kept inside SCALE. */
export function stepScale(scale, dir) {
  const next = Math.round((scale + dir * SCALE.step) * 100) / 100;
  return Math.min(SCALE.max, Math.max(SCALE.min, next));
}

/**
 * What to draw for frame `index` on a `width` x `height` picture: the body box is `scale` of the height tall, centred,
 * feet on FOOT_LINE. `mirrored` flips left and right to match a mirrored reference (and a mirrored preview).
 * @returns {{index, t, points: Array<[number, number]|null>, bones: Array<[number, number]>}}
 */
export function placeGhost(doc, index, width, height, { scale = SCALE.start, mirrored = true } = {}) {
  const frame = doc.frames[Math.max(0, Math.min(doc.frames.length - 1, index))];
  const box = scale * height;
  const top = FOOT_LINE * height - box;
  const points = frame.pts.map((p) => {
    if (!Array.isArray(p) || !Number.isFinite(p[0]) || !Number.isFinite(p[1])) return null;
    const u = mirrored ? 1 - p[0] : p[0];
    return [width / 2 + (u - 0.5) * box, top + p[1] * box];
  });
  const bones = doc.bones.filter(([a, b]) => points[a] && points[b]).map(([a, b]) => [a, b]);
  return { index: doc.frames.indexOf(frame), t: frame.t, points, bones };
}
