// Heat on your own body (docs/specs/heat-and-ar.md, TICKET-274): the follower's per-vertex movement error, read from
// the job's heat.json + heat.bin and turned into colours and a "hottest region" readout. Pure functions, no DOM,
// so the unit tests run under node. The files are made by Part 2's side (the trainer's MHR pose put on the
// follower's own MHR shape, distance to the follower's real mesh), never by this module.
//
// Contract H1 (heat.json, format "part7.heat/1"):
//   { format, vertex_count, max_m, frames: [{t_ms}], bin: "heat.bin", bin_bytes, masked_labels?: [joint names] }
//   heat.bin: frames.length * vertex_count unsigned bytes, frame-major. A byte v is an error of v / 255 * max_m
//   metres, with body shape removed. Vertices of masked_labels (hands and feet, where the transfer drifts) hold 0
//   and are left out of the opening frame and the region readout. t_ms is on the follower's clock, as mesh3d.json is.

const FORMAT_PREFIX = "part7.heat/";

class HeatFormatError extends Error {}
const need = (ok, what) => { if (!ok) throw new HeatFormatError(what); };

/** {vertexCount, maxM, times, data, masked} from a heat header and bin; throws HeatFormatError when they disagree. */
export function parseHeat(header, buffer, vertexCount) {
  need(header && typeof header === "object" && String(header.format || "").startsWith(FORMAT_PREFIX), "format");
  need(header.vertex_count === vertexCount, "vertex count");
  need(Number.isFinite(header.max_m) && header.max_m > 0, "max_m");
  need(Array.isArray(header.frames) && header.frames.length > 0, "frames");
  need(header.frames.every((f) => f && Number.isFinite(f.t_ms)), "frame times");
  need(buffer instanceof ArrayBuffer && buffer.byteLength === header.frames.length * vertexCount && buffer.byteLength === header.bin_bytes, "bin size");
  const masked = Array.isArray(header.masked_labels) ? header.masked_labels.filter((n) => typeof n === "string") : [];
  return { vertexCount, maxM: header.max_m, times: header.frames.map((f) => f.t_ms / 1000), data: new Uint8Array(buffer), masked };
}

/** Fetch and parse the heat of a mesh with `vertexCount` vertices; null on any failure (the caller shows no Heat control). */
export async function loadHeat(url, vertexCount, fetchImpl = globalThis.fetch) {
  try {
    if (typeof url !== "string" || !url) return null;
    const res = await fetchImpl(url);
    if (!res.ok) return null;
    const header = await res.json();
    if (typeof header.bin !== "string" || header.bin.includes("/") || header.bin.includes("\\")) return null;
    const bin = await fetchImpl(new URL(header.bin, new URL(url, globalThis.location ? globalThis.location.href : undefined)).href);
    if (!bin.ok) return null;
    return parseHeat(header, await bin.arrayBuffer(), vertexCount);
  } catch {
    return null;
  }
}

/** {i0, i1, a} for the frames around t seconds, clamped to the ends. */
export function heatFrameAt(heat, t) {
  const f = heat.times;
  if (!(t > f[0])) return { i0: 0, i1: 0, a: 0 };
  if (t >= f[f.length - 1]) return { i0: f.length - 1, i1: f.length - 1, a: 0 };
  let lo = 0;
  let hi = f.length - 1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (f[mid] <= t) lo = mid; else hi = mid;
  }
  return { i0: lo, i1: hi, a: (t - f[lo]) / (f[hi] - f[lo]) };
}

/** Heat 0 to 1 per vertex at t seconds into `out` (Float32Array of vertexCount); returns out. */
export function heatAt(heat, t, out) {
  const { i0, i1, a } = heatFrameAt(heat, t);
  const n = heat.vertexCount;
  for (let i = 0; i < n; i++) {
    const v0 = heat.data[i0 * n + i];
    const v1 = heat.data[i1 * n + i];
    out[i] = (v0 + (v1 - v0) * a) / 255;
  }
  return out;
}

/** [r, g, b] (0 to 1 each) along the ramp `stops` (an array of [r, g, b], coolest first) at v in 0 to 1. */
export function rampAt(stops, v, out = [0, 0, 0]) {
  const x = Math.min(1, Math.max(0, Number.isFinite(v) ? v : 0)) * (stops.length - 1);
  const i = Math.min(stops.length - 2, Math.floor(x));
  const a = x - i;
  for (let k = 0; k < 3; k++) out[k] = stops[i][k] + (stops[i + 1][k] - stops[i][k]) * a;
  return out;
}

/** Mean heat (0 to 1) of each label at t: {names: [label name], means: Float32Array}. Masked labels read 0 and are skipped by callers. */
export function regionMeans(heat, mesh, t, scratch = new Float32Array(heat.vertexCount)) {
  heatAt(heat, t, scratch);
  const k = mesh.names.length;
  const sum = new Float64Array(k);
  const count = new Uint32Array(k);
  for (let i = 0; i < heat.vertexCount; i++) { sum[mesh.labels[i]] += scratch[i]; count[mesh.labels[i]] += 1; }
  return { names: mesh.names, means: Float32Array.from(sum, (s, j) => (count[j] ? s / count[j] : 0)) };
}

/** The hottest unmasked region at t: {name, value} (value is the mean heat 0 to 1), or null when every region is cold. */
export function hottestRegion(heat, mesh, t, scratch) {
  const { names, means } = regionMeans(heat, mesh, t, scratch);
  let best = null;
  names.forEach((name, j) => {
    if (heat.masked.includes(name)) return;
    if (means[j] > 0 && (!best || means[j] > best.value)) best = { name, value: means[j] };
  });
  return best;
}

export const NEAREST_S = 0.25;   // a fault time further than this from every drawn frame has no heat (part7/heat.py NEAREST_S)
export const TAIL_S = 0.5;       // the last half second of a take is where the alignment clamps (part7/heat.py TAIL_S)

/**
 * The follower time (seconds) after which the take is not aligned with the trainer, from replay.json: Part 5's
 * `aligned_until_s` when present (Part 5 1.14.0), else the follower time of the last frame any trainer frame maps to
 * (`follower_t[max(exp_to_fol)]`). Later frames are the idle tail Part 5 never compared. null when replay says neither.
 */
export function alignedUntil(replay) {
  if (!replay || typeof replay !== "object") return null;
  if (Number.isFinite(replay.aligned_until_s)) return replay.aligned_until_s;
  const map = replay.exp_to_fol;
  const times = replay.follower_t;
  if (!Array.isArray(map) || !map.length || !Array.isArray(times)) return null;
  const last = Math.max(...map);
  return Number.isFinite(times[last]) ? times[last] : null;
}

/** True when time t (seconds) is inside the aligned part of the take (always true with no cutoff). */
export const isAligned = (heat, t) => !Number.isFinite(heat.alignedUntil) || t <= heat.alignedUntil + 1e-6;

/** True for a frame that holds heat: the server writes a frame it could not score as a row of zeros. */
export const frameHasHeat = (heat, i) => {
  if (!isAligned(heat, heat.times[i])) return false;   // the idle tail is never paired with the trainer's last frame
  const n = heat.vertexCount;
  for (let k = i * n; k < (i + 1) * n; k++) if (heat.data[k] !== 0) return true;
  return false;
};

/**
 * Where the Heat view opens, as the server's heat.open_moment does (docs/specs/heat.md AC-H4): the frame nearest the lead
 * fault's time (`leadFaultAt`, seconds, the first fault of the analysis) when one is within NEAREST_S; otherwise the frame
 * with the most heat outside the last TAIL_S. {t, name, source: "fault"|"heat"}, or null when no frame holds heat.
 * `name` is the region that differs most in that frame. It is not a claim about the fault.
 */
export function openMoment(heat, mesh, leadFaultAt = null) {
  const scratch = new Float32Array(heat.vertexCount);
  const drawn = heat.times.map((t, i) => ({ t, i })).filter(({ i }) => frameHasHeat(heat, i));
  if (!drawn.length) return null;
  const pick = (f, source) => { const r = hottestRegion(heat, mesh, f.t, scratch); return r ? { t: f.t, name: r.name, value: r.value, source } : null; };
  if (Number.isFinite(leadFaultAt)) {
    const near = drawn.reduce((a, b) => (Math.abs(b.t - leadFaultAt) < Math.abs(a.t - leadFaultAt) ? b : a));
    if (Math.abs(near.t - leadFaultAt) <= NEAREST_S) {
      const at = pick(near, "fault");
      if (at) return at;
    }
  }
  const end = heat.times[heat.times.length - 1];
  let best = null;
  drawn.filter(({ t }) => t <= end - TAIL_S).forEach((f) => {
    const r = pick(f, "heat");
    if (r && (!best || r.value > best.value)) best = r;
  });
  return best;
}

/** "left_knee" as "left knee". */
export const regionLabel = (name) => String(name).replace(/_/g, " ");
