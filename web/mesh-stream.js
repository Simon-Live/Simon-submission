// The body being built, on the job page (docs/specs/mesh-stream.md, TICKET-284). `createMeshStream` polls the snapshot the
// way job.js polls the job, fetches each new chunk once and hands over decoded points; `mountMeshStream` draws them.
// The job answer names the stream (`mesh_stream`) only for the job's owner, so nobody else's page ever asks.
import { h } from "./ui.js";
import { getMeshStream, getMeshBytes } from "./api.js";

export const POLL_MS = 1000;
export const SLOW_MS = 4000;
export const MAX_POINTS = 600;   // drawn per person; the mesh has thousands of vertices
export const MAX_CHUNKS_PER_TICK = 24;
const UNIT_M = 1e-4;             // chunk vertices are int16 at 0.1 mm (Part 2 mesh3d stream)
const GONE = new Set([401, 404]);

/** Pure: every `step`-th vertex of a block (int16 x, y, z per vertex) as metres, at most MAX_POINTS of them. */
export function decodeBlock(buffer, offset, vertexCount) {
  const raw = new Int16Array(buffer, offset, vertexCount * 3);
  const step = Math.max(1, Math.ceil(vertexCount / MAX_POINTS));
  const out = [];
  for (let v = 0; v < vertexCount; v += step) out.push([raw[v * 3] * UNIT_M, raw[v * 3 + 1] * UNIT_M, raw[v * 3 + 2] * UNIT_M]);
  return out;
}

/** Pure: the blocks of one chunk as arrays of points; a chunk whose size does not match the manifest decodes to nothing. */
export function decodeChunk(buffer, stream) {
  const size = stream.block_bytes;
  if (!Number.isInteger(size) || size <= 0 || buffer.byteLength % size !== 0 || size !== stream.vertex_count * 6) return [];
  const blocks = [];
  for (let at = 0; at < buffer.byteLength; at += size) blocks.push(decodeBlock(buffer, at, stream.vertex_count));
  return blocks;
}

/**
 * Poll `getSnapshot(url)` until the server closes the stream, the job is gone, or `stop()` runs. New chunks are fetched
 * once each with `getBytes(url)`; `onBlocks(blocks, {done, total})` gets the newest chunk's blocks. A 429 slows the poll.
 */
export function createMeshStream({ url, getSnapshot, getBytes, onBlocks, onClosed = () => {}, setTimer = setTimeout, clearTimer = clearTimeout }) {
  let seen = 0;
  let timer = null;
  let stopped = false;

  function stop() {
    stopped = true;
    clearTimer(timer);
  }

  async function tick() {
    let wait = POLL_MS;
    try {
      const doc = await getSnapshot(url);
      if (stopped) return;
      if (doc.closed) { stop(); onClosed(); return; }
      const s = doc.stream;
      if (s && Array.isArray(s.chunks) && s.chunks.length > seen) {
        const last = Math.min(s.chunks.length, seen + MAX_CHUNKS_PER_TICK);
        let blocks = [];
        for (let i = seen; i < last; i += 1) blocks = decodeChunk(await getBytes(s.chunks[i]), s);
        if (stopped) return;
        seen = last;
        if (blocks.length) onBlocks(blocks, { done: s.frames_done, total: s.frames_total });
      }
    } catch (err) {
      if (stopped) return;
      if (err && GONE.has(err.status)) { stop(); return; }
      if (err && err.status === 429) wait = SLOW_MS;
    }
    if (!stopped) timer = setTimer(tick, wait);
  }

  timer = setTimer(tick, 0);
  return stop;
}

const count = (n) => (Number.isInteger(n) && n >= 0 ? n : null);

/**
 * The text above the canvas: `Frame 12 of 90`, or `Frame 12` while the run goes on (Part 2 sets `frames_total` only at
 * the end, null until then). Null when `done` is not a count, so the caller keeps the text it shows; never "of null" or NaN.
 */
export function counterText({ done, total }) {
  const d = count(done);
  if (d === null) return null;
  const t = count(total);
  return t && t >= d ? `Frame ${d} of ${t}` : `Frame ${d}`;
}

/** Pure: scale `points` into a `w` by `hgt` box with `box` (x0, x1, y0, y1) fixed across frames, y up. */
export function fit(points, box, w, hgt, pad = 8) {
  const scale = Math.min((w - 2 * pad) / ((box.x1 - box.x0) || 1), (hgt - 2 * pad) / ((box.y1 - box.y0) || 1));
  return points.map((p) => [pad + (p[0] - box.x0) * scale, hgt - pad - (p[1] - box.y0) * scale]);
}

const boxOf = (pts) => ({ x0: Math.min(...pts.map((p) => p[0])), x1: Math.max(...pts.map((p) => p[0])), y0: Math.min(...pts.map((p) => p[1])), y1: Math.max(...pts.map((p) => p[1])) });

/**
 * Mount the stream under `root`. Returns `stop()`, which ends the polling and removes the panel.
 * `info` is the job answer's `mesh_stream` ({url, model}); the fetchers are injectable for tests.
 */
export function mountMeshStream(root, info, { getSnapshot = getMeshStream, getBytes = getMeshBytes, ...timers } = {}) {
  const canvas = h("canvas", { width: 240, height: 320, role: "img", "aria-label": "The follower's body as it is rebuilt from the video, frame by frame", "data-testid": "mesh-stream-canvas" });
  const counter = h("p", { class: "meta tnum", "data-testid": "mesh-stream-count", text: "Waiting for the first frame" });
  const panel = h("section", { class: "mesh-stream", "data-testid": "mesh-stream" },
    h("p", { class: "hint", "data-testid": "mesh-stream-model", text: `${info.model || "SAM 3D Body"} is rebuilding your body from the video` }), canvas, counter);
  root.append(panel);
  let bounds = null;
  const ctx = canvas.getContext ? canvas.getContext("2d") : null;

  function draw(blocks) {
    const all = blocks.flat();
    if (!ctx || !all.length) return;
    bounds ||= boxOf(all);
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = "#3a6ea5";
    for (const block of blocks) for (const [x, y] of fit(block, bounds, canvas.width, canvas.height)) ctx.fillRect(x - 1, y - 1, 2, 2);
  }

  const stop = createMeshStream({
    url: info.url, getSnapshot, getBytes, ...timers,
    onBlocks: (blocks, state) => {
      draw(blocks);
      const text = counterText(state);
      if (text === null) return; // no frame count in this snapshot: the previous line stays
      counter.textContent = text;
      panel.setAttribute("data-frames", String(state.done));
    },
  });
  return () => { stop(); panel.remove(); };
}
