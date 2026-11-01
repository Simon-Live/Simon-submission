// The trainer's joints Part 3 never saw, as data for the 3D compare and the results summary (compare-view.md, TICKET-116).
// Part 4's animation.json (so Part 5's replay) drops Part 3's "unseen" mark; part7/trainer_visibility.py answers it from
// the trainer's Part 3 skeleton as `{joints, t, unseen}`: `unseen[k]` lists the joint indices unseen at `t[k]` seconds.
// Pure mapping, no measurement: it only places that mark on the replay's expected frames.

/** True for a usable `simon.trainer_visibility.v1` payload. */
export function validVisibility(doc) {
  return !!doc && Array.isArray(doc.joints) && Array.isArray(doc.t) && Array.isArray(doc.unseen) && doc.t.length > 0
    && doc.t.length === doc.unseen.length && doc.t.every(Number.isFinite)
    && doc.unseen.every((u) => Array.isArray(u) && u.every((i) => Number.isInteger(i) && i >= 0 && i < doc.joints.length));
}

/** Index of the entry of the ascending `times` nearest `t` (the earlier one on a tie). */
function nearest(times, t) {
  let lo = 0, hi = times.length - 1;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (times[mid] < t) lo = mid + 1; else hi = mid;
  }
  return lo > 0 && Math.abs(times[lo - 1] - t) <= Math.abs(times[lo] - t) ? lo - 1 : lo;
}

/**
 * Per expected frame, the model joint indices the trainer's Part 3 skeleton marks unseen. `times[i]` is the trainer
 * time of expected frame i in seconds. A joint the model does not have is ignored; a bad document marks nothing.
 */
export function trainerUnseenByFrame(doc, joints, times) {
  if (!validVisibility(doc)) return times.map(() => []);
  const toModel = doc.joints.map((n) => joints.indexOf(n));
  return times.map((t) => doc.unseen[nearest(doc.t, t)].map((i) => toModel[i]).filter((i) => i >= 0));
}

/** `have` (indices already dimmed in a frame) plus `extra`, each once, in ascending order. */
export const unionIndices = (have, extra) => [...new Set([...have, ...extra])].sort((a, b) => a - b);
