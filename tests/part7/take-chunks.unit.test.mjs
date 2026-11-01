// TICKET-196: the take's Blob includes a final chunk delivered after `stop`.
import test from "node:test";
import assert from "node:assert/strict";
import { createChunks } from "../../web/take-chunks.js";

const chunk = (n) => ({ data: new Blob([new Uint8Array(n)]) });

test("a chunk delivered after stop but before the settle task is in the blob", () => {
  const queue = [];
  const c = createChunks({ later: (fn) => queue.push(fn) });
  c.add(chunk(100));
  c.add(chunk(50));
  let seen = null;
  c.whenSettled((parts) => { seen = c.blob("video/webm", parts); }); // onstop fired
  c.add(chunk(30)); // the last dataavailable arrives after onstop
  queue.forEach((fn) => fn());
  assert.equal(seen.size, 180);
  assert.equal(seen.type, "video/webm");
});

test("empty data is ignored and reset starts a new take", () => {
  const c = createChunks();
  c.add({ data: new Blob([]) });
  c.add({});
  c.add(null);
  assert.equal(c.count(), 0);
  c.add(chunk(5));
  c.reset();
  assert.equal(c.count(), 0);
});

test("the default scheduler settles on a later task", async () => {
  const c = createChunks();
  c.add(chunk(10));
  const got = await new Promise((resolve) => { c.whenSettled(resolve); c.add(chunk(7)); });
  assert.equal(got.length, 2);
});

test("a new take starting in the gap does not leak into the settled take (TICKET-202)", () => {
  const queue = [];
  const c = createChunks({ later: (fn) => queue.push(fn) });
  c.add(chunk(100));
  let seen = null;
  c.whenSettled((parts) => { seen = parts; }); // first take stops
  c.reset(); // a new recording starts before the settle task runs
  c.add(chunk(7));
  queue.forEach((fn) => fn());
  assert.deepEqual(seen.map((b) => b.size), [100], "only the first take's chunk");
  assert.equal(c.count(), 1, "the new take keeps its own chunk");
});
