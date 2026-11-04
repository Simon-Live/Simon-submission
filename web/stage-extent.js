// The extent of a whole take, for the stage framing (docs/specs/model-skin.md AC16, "Take framing"). No three and no DOM:
// the stage (web/viewer3d.js) poses its skins on the frames picked here and projects the boxes with its own camera.

const EVEN_SAMPLES = 24; // frames spread evenly over the take, on top of the extreme ones

/** [cx, cy, cz] the hip centre of a pose, the point the stage puts on the figure's slot; [0,0,0] without both hips. */
export function hipCentre(pose, hipL, hipR) {
  const l = pose && pose[hipL], r = pose && pose[hipR];
  return l && r ? [(l[0] + r[0]) / 2, (l[1] + r[1]) / 2, (l[2] + r[2]) / 2] : [0, 0, 0];
}

/** The joints' box {min, max} relative to the hip centre, grown by `pad`; null for a frame with no joint. */
export function frameStickBox(pose, hipL, hipR, pad = 0) {
  if (!pose) return null;
  const c = hipCentre(pose, hipL, hipR);
  const min = [Infinity, Infinity, Infinity], max = [-Infinity, -Infinity, -Infinity];
  let any = false;
  for (const p of pose) {
    if (!p) continue;
    any = true;
    for (let k = 0; k < 3; k++) {
      const v = p[k] - c[k];
      if (v < min[k]) min[k] = v;
      if (v > max[k]) max[k] = v;
    }
  }
  if (!any) return null;
  return { min: min.map((v) => v - pad), max: max.map((v) => v + pad) };
}

/**
 * The indices of the frames the skin is posed on to find the take's extent: for each axis the frame reaching furthest
 * each way from the hips, the frame reaching furthest out from them on the floor, and `even` frames spread over the take.
 * Sorted, no repeats, null frames left out.
 */
export function extremeFrames(frames, hipL, hipR, even = EVEN_SAMPLES) {
  const best = Array.from({ length: 7 }, () => ({ v: -Infinity, i: -1 }));
  const keep = (slot, v, i) => { if (v > best[slot].v) best[slot] = { v, i }; };
  const picked = new Set();
  frames.forEach((pose, i) => {
    const b = frameStickBox(pose, hipL, hipR);
    if (!b) return;
    for (let k = 0; k < 3; k++) { keep(2 * k, b.max[k], i); keep(2 * k + 1, -b.min[k], i); }
    keep(6, Math.max(Math.hypot(b.max[0], b.max[2]), Math.hypot(b.min[0], b.min[2]), Math.hypot(b.max[0], b.min[2]), Math.hypot(b.min[0], b.max[2])), i);
  });
  for (const { i } of best) if (i >= 0) picked.add(i);
  const n = frames.length;
  const step = Math.max(1, n / Math.max(1, even));
  for (let x = 0; x < n; x += step) { const i = Math.floor(x); if (frames[i]) picked.add(i); }
  return [...picked].sort((a, b) => a - b);
}

/**
 * The NDC box {x0, x1, y0, y1} of `boxes` (each {min, max} relative to the slot) placed at `slot` [x, y, z], `project`
 * mapping a scene point to NDC [x, y]; `into` (the same shape) is grown and returned when given.
 */
export function projectBoxes(boxes, slot, project, into = null) {
  const r = into || { x0: Infinity, x1: -Infinity, y0: Infinity, y1: -Infinity };
  for (const b of boxes) {
    for (const x of [b.min[0], b.max[0]]) for (const y of [b.min[1], b.max[1]]) for (const z of [b.min[2], b.max[2]]) {
      const [px, py] = project(x + slot[0], y + slot[1], z + slot[2]);
      if (px < r.x0) r.x0 = px;
      if (px > r.x1) r.x1 = px;
      if (py < r.y0) r.y0 = py;
      if (py > r.y1) r.y1 = py;
    }
  }
  return r;
}
