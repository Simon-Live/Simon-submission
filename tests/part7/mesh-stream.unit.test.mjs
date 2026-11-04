// The streamed frames on the job page and the corrected-pose card (docs/specs/mesh-stream.md, muse-image-corrected.md).
//   node --test tests/part7/mesh-stream.unit.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { El, installDom, find } from "./fake-dom.mjs";

installDom();
const stream = await import("../../web/mesh-stream.js");
const card = await import("../../web/corrected-card.js");
const consent = await import("../../web/consent.js");

/** A manual clock: timers run when the test calls `run()`. */
function clock() {
  const queue = [];
  return {
    setTimer: (fn, ms) => { queue.push({ fn, ms }); return queue.length; },
    clearTimer: () => { queue.length = 0; },
    queue,
    async run() { const t = queue.shift(); if (t) await t.fn(); },
  };
}

/** A chunk of `n` blocks of 2 vertices each (int16 at 0.1 mm): vertex 0 at (10000 * k, 0, 0) and vertex 1 at (10000 * k, 20000, 0). */
const chunkBytes = (n) => {
  const a = new Int16Array(n * 6);
  for (let k = 0; k < n; k += 1) a.set([1000 * (k + 1), 0, 0, 1000 * (k + 1), 2000, 0], k * 6);
  return a.buffer;
};
const stream2 = (chunks, done, total = 5) => ({ closed: false, stream: { frames_done: done, frames_total: total, vertex_count: 2, block_bytes: 12,
  chunks: Array.from({ length: chunks }, (_, i) => `c${i}`) } });

test("decoding reads int16 vertices at 0.1 mm and refuses a chunk that does not match the manifest", () => {
  const blocks = stream.decodeChunk(chunkBytes(2), { vertex_count: 2, block_bytes: 12 });
  assert.equal(blocks.length, 2);
  assert.deepEqual(blocks[1].map((pt) => pt.map((v) => Math.round(v * 1e4) / 1e4)), [[0.2, 0, 0], [0.2, 0.2, 0]]);
  assert.deepEqual(stream.decodeChunk(chunkBytes(2), { vertex_count: 3, block_bytes: 12 }), [], "size does not match the vertex count");
  assert.deepEqual(stream.decodeChunk(new ArrayBuffer(13), { vertex_count: 2, block_bytes: 12 }), [], "a torn chunk");
  const many = stream.decodeBlock(new Int16Array(6000 * 3).buffer, 0, 6000);
  assert.ok(many.length <= stream.MAX_POINTS, "points are thinned");
});

test("the stream fetches each chunk once, in order, and stops when the server closes it", async () => {
  const c = clock();
  const asked = [];
  const drawn = [];
  let closed = 0;
  const replies = [{ closed: false, stream: null }, stream2(1, 1), stream2(3, 3), { closed: true, stream: null }];
  stream.createMeshStream({ url: "u", getSnapshot: async () => replies.shift(), getBytes: async (url) => { asked.push(url); return chunkBytes(1); },
    onBlocks: (b, s) => drawn.push([b.length, s.done, s.total]), onClosed: () => { closed += 1; }, ...c });
  for (let i = 0; i < 4; i += 1) await c.run();
  assert.deepEqual(asked, ["c0", "c1", "c2"]);
  assert.deepEqual(drawn, [[1, 1, 5], [1, 3, 5]]);
  assert.equal(closed, 1);
  assert.equal(c.queue.length, 0, "closed means no further poll");
});

test("401 and 404 end the stream quietly, 429 slows it, another failure retries at the normal pace", async () => {
  for (const [status, expected] of [[401, null], [404, null], [429, stream.SLOW_MS], [500, stream.POLL_MS]]) {
    const c = clock();
    stream.createMeshStream({ url: "u", getSnapshot: async () => { throw Object.assign(new Error("x"), { status }); }, getBytes: async () => new ArrayBuffer(0), onBlocks() {}, ...c });
    await c.run();
    assert.equal(c.queue.length ? c.queue[0].ms : null, expected, String(status));
  }
});

test("stop() ends the polling and a late reply draws nothing", async () => {
  const c = clock();
  let resolve;
  const got = [];
  const stop = stream.createMeshStream({ url: "u", getSnapshot: () => new Promise((r) => { resolve = r; }), getBytes: async () => chunkBytes(1), onBlocks: (b) => got.push(b), ...c });
  const pending = c.run();
  stop();
  resolve(stream2(1, 1));
  await pending;
  assert.deepEqual(got, []);
  assert.equal(c.queue.length, 0);
});

test("the panel names the model, counts frames and is removed when stopped", async () => {
  const c = clock();
  const root = new El("div");
  const stop = stream.mountMeshStream(root, { url: "u", model: "SAM 3D Body" },
    { getSnapshot: async () => stream2(1, 1, 90), getBytes: async () => chunkBytes(1), ...c });
  assert.match(find(root, "mesh-stream-model").textContent, /SAM 3D Body is rebuilding your body/);
  assert.equal(find(root, "mesh-stream-count").textContent, "Waiting for the first frame");
  await c.run();
  assert.equal(find(root, "mesh-stream-count").textContent, "Frame 1 of 90");
  stop();
  assert.equal(find(root, "mesh-stream"), null);
});

test("counter and fit are exact", () => {
  assert.equal(stream.counterText({ done: 4, total: null }), "Frame 4");
  assert.equal(stream.counterText({ done: 4, total: 9 }), "Frame 4 of 9");
  // Part 2 leaves frames_total null while the run goes on and sets it at the end (TICKET-284): never "of null" or NaN
  for (const total of [undefined, null, "null", Number.NaN, 0, -3, 2.5, 3]) assert.equal(stream.counterText({ done: 4, total }), "Frame 4", String(total));
  for (const done of [undefined, null, Number.NaN, "4", -1]) assert.equal(stream.counterText({ done, total: 9 }), null, String(done));
  assert.equal(stream.counterText({ done: 0, total: null }), "Frame 0");
  assert.deepEqual(stream.fit([[0, 0, 0], [2, 4, 0]], { x0: 0, x1: 2, y0: 0, y1: 4 }, 100, 100, 0), [[0, 100], [50, 0]]);
});

// ---- the corrected-pose card ------------------------------------------------------------------------------
const SHOWN = { status: "shown", label: "AI-generated illustration", image: "corrected-1.png", joint: "left_elbow", error_deg: 3.4, error_text: "Measured error: 3.4 degrees from the target pose." };
const READY = { eligible: true, consent: true, running: false, card: null, image: null, referee: null };
const shown = { ...READY, card: SHOWN, image: "api/jobs/j1/muse-fix/image" };

test("a picture that passed shows labelled as AI-generated with its measured error", async () => {
  const el = new El("section");
  await card.mountCorrectedCard(el, "j1", { api: { getMuseFix: async () => shown } });
  assert.equal(el.hidden, false);
  assert.equal(find(el, "corrected-label").textContent, "AI-generated illustration");
  assert.equal(find(el, "corrected-error").textContent, "Measured error: 3.4 degrees from the target pose.");
  assert.match(find(el, "corrected-image").getAttribute("alt"), /^AI-generated illustration/);
  assert.ok(find(el, "referee-ask"), "the referee is offered once there is a picture");
});

test("a miss shows only the plain sentence, no image and a try again", async () => {
  const el = new El("section");
  const missed = { ...READY, card: { status: "missed", message: "The image model missed the pose." } };
  await card.mountCorrectedCard(el, "j1", { api: { getMuseFix: async () => missed } });
  assert.equal(find(el, "corrected-missed").textContent, "The image model missed the pose.");
  assert.equal(find(el, "corrected-image"), null);
  assert.equal(find(el, "corrected-ask").textContent, "Try again");
});

test("a take with no fault to draw says so and offers no button", async () => {
  const el = new El("section");
  await card.mountCorrectedCard(el, "j1", { api: { getMuseFix: async () => ({ ...READY, can_draw: false }) } });
  assert.equal(find(el, "corrected-no-fault").textContent, card.NO_FAULT);
  assert.equal(find(el, "corrected-ask"), null);
});

test("a host that cannot check pictures says so, offers no button and the take is not called faultless", async () => {
  const el = new El("section");
  await card.mountCorrectedCard(el, "j1", { api: { getMuseFix: async () => ({ ...READY, can_draw: false, no_check: true }) } });
  assert.equal(find(el, "corrected-no-check").textContent, card.NO_CHECK);
  assert.equal(find(el, "corrected-no-fault"), null);
  assert.equal(find(el, "corrected-ask"), null);
});

test("a press that found nothing to draw leaves its line and no try again", async () => {
  const el = new El("section");
  const none = { ...READY, can_draw: true, card: { status: "not_available", message: "Simon could not find a moment to draw in this take. Nothing was sent." } };
  await card.mountCorrectedCard(el, "j1", { api: { getMuseFix: async () => none } });
  assert.match(find(el, "corrected-missed").textContent, /Nothing was sent/);
  assert.equal(find(el, "corrected-ask"), null);
});

test("negative: consent off, an ineligible take, or a failed read shows no card and sends nothing", async () => {
  for (const state of [{ ...READY, consent: false }, { ...READY, eligible: false }, null]) {
    const el = new El("section");
    const posts = [];
    await card.mountCorrectedCard(el, "j1", { api: { getMuseFix: async () => state, postMuseFix: async (...a) => posts.push(a) } });
    assert.equal(el.hidden, true);
    assert.equal(find(el, "corrected-ask"), null);
    assert.deepEqual(posts, []);
  }
  const el = new El("section");
  assert.equal(await card.mountCorrectedCard(el, "j1", { api: { getMuseFix: async () => { throw new Error("x"); } } }), null);
  assert.equal(el.hidden, true);
});

test("the ask button posts once, shows that it is working and polls until the picture is there", async () => {
  const el = new El("section");
  const c = clock();
  const posts = [];
  const replies = [READY, { ...READY, running: true }, shown];
  const api = { getMuseFix: async () => replies.shift() || shown, postMuseFix: async (job, what) => { posts.push([job, what]); return {}; } };
  await card.mountCorrectedCard(el, "j1", { api, ...c });
  find(el, "corrected-ask").click();
  find(el, "corrected-ask")?.click();
  await new Promise((r) => setTimeout(r, 0));
  assert.deepEqual(posts, [["j1", "image"]]);
  assert.ok(find(el, "corrected-running"));
  assert.equal(c.queue[0].ms, card.POLL_MS);
  await c.run();
  assert.ok(find(el, "corrected-image"));
});

test("a 403 on the ask says nothing was sent", async () => {
  const el = new El("section");
  const api = { getMuseFix: async () => READY, postMuseFix: async () => { throw Object.assign(new Error("x"), { status: 403 }); } };
  await card.mountCorrectedCard(el, "j1", { api });
  find(el, "corrected-ask").click();
  await new Promise((r) => setTimeout(r, 0));
  assert.match(find(el, "corrected-note").textContent, /Nothing was sent/);
});

test("the referee's verdict is the model's opinion, and the tally prints only with the badge", () => {
  const mine = { model: "muse-spark-1.3", picked_corrected: true };
  assert.equal(card.refereeText(mine, null), "Shown the trainer and both bodies in a random order, muse-spark-1.3 said the corrected picture moves more like the trainer.");
  assert.doesNotMatch(card.refereeText(mine, { badge: false, n: 5, k: 4, p: 0.19 }), /Across/);
  assert.match(card.refereeText(mine, { badge: true, n: 9, k: 8, p: 0.019531 }), /Across 9 takes it picked the corrected one 8 times \(chance alone: p = 0\.019531\)\./);
  assert.match(card.refereeText({ ...mine, picked_corrected: false }, null), /your original body/);
});

test("the referee card renders the verdict with the opinion tag", async () => {
  const el = new El("section");
  const state = { ...shown, referee: { mine: { model: "muse-spark-1.3", picked_corrected: true }, summary: { badge: false } } };
  await card.mountCorrectedCard(el, "j1", { api: { getMuseFix: async () => state } });
  assert.equal(find(el, "referee-opinion").textContent, card.OPINION);
  assert.match(find(el, "referee-verdict").textContent, /muse-spark-1\.3 said/);
  assert.equal(find(el, "referee-ask"), null);
});

test("the data note names the picture and the blind comparison, and who can run them", () => {
  const note = consent.NOTE.join(" ");
  assert.match(note, /one frame of your video and a grey figure of your body go to Meta's Muse Image/);
  assert.match(note, /three grey figures \(the trainer, you, and you corrected\) go to Muse Spark in a random order/);
  assert.match(note, /Both only run for you, only when you have allowed Meta's AI models to see your video, and never for a private take or a take kept for health work/);
  assert.match(note, /labelled as AI-generated, and the comparison as the model's opinion/);
});

test("the mounted counter shows the frame alone while frames_total is null, then the total once it is known", async () => {
  const c = clock();
  const root = new El("div");
  const replies = [stream2(1, 42, null), stream2(2, 43, undefined), stream2(3, null, null), stream2(4, 90, 90)];
  const stop = stream.mountMeshStream(root, { url: "u", model: "SAM 3D Body" },
    { getSnapshot: async () => replies.shift(), getBytes: async () => chunkBytes(1), ...c });
  const seen = [];
  for (let i = 0; i < 4; i += 1) { await c.run(); seen.push(find(root, "mesh-stream-count").textContent); }
  assert.deepEqual(seen, ["Frame 42", "Frame 43", "Frame 43", "Frame 90 of 90"]);
  for (const text of seen) assert.doesNotMatch(text, /null|NaN|undefined/);
  stop();
});
