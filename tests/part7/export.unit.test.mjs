// Unit tests for web/export.js (export-clip.md AC-11) against a tiny fake DOM.   node --test tests/part7/export.unit.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { installDom, El, find } from "./fake-dom.mjs";

installDom();

const { mountExportButton, failureText, TEXT, POLL_MAX, POLL_MS } = await import("../../web/export.js");

const text = (el) => el.textContent;
const flush = () => new Promise((r) => setImmediate(r));

function rig(answers) {
  const calls = [];
  const timers = [];
  const queue = [...answers];
  const deps = {
    fetch: async (url, opts) => {
      calls.push([opts.method, url]);
      const a = queue.length > 1 ? queue.shift() : queue[0];
      if (a instanceof Error) throw a;
      return { status: a.status, json: async () => { if (a.badJson) throw new Error("x"); return a.body; } };
    },
    setTimeout: (fn, ms) => { timers.push({ fn, ms, live: true }); return timers.length - 1; },
    clearTimeout: (id) => { timers[id].live = false; },
  };
  return { calls, timers, deps };
}
const tick = async (r) => { const t = r.timers.filter((x) => x.live).pop(); t.live = false; await t.fn(); await flush(); };

test("the button posts, polls until ready, then shows the video and the download link", async () => {
  const r = rig([
    { status: 202, body: { ok: true, state: "queued" } },
    { status: 200, body: { ok: true, state: "rendering" } },
    { status: 200, body: { ok: true, state: "ready", url: "api/jobs/abc/export.mp4" } },
  ]);
  const box = new El("div");
  mountExportButton(box, "abc", r.deps);
  const btn = find(box, "export-start");
  assert.equal(text(btn), TEXT.make);
  btn.click();
  await flush();
  assert.deepEqual(r.calls[0], ["POST", "api/jobs/abc/export"]);
  assert.equal(text(find(box, "export-busy")), TEXT.busy);
  assert.equal(r.timers[0].ms, POLL_MS);
  await tick(r);
  assert.deepEqual(r.calls[1], ["GET", "api/jobs/abc/export"]);
  assert.ok(find(box, "export-busy"));
  await tick(r);
  const video = find(box, "export-video");
  assert.equal(video.attrs.src, "api/jobs/abc/export.mp4");
  assert.equal(video.attrs.playsinline, "");
  const link = find(box, "export-download");
  assert.equal(link.attrs.href, "api/jobs/abc/export.mp4");
  assert.equal(link.attrs.download, "simon-clip.mp4");
  assert.equal(find(box, "export-error"), null); // negative: no error shown
  assert.equal(r.timers.filter((t) => t.live).length, 0); // polling stopped
});

test("a ready clip on the first answer needs no polling", async () => {
  const r = rig([{ status: 200, body: { ok: true, state: "ready", url: "u.mp4" } }]);
  const box = new El("div");
  mountExportButton(box, "abc", r.deps);
  find(box, "export-start").click();
  await flush();
  assert.ok(find(box, "export-video"));
  assert.equal(r.timers.length, 0);
});

test("a refusal shows the server message and a retry that posts again", async () => {
  const r = rig([
    { status: 409, body: { ok: false, message: "This result is still being analysed." } },
    { status: 202, body: { state: "queued" } },
  ]);
  const box = new El("div");
  mountExportButton(box, "abc", r.deps);
  find(box, "export-start").click();
  await flush();
  assert.equal(text(find(box, "export-error")), "This result is still being analysed.");
  assert.equal(find(box, "export-video"), null);
  const retry = find(box, "export-start");
  assert.equal(text(retry), TEXT.retry);
  retry.click();
  await flush();
  assert.equal(r.calls.length, 2);
  assert.ok(find(box, "export-busy"));
});

test("a failed render shows its message", async () => {
  const r = rig([{ status: 202, body: { state: "queued" } }, { status: 200, body: { state: "failed", message: "The clip could not be made. Try again." } }]);
  const box = new El("div");
  mountExportButton(box, "abc", r.deps);
  find(box, "export-start").click();
  await flush();
  await tick(r);
  assert.equal(text(find(box, "export-error")), "The clip could not be made. Try again.");
});

test("network failure and unreadable answers fall back to the offline text", async () => {
  const r = rig([new Error("down")]);
  const box = new El("div");
  mountExportButton(box, "abc", r.deps);
  find(box, "export-start").click();
  await flush();
  assert.equal(text(find(box, "export-error")), TEXT.offline);
  assert.equal(failureText({ status: 500, body: null }), TEXT.offline);
  assert.equal(failureText({ status: 500, body: { message: "" } }), TEXT.offline);
  const bad = rig([{ status: 502, badJson: true }]);
  const box2 = new El("div");
  mountExportButton(box2, "abc", bad.deps);
  find(box2, "export-start").click();
  await flush();
  assert.equal(text(find(box2, "export-error")), TEXT.offline);
});

test("polling gives up after POLL_MAX and says so", async () => {
  const r = rig([{ status: 202, body: { state: "queued" } }, { status: 200, body: { state: "rendering" } }]);
  const box = new El("div");
  mountExportButton(box, "abc", r.deps);
  find(box, "export-start").click();
  await flush();
  for (let i = 0; i < POLL_MAX; i += 1) await tick(r);
  assert.equal(text(find(box, "export-error")), TEXT.stuck);
  assert.equal(r.timers.filter((t) => t.live).length, 0);
});

test("stop removes the button, cancels the timer and ignores a late answer", async () => {
  const r = rig([{ status: 202, body: { state: "queued" } }, { status: 200, body: { state: "ready", url: "u.mp4" } }]);
  const box = new El("div");
  const stop = mountExportButton(box, "abc", r.deps);
  find(box, "export-start").click();
  await flush();
  stop();
  assert.equal(r.timers[0].live, false);
  assert.equal(find(box, "export-clip"), null);
  await r.timers[0].fn(); // a poll that was already on its way
  await flush();
  assert.equal(r.calls.length, 1);
});

test("the result's mountExport stops the button and forgets the job, also when stopped before the module loaded", async () => {
  const { mountExport } = await import("../../web/views/result-slots.js");
  const early = new El("div");
  mountExport(early, "late-job")();   // stopped at once: the module is still loading
  await new Promise((r) => setTimeout(r, 30));
  assert.equal(find(early, "export-clip"), null, "negative: the button does not appear after the stop");
  const box = new El("div");
  const stop = mountExport(box, "late-job");
  await new Promise((r) => setTimeout(r, 30));
  assert.ok(find(box, "export-clip"), "the job was not left behind in the map: a fresh button mounts");
  stop();
  assert.equal(find(box, "export-clip"), null);
  const again = new El("div");
  mountExportButton(again, "late-job");
  assert.equal(again.children.length, 1, "after the stop the same job mounts a new button, not a moved one");
  assert.equal(box.children.length, 0);
});

const { nextView, exportUrl } = await import("../../web/model/export.js");

test("model: nextView maps answers to a view", () => {
  assert.deepEqual(nextView({ status: 200, body: { state: "ready", url: "u" } }), { view: "ready", url: "u" });
  for (const state of ["queued", "rendering", "none"]) assert.deepEqual(nextView({ status: 200, body: { state } }), { view: "busy" });
  assert.deepEqual(nextView({ status: 409, body: { message: "m" } }), { view: "error", message: "m" });
  assert.deepEqual(nextView({ status: 200, body: { state: "ready" } }), { view: "error", message: TEXT.offline }); // no url
  assert.equal(nextView(null).view, "error");
  assert.equal(exportUrl("x y"), "api/jobs/x%20y/export");
});

test("the job id is encoded in the URL", async () => {
  const r = rig([{ status: 202, body: { state: "queued" } }]);
  const box = new El("div");
  mountExportButton(box, "a/b", r.deps);
  find(box, "export-start").click();
  await flush();
  assert.equal(r.calls[0][1], "api/jobs/a%2Fb/export");
});

test("a second mount for the same job moves the one button: no double button, no second poll", async () => {
  const r = rig([{ status: 202, body: { state: "queued" } }, { status: 200, body: { state: "ready", url: "u.mp4" } }]);
  const first = new El("div");
  const stop = mountExportButton(first, "abc", r.deps);
  find(first, "export-start").click();
  await flush();
  const second = new El("div"); // the summary repainted and discarded the first slot
  const stop2 = mountExportButton(second, "abc", r.deps);
  assert.equal(stop2, stop);
  assert.equal(find(first, "export-clip"), null); // negative: the old slot is empty
  assert.equal(second.querySelectorAll('[data-testid="export-clip"]').length, 1);
  assert.ok(find(second, "export-busy")); // its state came along
  assert.equal(r.timers.filter((t) => t.live).length, 1); // one poll
  await tick(r);
  assert.ok(find(second, "export-video"));
  assert.equal(r.calls.length, 2);
  mountExportButton(second, "abc", r.deps); // the same slot again: nothing changes
  assert.equal(second.querySelectorAll('[data-testid="export-clip"]').length, 1);
});

test("after stop the same job mounts a fresh button; another job gets its own", async () => {
  const r = rig([{ status: 202, body: { state: "queued" } }]);
  const box = new El("div");
  const stop = mountExportButton(box, "abc", r.deps);
  const other = mountExportButton(box, "def", r.deps);
  assert.notEqual(other, stop);
  assert.equal(box.querySelectorAll('[data-testid="export-clip"]').length, 2);
  stop();
  const again = new El("div");
  mountExportButton(again, "abc", r.deps);
  assert.ok(find(again, "export-start"));
});
