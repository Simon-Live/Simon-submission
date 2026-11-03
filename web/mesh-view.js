// SAM 3D Body mesh view (docs/specs/mesh-view.md, TICKET-143): the trainer's body as a translucent ghost and the
// follower's body solid, overlaid at the hips, on the compare clock, with the faulty limb tinted near each fault.
//
// Contract C6 (cross-lane, 2026-10-31). The result lane mounts it with one line:
//
//   const view = await mountMeshView(container, { trainerMeshUrl, followerMeshUrl, faults, fps });
//   // view: { setTime(t), destroy(), stats() } or null
//
//   trainerMeshUrl, followerMeshUrl  URL of each person's Part 2 `mesh3d.json` (`part2 run --mesh`); its
//                                    `mesh3d.bin` is fetched from beside it (the header's `bin` name).
//   faults    [{at_s, joints: [canonical joint names]}], the analysis' faults. The follower vertices labelled
//             with one of a fault's joints are tinted for TINT_WINDOW_S (0.5 s) either side of at_s.
//   fps       the compare clock's frame rate; used only to label stats (the mesh carries its own t_ms).
//   trainerTime (optional) t -> trainer seconds, when the compare maps the follower clock onto the trainer's.
//   fetch     (optional, tests) a fetch implementation.
//
//   Resolves null, never throws, when either mesh answers non-2xx or cannot be parsed, when a mesh holds no
//   person, or when WebGL is missing: the caller keeps its skeleton view. setTime(t) takes the follower time in
//   seconds and draws on the next animation frame. destroy() removes the canvas and frees the WebGL context.
//
// Colours come from CSS custom properties on the container (or an ancestor, for example web/theme/tokens.css):
//   --mesh-trainer (the ghost), --mesh-you (the follower), --mesh-fault (the tint), --mesh-light and --mesh-ground
//   (sky and ground light), --mesh-bg (clear colour; transparent when unset). FALLBACK_COLORS below is used for a property that is unset.
//
// Heat (TICKET-274, docs/specs/heat-and-ar.md): ctx.heatUrl, the URL of the job's heat.json. When it loads and matches the
// follower's mesh, the view also holds `view.heat` = {open: {t, name, value, source}, on, setOn(bool), onRegion(fn)} and paints
// the follower's body with the --heat-0 to --heat-4 ramp while on (the trainer's ghost is hidden then). With no heatUrl, a
// failed load, a mismatch or a take that is cold throughout, view.heat is null and the view is exactly what it was.
// ctx.alignedUntilS: after this follower time the take is unaligned (heat-data alignedUntil): no heat is painted and the listener gets {after: true}.
// ctx.leadFaultAt: the time of the analysis' first fault; `open.t` is the heat frame nearest it (the server's open_moment, docs/specs/heat.md).
//
// Part 7 reads only Part 2's output files (mesh3d.json + mesh3d.bin, Part 2 CONTRACT.md); it never imports Part 2.
// three.js is loaded lazily so the pure helpers below run under node for the unit tests.

import { FALLBACK_COLORS } from "./theme-fallbacks.js";
import { loadHeat, heatAt, rampAt, hottestRegion, openMoment, isAligned } from "./heat/heat-data.js"; // TICKET-274

export const TINT_WINDOW_S = 0.5;
export { FALLBACK_COLORS }; // the harness fallbacks live in theme-fallbacks.js

/** The value of a CSS custom property on `el` (inherited from its ancestors), else `fallback`. */
export function cssColor(el, name, fallback = FALLBACK_COLORS[name]) {
  try {
    const v = globalThis.getComputedStyle && el ? globalThis.getComputedStyle(el).getPropertyValue(name).trim() : "";
    return v || fallback;
  } catch {
    return fallback;
  }
}
const FORMAT_PREFIX = "part2.mesh3d/";

// ---- the Part 2 file ---------------------------------------------------------------------------

class MeshFormatError extends Error {}
const need = (ok, what) => { if (!ok) throw new MeshFormatError(what); };
const isInt = (v) => Number.isInteger(v) && v >= 0;

/** {vertexCount, faces, labels, names, unit, frames: [{t, block: Int16Array|null}], buffer} from a Part 2 header and
 *  its bin; throws MeshFormatError when they do not match. The first person of each frame is the one drawn. */
export function parseMesh(header, buffer) {
  need(header && typeof header === "object" && String(header.format || "").startsWith(FORMAT_PREFIX), "format");
  need(buffer instanceof ArrayBuffer && buffer.byteLength === header.bin_bytes, "bin size");
  const n = header.vertex_count;
  const k = header.face_count;
  need(isInt(n) && n >= 3 && isInt(k) && k >= 1, "counts");
  const wide = header.faces && header.faces.dtype === "uint32";
  need(header.faces && header.faces.offset === 0 && (wide || header.faces.dtype === "uint16"), "faces");
  const faceBytes = k * 3 * (wide ? 4 : 2);
  need(faceBytes <= buffer.byteLength, "faces size");
  const faces = wide ? new Uint32Array(buffer, 0, k * 3) : new Uint16Array(buffer, 0, k * 3);
  for (let i = 0; i < faces.length; i++) need(faces[i] < n, "face index");
  const vj = header.vertex_joint || {};
  need(Array.isArray(vj.names) && isInt(vj.offset) && vj.offset >= faceBytes && vj.offset + n <= buffer.byteLength, "vertex_joint");
  const labels = new Uint8Array(buffer, vj.offset, n);
  const unit = header.vertices && header.vertices.unit_m;
  need(header.vertices && header.vertices.dtype === "int16" && unit > 0, "vertices");
  need(Array.isArray(header.frames), "frames");
  const block = n * 3 * 2;
  const frames = header.frames.map((f) => {
    need(f && Number.isFinite(f.t_ms) && Array.isArray(f.people), "frame");
    const p = f.people[0];
    if (!p) return { t: f.t_ms / 1000, block: null };
    need(isInt(p.offset) && p.offset % 2 === 0 && p.offset >= vj.offset + n && p.offset + block <= buffer.byteLength, "offset");
    return { t: f.t_ms / 1000, block: new Int16Array(buffer, p.offset, n * 3) };
  });
  need(frames.some((f) => f.block), "no person");
  return { vertexCount: n, faces, labels, names: vj.names, unit, frames };
}

/** Fetch and parse one mesh; null on any failure (C6: the caller falls back to skeletons). */
export async function loadMesh(url, fetchImpl = globalThis.fetch) {
  try {
    const res = await fetchImpl(url);
    if (!res.ok) return null;
    const header = await res.json();
    if (typeof header.bin !== "string" || header.bin.includes("/") || header.bin.includes("\\")) return null;
    const base = new URL(url, globalThis.location ? globalThis.location.href : undefined);
    const bin = await fetchImpl(new URL(header.bin, base).href);
    if (!bin.ok) return null;
    return parseMesh(header, await bin.arrayBuffer());
  } catch {
    return null;
  }
}

const meshCaches = new WeakMap();
/**
 * loadMesh with a cache by fetch function and URL, so the result page's mesh view and the Person skin parse a mesh once
 * (docs/specs/person-skin.md). A failure is not remembered.
 */
export function cachedMesh(url, fetchImpl = globalThis.fetch) {
  let byUrl = meshCaches.get(fetchImpl);
  if (!byUrl) meshCaches.set(fetchImpl, (byUrl = new Map()));
  if (!byUrl.has(url)) {
    byUrl.set(url, loadMesh(url, fetchImpl).then((m) => { if (!m) byUrl.delete(url); return m; }));
  }
  return byUrl.get(url);
}

// ---- time --------------------------------------------------------------------------------------

/** {i0, i1, a}: the frames around t seconds and the weight of i1, clamped to the ends. */
export function frameAt(mesh, t) {
  const f = mesh.frames;
  if (!(t > f[0].t)) return { i0: 0, i1: 0, a: 0 };
  if (t >= f[f.length - 1].t) return { i0: f.length - 1, i1: f.length - 1, a: 0 };
  let lo = 0;
  let hi = f.length - 1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (f[mid].t <= t) lo = mid; else hi = mid;
  }
  const span = f[hi].t - f[lo].t;
  return { i0: lo, i1: hi, a: span > 0 ? (t - f[lo].t) / span : 0 };
}

const nearestWithPerson = (frames, i) => {
  for (let d = 0; d < frames.length; d++) {
    if (i - d >= 0 && frames[i - d].block) return frames[i - d].block;
    if (i + d < frames.length && frames[i + d].block) return frames[i + d].block;
  }
  return null;
};

/** Metres at t seconds into `out` (Float32Array of vertexCount * 3), interpolated; returns out. */
export function positionsAt(mesh, t, out) {
  const { i0, i1, a } = frameAt(mesh, t);
  const b0 = mesh.frames[i0].block || nearestWithPerson(mesh.frames, i0);
  const b1 = mesh.frames[i1].block || b0;
  const u = mesh.unit;
  for (let i = 0; i < out.length; i++) out[i] = (b0[i] + (b1[i] - b0[i]) * a) * u;
  return out;
}

// ---- tint --------------------------------------------------------------------------------------

/** The joint names of every fault whose window holds t. */
export function activeJoints(faults, t, windowS = TINT_WINDOW_S) {
  const out = new Set();
  for (const f of faults || []) {
    if (f && Number.isFinite(f.at_s) && Math.abs(t - f.at_s) <= windowS) for (const j of f.joints || []) out.add(j);
  }
  return out;
}

/** Uint8Array: 1 for each vertex labelled with one of `joints`. */
export function tintMask(mesh, joints) {
  const want = new Set();
  mesh.names.forEach((name, i) => { if (joints.has(name)) want.add(i); });
  const mask = new Uint8Array(mesh.vertexCount);
  for (let i = 0; i < mask.length; i++) mask[i] = want.has(mesh.labels[i]) ? 1 : 0;
  return mask;
}

// ---- WebGL -------------------------------------------------------------------------------------

function webglAvailable() {
  try {
    if (typeof document === "undefined") return false;
    const c = document.createElement("canvas");
    return !!(c.getContext("webgl2") || c.getContext("webgl"));
  } catch {
    return false;
  }
}

function bodyGeometry(THREE, mesh) {
  const g = new THREE.BufferGeometry();
  g.setIndex(new THREE.BufferAttribute(mesh.faces, 1));
  g.setAttribute("position", new THREE.BufferAttribute(new Float32Array(mesh.vertexCount * 3), 3));
  return g;
}

function paint(colors, mask, base, hot) {
  for (let i = 0; i < mask.length; i++) {
    const c = mask[i] ? hot : base;
    colors[i * 3] = c.r; colors[i * 3 + 1] = c.g; colors[i * 3 + 2] = c.b;
  }
}

/** TICKET-274: the follower's vertex colours from the heat at t; tells the region listener when the hottest region changes. */
function paintHeat(heat, follower, stops, state, colors, t, ghost) {
  if (!isAligned(heat, t)) {   // the idle tail after the movement: the body in its own colour, no heat
    for (let i = 0; i < state.level.length; i++) { colors.array[i * 3] = state.base.r; colors.array[i * 3 + 1] = state.base.g; colors.array[i * 3 + 2] = state.base.b; }
    colors.needsUpdate = true;
    ghost.visible = false;
    if (state.region !== "\u0000after") { state.region = "\u0000after"; if (state.listener) state.listener({ after: true }); }
    return;
  }
  heatAt(heat, t, state.level);
  for (let i = 0; i < state.level.length; i++) {
    rampAt(stops, state.level[i], state.rgb);
    colors.array[i * 3] = state.rgb[0]; colors.array[i * 3 + 1] = state.rgb[1]; colors.array[i * 3 + 2] = state.rgb[2];
  }
  colors.needsUpdate = true;
  ghost.visible = false;
  const hot = hottestRegion(heat, follower, t);
  const name = hot ? hot.name : "";
  if (name !== state.region) {
    state.region = name;
    if (state.listener) state.listener(hot);
  }
}

function buildScene(THREE, host, trainer, follower) {
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
  renderer.setPixelRatio(Math.min(globalThis.devicePixelRatio || 1, 2));
  const canvas = renderer.domElement;
  canvas.setAttribute("role", "img");
  canvas.setAttribute("aria-label", "3D bodies: the trainer as a see-through ghost over you, the limb that is off marked");
  canvas.style.width = "100%";
  canvas.style.height = "100%";
  canvas.style.display = "block";
  host.appendChild(canvas);
  const scene = new THREE.Scene();
  const light = new THREE.Color(cssColor(host, "--mesh-light"));
  scene.add(new THREE.HemisphereLight(light, new THREE.Color(cssColor(host, "--mesh-ground")), 1.6));
  const sun = new THREE.DirectionalLight(light, 1.4);
  sun.position.set(1.5, 2.5, 3);
  scene.add(sun);
  const camera = new THREE.PerspectiveCamera(35, 1, 0.05, 50);
  const bg = cssColor(host, "--mesh-bg", "");
  if (bg && bg !== "transparent") renderer.setClearColor(new THREE.Color(bg), 1);
  const ghost = new THREE.Mesh(bodyGeometry(THREE, trainer), new THREE.MeshStandardMaterial({
    color: new THREE.Color(cssColor(host, "--mesh-trainer")), transparent: true, opacity: 0.35, depthWrite: false, roughness: 0.8, side: THREE.DoubleSide,
  }));
  const fg = bodyGeometry(THREE, follower);
  fg.setAttribute("color", new THREE.BufferAttribute(new Float32Array(follower.vertexCount * 3), 3));
  const you = new THREE.Mesh(fg, new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.6, side: THREE.DoubleSide }));
  ghost.renderOrder = 1; // drawn after the solid body so the ghost blends over it
  scene.add(you, ghost);
  return { renderer, canvas, scene, camera, ghost, you };
}

/** Drag to turn around the bodies (azimuth only); returns a detach function. */
function orbit(canvas, view) {
  let x0 = null;
  const down = (e) => { x0 = e.clientX; canvas.setPointerCapture && canvas.setPointerCapture(e.pointerId); };
  const move = (e) => { if (x0 === null) return; view.azimuth += (e.clientX - x0) * 0.01; x0 = e.clientX; view.dirty(); };
  const up = () => { x0 = null; };
  canvas.addEventListener("pointerdown", down);
  canvas.addEventListener("pointermove", move);
  canvas.addEventListener("pointerup", up);
  canvas.addEventListener("pointercancel", up);
  return () => {
    canvas.removeEventListener("pointerdown", down);
    canvas.removeEventListener("pointermove", move);
    canvas.removeEventListener("pointerup", up);
    canvas.removeEventListener("pointercancel", up);
  };
}

/** Contract C6: see the top of this file. */
export async function mountMeshView(container, ctx = {}) {
  const fetchImpl = ctx.fetch || globalThis.fetch;
  const [trainer, follower] = await Promise.all([cachedMesh(ctx.trainerMeshUrl, fetchImpl), cachedMesh(ctx.followerMeshUrl, fetchImpl)]);
  if (!trainer || !follower || !container || !webglAvailable()) return null;
  let THREE;
  try {
    THREE = await import("./vendor/three/three.module.min.js");
  } catch {
    return null;
  }
  const s = buildScene(THREE, container, trainer, follower);
  const faults = Array.isArray(ctx.faults) ? ctx.faults : [];
  const trainerTime = typeof ctx.trainerTime === "function" ? ctx.trainerTime : (t) => t;
  const base = new THREE.Color(cssColor(container, "--mesh-you"));
  const hot = new THREE.Color(cssColor(container, "--mesh-fault"));
  const colors = s.you.geometry.getAttribute("color");
  let tintKey = null;
  let t = 0;
  let raf = 0;
  let frames = 0;
  const view = { azimuth: 0, dirty: () => schedule() };
  // TICKET-274: heat on the follower's body
  const heat = ctx.heatUrl ? await loadHeat(ctx.heatUrl, follower.vertexCount, fetchImpl) : null;
  if (heat) heat.alignedUntil = Number.isFinite(ctx.alignedUntilS) ? ctx.alignedUntilS : null;   // after it: no heat
  const heatStops = [0, 1, 2, 3, 4].map((k) => { const c = new THREE.Color(cssColor(container, `--heat-${k}`)); return [c.r, c.g, c.b]; });
  const heatState = { on: false, region: "", listener: null, level: new Float32Array(follower.vertexCount), rgb: [0, 0, 0], base };

  const draw = () => {
    raf = 0;
    const tp = s.ghost.geometry.getAttribute("position");
    const yp = s.you.geometry.getAttribute("position");
    positionsAt(trainer, trainerTime(t), tp.array);
    positionsAt(follower, t, yp.array);
    tp.needsUpdate = yp.needsUpdate = true;
    s.ghost.geometry.computeVertexNormals();
    s.you.geometry.computeVertexNormals();
    const joints = activeJoints(faults, t);
    const key = [...joints].sort().join(",");
    if (key !== tintKey) {
      paint(colors.array, tintMask(follower, joints), base, hot);
      colors.needsUpdate = true;
      tintKey = key;
    }
    if (heat && heatState.on) paintHeat(heat, follower, heatStops, heatState, colors, t, s.ghost);
    const r = 3.4;
    s.camera.position.set(Math.sin(view.azimuth) * r, 0.25, Math.cos(view.azimuth) * r);
    s.camera.lookAt(0, -0.05, 0);
    s.renderer.render(s.scene, s.camera);
    frames += 1;
  };
  const schedule = () => { if (!raf) raf = requestAnimationFrame(draw); };
  const resize = () => {
    const w = container.clientWidth || 1;
    const h = container.clientHeight || 1;
    s.renderer.setSize(w, h, false);
    s.camera.aspect = w / h;
    s.camera.updateProjectionMatrix();
    schedule();
  };
  const ro = typeof ResizeObserver === "function" ? new ResizeObserver(resize) : null;
  if (ro) ro.observe(container);
  const detach = orbit(s.canvas, view);
  resize();

  const open = heat ? openMoment(heat, follower, ctx.leadFaultAt) : null;
  return {
    heat: heat && open ? {
      open,
      get on() { return heatState.on; },
      setOn(on) {
        heatState.on = !!on;
        s.ghost.visible = !heatState.on;
        if (!heatState.on) { tintKey = null; heatState.region = ""; }
        schedule();
      },
      onRegion(fn) { heatState.listener = typeof fn === "function" ? fn : null; },
    } : null,
    setTime(next) {
      if (Number.isFinite(next)) { t = next; schedule(); }
    },
    stats() {
      return { frames, fps: ctx.fps ?? null, trainerVertices: trainer.vertexCount, followerVertices: follower.vertexCount,
        faces: follower.faces.length / 3, tinted: tintKey || "", heat: heatState.on ? heatState.region || "on" : "" };
    },
    destroy() {
      if (raf) cancelAnimationFrame(raf);
      if (ro) ro.disconnect();
      detach();
      s.ghost.geometry.dispose(); s.you.geometry.dispose();
      s.ghost.material.dispose(); s.you.material.dispose();
      s.renderer.dispose();
      s.canvas.remove();
    },
  };
}
