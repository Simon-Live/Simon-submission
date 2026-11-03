// "Fix it for me" (docs/specs/fix-it-for-me.md, TICKET-265): the pure part. A coaching moment names a faulted joint and a
// time window (Part 5 analysis.faults[].joints and follower_t_s). The student's own take is replayed with only that limb
// moved toward the trainer's shape, using Part 5's alignment (replay exp_to_fol) to pick the trainer's frame. No DOM, no
// fetch, no storage. It never scores anything and never claims the student moved that way: the words in TEXT say so.
// Bone lengths stay the student's own, only the bone directions turn toward the trainer's.

export const EASE_S = 0.3;          // the blend eases in before the window and out after it over this long
export const CLIP_PAD_S = 0.9;      // the replay clip starts and ends this far outside the window
export const MIN_MOVED_DEG = 0.5;   // a limb that already points where the trainer's does shows no button for it

export const TEXT = Object.freeze({
  button: "Fix it for me",
  lead: "Replay this moment on your own body, with the limb this note is about moved toward the trainer's pose.",
  caption: "A preview of the trainer's pose on your body, not a measurement. Your score is unchanged.",
  before: "Before",
  after: "After",
  split: "Side by side",
  single: "One view",
  close: "Close",
  you: "You",
  youCorrected: "You, corrected",
  trainer: "Trainer",
  pick: "Moment to fix",
  noWebgl: "The 3D view is not available in this browser, so the preview cannot be shown.",
});

/** "Your take, with the left arm moved toward the trainer's pose": the one label that says what the picture is. */
export const labelFor = (limbs) => `Your take, with the ${limbs.join(" and ")} moved toward the trainer's pose`;

// each limb: the joint that stays put and the joints that follow, in order from the root
const LIMBS = Object.freeze({
  arm: ["shoulder", "elbow", "wrist"],
  leg: ["hip", "knee", "ankle"],
});
const LIMB_OF = Object.freeze({ shoulder: "arm", elbow: "arm", wrist: "arm", hip: "leg", knee: "leg", ankle: "leg" });
const NOT_A_LIMB = new Set(["torso", "trunk", "core", "spine", "head", "neck", "face"]);

/** The limb chains a fault names, [{side, limb, joints: [root, mid, end]}], or [] when it is not an arm or leg fault. */
export function chainsOf(fault) {
  if (!fault || !Array.isArray(fault.joints)) return [];
  if (NOT_A_LIMB.has(String(fault.body_part || "").toLowerCase())) return [];
  const out = [];
  for (const name of fault.joints) {
    const m = /^(left|right)_([a-z]+)$/.exec(String(name));
    const limb = m && LIMB_OF[m[2]];
    if (!limb) continue;
    const key = `${m[1]}_${limb}`;
    if (!out.some((c) => c.key === key)) out.push({ key, side: m[1], limb, joints: LIMBS[limb].map((j) => `${m[1]}_${j}`) });
  }
  return out;
}

/** The words for a fault's limbs: "left arm", "right leg". */
export const limbNames = (chains) => chains.map((c) => `${c.side} ${c.limb}`);

const finite = (x) => typeof x === "number" && Number.isFinite(x);

/**
 * The fault's time window in follower seconds: Part 5's follower_t_s, widened to hold the moment `at_s` names (which can
 * sit a frame outside it). Null when the fault has no usable time.
 */
export function windowOf(fault) {
  const t = fault && Array.isArray(fault.follower_t_s) && fault.follower_t_s.length === 2 && fault.follower_t_s.every(finite) ? fault.follower_t_s : null;
  const at = fault && finite(fault.at_s) ? fault.at_s : null;
  if (!t && at === null) return null;
  const lo = Math.min(...(t || [at]), ...(at === null ? [] : [at]));
  const hi = Math.max(...(t || [at]), ...(at === null ? [] : [at]));
  return { start: Math.max(0, lo), end: Math.max(0, hi), at };
}

const smooth = (x) => { const k = Math.min(1, Math.max(0, x)); return k * k * (3 - 2 * k); };

/** The blend weight at follower time `t`: 1 inside the window, eased to 0 over EASE_S before and after, 0 elsewhere. */
export function blendWeight(t, win, ease = EASE_S) {
  if (!win || !finite(t)) return 0;
  if (t >= win.start && t <= win.end) return 1;
  if (t < win.start) return t <= win.start - ease ? 0 : smooth(1 - (win.start - t) / ease);
  return t >= win.end + ease ? 0 : smooth(1 - (t - win.end) / ease);
}

/** The time span the eased blend touches: outside it the corrected pose is the take's own, joint for joint. */
export const touchedSpan = (win, ease = EASE_S) => ({ start: Math.max(0, win.start - ease), end: win.end + ease });

const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const len = (v) => Math.hypot(v[0], v[1], v[2]);
const ok3 = (p) => Array.isArray(p) && p.length === 3 && p.every(finite);

/** The angle in degrees between two vectors; 0 when either has no length. */
export function angleDeg(u, v) {
  const lu = len(u), lv = len(v);
  if (!(lu > 1e-9) || !(lv > 1e-9)) return 0;
  return (Math.acos(Math.min(1, Math.max(-1, (u[0] * v[0] + u[1] * v[1] + u[2] * v[2]) / (lu * lv)))) * 180) / Math.PI;
}

/** The unit vector a fraction `w` of the way from unit `a` to unit `b` along the great circle. */
export function slerp(a, b, w) {
  const dot = Math.min(1, Math.max(-1, a[0] * b[0] + a[1] * b[1] + a[2] * b[2]));
  const theta = Math.acos(dot);
  if (theta < 1e-6) return a.slice();
  let ax = a;
  let sinT = Math.sin(theta);
  if (sinT < 1e-6) {   // opposite directions: turn through any perpendicular
    const p = Math.abs(a[0]) < 0.9 ? [1, 0, 0] : [0, 1, 0];
    ax = [a[1] * p[2] - a[2] * p[1], a[2] * p[0] - a[0] * p[2], a[0] * p[1] - a[1] * p[0]];
    const l = len(ax);
    ax = ax.map((c) => c / l);
    const ang = Math.PI * w;
    return [0, 1, 2].map((i) => a[i] * Math.cos(ang) + ax[i] * Math.sin(ang));
  }
  const s0 = Math.sin((1 - w) * theta) / sinT;
  const s1 = Math.sin(w * theta) / sinT;
  return [0, 1, 2].map((i) => a[i] * s0 + b[i] * s1);
}

/**
 * The follower's pose with the chains' bones turned `w` of the way toward the trainer's bone directions. Bones keep the
 * follower's length; the chain's root joint and every joint outside the chains are the follower's own, unchanged. A bone
 * whose ends the follower or the trainer did not show moves with its parent and is not turned. Returns a new pose.
 */
export function correctPose(follower, trainer, index, chains, w) {
  const out = follower.map((p) => (p ? p.slice() : p));
  if (!(w > 0) || !trainer) return out;
  for (const chain of chains) {
    const ids = chain.joints.map((n) => index.get(n));
    if (ids.some((i) => i === undefined)) continue;
    for (let k = 1; k < ids.length; k++) {
      const [a, b] = [ids[k - 1], ids[k]];
      const fa = follower[a], fb = follower[b], ta = trainer[a], tb = trainer[b];
      if (!ok3(fa) || !ok3(fb) || !ok3(out[a])) continue;
      const v = sub(fb, fa);
      const l = len(v);
      if (ok3(ta) && ok3(tb) && l > 1e-9 && len(sub(tb, ta)) > 1e-9) {
        const dt = sub(tb, ta);
        const dir = slerp(v.map((c) => c / l), dt.map((c) => c / len(dt)), Math.min(1, w));
        out[b] = [0, 1, 2].map((i) => out[a][i] + dir[i] * l);
      } else {
        out[b] = [0, 1, 2].map((i) => fb[i] + out[a][i] - fa[i]);   // rides with its parent
      }
    }
  }
  return out;
}

/** The chains' bones as [from, to] joint-name pairs. */
export const bonesOf = (chains) => chains.flatMap((c) => [[c.joints[0], c.joints[1]], [c.joints[1], c.joints[2]]]);

/**
 * What a correction did to the chains, in degrees: `moved` is the largest turn from the take's own bone direction,
 * `toward` the largest angle left to the trainer's. `outside` is the largest distance (metres) any joint outside the
 * chains moved, which is 0 for a correct blend. Joints in `skip` (the chains' moving joints) are not counted in `outside`.
 */
export function report(follower, shown, trainer, index, chains) {
  let moved = 0;
  let toward = 0;
  const inChain = new Set();
  for (const c of chains) c.joints.slice(1).forEach((n) => inChain.add(index.get(n)));
  for (const [an, bn] of bonesOf(chains)) {
    const a = index.get(an), b = index.get(bn);
    if (![follower[a], follower[b], shown[a], shown[b]].every(ok3)) continue;
    moved = Math.max(moved, angleDeg(sub(follower[b], follower[a]), sub(shown[b], shown[a])));
    if (trainer && ok3(trainer[a]) && ok3(trainer[b])) toward = Math.max(toward, angleDeg(sub(trainer[b], trainer[a]), sub(shown[b], shown[a])));
  }
  let outside = 0;
  follower.forEach((p, i) => {
    if (inChain.has(i) || !ok3(p) || !ok3(shown[i])) return;
    outside = Math.max(outside, len(sub(p, shown[i])));
  });
  return { moved, toward, outside };
}

/** How far (degrees) the chains' bones differ from the trainer's at the fault, before any blend: the size of the correction. */
export function gapDeg(follower, trainer, index, chains) {
  return report(follower, follower, trainer, index, chains).toward;
}

/**
 * The faults the button can act on, with what it needs: [{index, fault, chains, limbs, label, win, at, gap, peak}]. A fault is kept
 * only when it names an arm or a leg, has a time, and the trainer's shape differs from the take's own somewhere in its
 * window (otherwise the replay would show nothing). `gap` is the difference at the fault's moment, `peak` the largest in the window.
 * `pick(t)` is compare.js pickFrames; `model` is its replay model.
 */
export function fixableFaults(analysis, model, pick) {
  const out = [];
  const index = new Map(model.joints.map((n, i) => [n, i]));
  (analysis && Array.isArray(analysis.faults) ? analysis.faults : []).forEach((fault, i) => {
    const chains = chainsOf(fault);
    const win = windowOf(fault);
    if (!chains.length || !win) return;
    const when = win.at !== null ? win.at : win.start;
    const gapAt = (t) => { const p = pick(t, model); return gapDeg(model.follower[p.follower], model.expected[p.expected], index, chains); };
    const gap = gapAt(when);
    let peak = { gap, at: when };   // where in the window the trainer's shape differs most: the best moment to show first
    for (let t = win.start; t <= win.end + 1e-9; t += 1 / model.fps) { const g = gapAt(t); if (g > peak.gap) peak = { gap: g, at: t }; }
    if (!(peak.gap >= MIN_MOVED_DEG)) return;
    const limbs = limbNames(chains);
    out.push({ index: i, fault, chains, limbs, label: labelFor(limbs), win, at: when, gap, peak });
  });
  return out;
}

/** The replay clip around a window, clamped to the take: [start, end] in follower seconds. */
export const clipOf = (win, duration) => ({ start: Math.max(0, win.start - CLIP_PAD_S), end: Math.min(duration, win.end + CLIP_PAD_S) });
