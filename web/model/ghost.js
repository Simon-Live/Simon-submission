// The trainer's ghost over the live camera preview, as data (docs/specs/follow-ghost.md, TICKET-264). Reads the
// `simon.skeleton2d.v1` document of `GET api/ghost/<entry>.json` (part7/ghost.py) and says which frame to draw at a
// clock and where its points land on the preview. `box: "image"` is the trainer's own Part 2 picture (shares of their
// `image_size`), drawn in their frame fitted inside the preview; `box: "body"` (an entry without it) has the body's
// height scaled to 1. No DOM, no fetch, no storage, and no pose model: the ghost is the trainer's data, sized by the
// person's "stand in the outline".
import { validSkeleton } from "./skeleton-frame.js";

export const SCALE = { start: 0.8, min: 0.5, max: 1, step: 0.1 };
export const IMAGE_SCALE = { start: 1, min: 0.5, max: 2, step: 0.1 }; // 1 is the trainer's own framing
export const FOOT_LINE = 0.95; // the body ghost's feet rest this far down the preview

const isImage = (doc) => Boolean(doc && doc.box === "image");
const goodSize = (s) => Array.isArray(s) && s.length === 2 && s.every((n) => Number.isFinite(n) && n > 0);

/** True for a ghost the preview can draw (the route says `available`, the frames are a valid skeleton, and an image
 * ghost has a positive `image_size`). */
export const usableGhost = (doc) => Boolean(doc && doc.available !== false && validSkeleton(doc)
  && (!isImage(doc) || goodSize(doc.image_size)));

/** The size range of a ghost: IMAGE_SCALE for the trainer's own picture, SCALE for a body ghost. */
export const scaleRange = (doc) => (isImage(doc) ? IMAGE_SCALE : SCALE);

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

/** A scale one step bigger (`dir` 1) or smaller (-1), kept inside `range` (SCALE or IMAGE_SCALE). */
export function stepScale(scale, dir, range = SCALE) {
  const next = Math.round((scale + dir * range.step) * 100) / 100;
  return Math.min(range.max, Math.max(range.min, next));
}

/** `(u, v) => [x, y]` on a `width` x `height` preview. Image ghost: the trainer's frame fitted inside the preview
 * (contain), `scale` times that about the centre. Body ghost: the box is `scale` of the height, feet on FOOT_LINE. */
function spot(doc, width, height, scale) {
  if (isImage(doc)) {
    const [w, h] = doc.image_size;
    const fit = Math.min(width / w, height / h) * scale;
    return (u, v) => [width / 2 + (u - 0.5) * w * fit, height / 2 + (v - 0.5) * h * fit];
  }
  const box = scale * height;
  const top = FOOT_LINE * height - box;
  return (u, v) => [width / 2 + (u - 0.5) * box, top + v * box];
}

/**
 * What to draw for frame `index` on a `width` x `height` picture, placed by `spot` (`scale` defaults to the start of
 * the ghost's range). `mirrored` flips left and right to match a mirrored reference (and a mirrored preview).
 * @returns {{index, t, points: Array<[number, number]|null>, bones: Array<[number, number]>}}
 */
export function placeGhost(doc, index, width, height, { scale = scaleRange(doc).start, mirrored = true } = {}) {
  const frame = doc.frames[Math.max(0, Math.min(doc.frames.length - 1, index))];
  const at = spot(doc, width, height, scale);
  const points = frame.pts.map((p) => {
    if (!Array.isArray(p) || !Number.isFinite(p[0]) || !Number.isFinite(p[1])) return null;
    return at(mirrored ? 1 - p[0] : p[0], p[1]);
  });
  const bones = doc.bones.filter(([a, b]) => points[a] && points[b]).map(([a, b]) => [a, b]);
  return { index: doc.frames.indexOf(frame), t: frame.t, points, bones };
}
