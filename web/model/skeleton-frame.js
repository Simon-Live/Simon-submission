// The follower's 2D skeleton at a moment, as data (docs/specs/models-and-skeleton-data.md R2, TICKET-154). Reads
// `GET api/results/<job>/skeleton2d.json` (part7/skeleton2d.py: Part 2's joints projected through its camera file) and
// says which joints Part 5's mistakes place near a time. No DOM, no fetch, no storage, and no new measurement
// (ADR-0006): a view draws what this returns.

/** A joint is lit when one of its mistakes is this close to the clock, in seconds. */
export const HOT_WINDOW_S = 0.6;

/** The route of a finished job's skeleton, or null for the example result. */
export const skeletonUrlFor = (job) => (!job || job === "fixture" ? null : `api/results/${encodeURIComponent(job)}/skeleton2d.json`);

/** True for a usable `simon.skeleton2d.v1` document (frames in time order). */
export function validSkeleton(doc) {
  if (!doc || !Array.isArray(doc.joints) || !Array.isArray(doc.bones) || !Array.isArray(doc.frames) || !doc.frames.length) return false;
  return doc.frames.every((f, i) => f && Number.isFinite(f.t) && Array.isArray(f.pts) && f.pts.length === doc.joints.length
    && (i === 0 || f.t >= doc.frames[i - 1].t));
}

/** The frame nearest `t` (the earlier one on a tie). */
export function frameAt(doc, t) {
  const fr = doc.frames;
  let lo = 0, hi = fr.length - 1;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (fr[mid].t < t) lo = mid + 1; else hi = mid;
  }
  return lo > 0 && Math.abs(fr[lo - 1].t - t) <= Math.abs(fr[lo].t - t) ? fr[lo - 1] : fr[lo];
}

/**
 * Every timed mistake of a Part 5 analysis as `{at, joints}`: faults (their own `joints`), insights and the misses of
 * the score timeline. `jointsOf(item, analysis)` names an insight's or miss's joints (web/timeline.js `jointsFor`), so
 * this module stays free of any view code.
 */
export function mistakesOf(analysis, jointsOf = () => []) {
  const out = [];
  const add = (at, joints) => {
    if (at === null || at === undefined || at === "" || !Number.isFinite(Number(at))) return;
    if (Array.isArray(joints) && joints.length) out.push({ at: Number(at), joints: [...joints] });
  };
  if (!analysis) return out;
  for (const f of analysis.faults || []) add(f && f.at_s, f && f.joints);
  for (const x of Array.isArray(analysis.insights) ? analysis.insights : []) add(x && x.at_s, jointsOf(x, analysis));
  const tl = analysis.score && Array.isArray(analysis.score.timeline) ? analysis.score.timeline : [];
  for (const w of tl) for (const m of (w && w.misses) || []) add(m && m.at_s, jointsOf(m, analysis));
  return out;
}

/** Joint names to light at `t`: those of every mistake within `win` seconds, sorted. */
export function hotJoints(mistakes, t, win = HOT_WINDOW_S) {
  const names = new Set();
  for (const m of mistakes) if (Math.abs(m.at - t) <= win) m.joints.forEach((j) => names.add(j));
  return [...names].sort();
}

/**
 * What a view draws at time `t` on a `width` x `height` box over the video: points in pixels (null when unseen),
 * the bones whose two ends are seen, and the lit joints (`hot` from the clock plus `pinned`, the tapped row's).
 * @returns {{t, points: Array<[number, number]|null>, bones: Array<[number, number, boolean]>, hot: string[], lit: number[]}}
 */
export function skeletonAt(doc, t, width, height, mistakes = [], pinned = []) {
  const frame = frameAt(doc, t);
  const points = frame.pts.map((p) => (Array.isArray(p) && Number.isFinite(p[0]) && Number.isFinite(p[1]) ? [p[0] * width, p[1] * height] : null));
  const hot = [...new Set([...hotJoints(mistakes, t), ...pinned])].sort();
  const lit = new Set(hot.map((n) => doc.joints.indexOf(n)).filter((i) => i >= 0));
  const bones = doc.bones.filter(([a, b]) => points[a] && points[b]).map(([a, b]) => [a, b, lit.has(a) || lit.has(b)]);
  return { t: frame.t, points, bones, hot, lit: [...lit].sort((a, b) => a - b) };
}
