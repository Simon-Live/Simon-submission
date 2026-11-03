// Frame-stepped render hook for the cinematic video renders (docs/specs/cinematic-render.md, TICKET-267).
// Loaded only when the page URL carries ?cinematic=1 (web/flags.js isCinematic). It never reads the wall clock:
// a driver calls step(i) and the pose, the take time and the camera are pure functions of the frame index.
// The camera path is the simon.camera-path.v1 shape: keys [{t, position, target, fov_deg, ease, take_time?}].
export const SCHEMA = "simon.camera-path.v1";

const EASES = {
  linear: (k) => k,
  ease_in_out: (k) => k * k * (3 - 2 * k),
  ease_in: (k) => k * k,
  ease_out: (k) => 1 - (1 - k) * (1 - k),
};
const lerp = (a, b, k) => a + (b - a) * k;
const lerp3 = (a, b, k) => [lerp(a[0], b[0], k), lerp(a[1], b[1], k), lerp(a[2], b[2], k)];

/** Throws a plain Error naming the first thing wrong; returns the document when it is usable. */
export function validatePath(doc) {
  const bad = (why) => { throw new Error(`camera path: ${why}`); };
  if (!doc || doc.schema !== SCHEMA) bad(`schema must be ${SCHEMA}`);
  const keys = doc.keys;
  if (!Array.isArray(keys) || !keys.length) bad("keys must be a non-empty list");
  const vec = (v) => Array.isArray(v) && v.length === 3 && v.every(Number.isFinite);
  keys.forEach((k, i) => {
    if (!Number.isFinite(k.t)) bad(`key ${i} has no t`);
    if (i && !(k.t > keys[i - 1].t)) bad(`key ${i} t must rise`);
    if (!vec(k.position) || !vec(k.target)) bad(`key ${i} needs position and target as [x,y,z]`);
    if (!(k.fov_deg > 0 && k.fov_deg < 180)) bad(`key ${i} fov_deg`);
    if (k.take_time !== undefined && !(Number.isFinite(k.take_time) && k.take_time >= 0)) bad(`key ${i} take_time`);
    if (k.ease !== undefined && !EASES[k.ease]) bad(`key ${i} ease ${k.ease}`);
  });
  return doc;
}

/** The camera at render second t: {position, target, fov}. The ease of the key a segment starts at shapes that segment. */
export function cameraAt(doc, t) {
  const keys = doc.keys;
  const edge = (k) => ({ position: k.position.slice(), target: k.target.slice(), fov: k.fov_deg });
  if (t <= keys[0].t) return edge(keys[0]);
  const last = keys[keys.length - 1];
  if (t >= last.t) return edge(last);
  let i = 0;
  while (keys[i + 1].t <= t) i++;
  const a = keys[i], b = keys[i + 1];
  const k = EASES[a.ease || "linear"]((t - a.t) / (b.t - a.t));
  return { position: lerp3(a.position, b.position, k), target: lerp3(a.target, b.target, k), fov: lerp(a.fov_deg, b.fov_deg, k) };
}

/** Take seconds (the follower clock) at render second t. Each key may carry take_time; an absent one is start + t, where start is
 *  the first key's take_time (0 when absent), so a path with none plays the take in real time. Between keys it eases like the
 *  camera: equal values hold the take (bullet time), a smaller rise than t is slow motion. Clamped to the take's duration. */
export function takeTimeAt(doc, t, duration) {
  const keys = doc.keys;
  const start = Number.isFinite(keys[0].take_time) ? keys[0].take_time : 0;
  const at = (k) => (Number.isFinite(k.take_time) ? k.take_time : start + k.t);
  let s;
  if (t <= keys[0].t) s = at(keys[0]);
  else if (t >= keys[keys.length - 1].t) s = at(keys[keys.length - 1]);
  else {
    let i = 0;
    while (keys[i + 1].t <= t) i++;
    const a = keys[i], b = keys[i + 1];
    s = lerp(at(a), at(b), EASES[a.ease || "linear"]((t - a.t) / (b.t - a.t)));
  }
  return Math.min(duration, Math.max(0, s));
}

/** Render seconds of frame i at a fixed rate: integer arithmetic on the index, no clock. */
export const frameTime = (i, fps) => i / fps;
export const frameCount = (doc, fps) => Math.floor(doc.keys[doc.keys.length - 1].t * fps) + 1;

/** One pure frame state: what the take clock and camera are at frame i. */
export function frameState(doc, i, fps, duration) {
  const t = frameTime(i, fps);
  return { i, t, take_s: takeTimeAt(doc, t, duration), camera: cameraAt(doc, t) };
}

const FULL_FRAME_CSS = `
  body > *:not(.simon-cine-root) { visibility: hidden !important; }
  .simon-cine-root, .simon-cine-root * { visibility: visible; }
  .simon-cine-root { position: fixed !important; inset: 0 !important; margin: 0 !important; z-index: 99999; background: #10141c; }
  .simon-cine-root .sr-stage { position: fixed !important; inset: 0 !important; width: 100vw !important; height: 100vh !important; }
  .simon-cine-root .sr-bar, .simon-cine-root .sr-tools, .simon-cine-root .sr-legend { display: none !important; }`;

/** Install window.__cinematic on a mounted compare view (the api of compare.js mountCompare). */
export function installCinematic(compare, win = globalThis) {
  const doc = win.document;
  const style = doc.createElement("style");
  style.textContent = FULL_FRAME_CSS;
  doc.head.append(style);
  compare.el.classList.add("simon-cine-root");
  let path = null;
  let fps = 60;
  const api = {
    ready: true,
    /** Load the camera path and the rate; returns the frame count. */
    load(pathDoc, rate = 60) {
      path = validatePath(pathDoc);
      fps = rate;
      return frameCount(path, fps);
    },
    frames: () => (path ? frameCount(path, fps) : 0),
    /** Pose the take and the camera for frame i and draw it synchronously. Same i, same pixels. */
    step(i) {
      if (!path) throw new Error("cinematic: load a camera path first");
      const s = frameState(path, i, fps, compare.duration);
      compare.pause();
      compare.seek(s.take_s);
      compare.stage.setFreeCamera(s.camera);
      compare.stage.render();
      return s;
    },
  };
  win.__cinematic = api;
  return api;
}
