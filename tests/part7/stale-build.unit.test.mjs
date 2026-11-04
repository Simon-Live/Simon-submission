// TICKET-493: a page left open across a release reloads at the next safe hash navigation, never with work at risk.
//   node --test tests/part7/stale-build.unit.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { createStaleGuard, hasEdits, MIN_GAP_MS } from "../../web/stale-build.js";

function rig({ safe = true } = {}) {
  const s = { sha: "aaa", reloads: 0, safe, t: 0, asked: 0 };
  const guard = createStaleGuard({
    getVersion: async () => { s.asked += 1; if (s.sha instanceof Error) throw s.sha; return { sha: s.sha }; },
    isSafe: () => s.safe, reload: () => { s.reloads += 1; }, now: () => s.t });
  return { s, guard };
}

test("the same build never reloads", async () => {
  const { s, guard } = rig();
  await guard.check();
  s.t += MIN_GAP_MS;
  assert.equal(guard.navigate(), false);
  await guard.check();
  assert.equal(guard.navigate(), false);
  assert.equal(s.reloads, 0);
});

test("a new build reloads at the next safe navigation, not before it", async () => {
  const { s, guard } = rig();
  await guard.check();
  s.sha = "bbb";
  await guard.check();
  assert.equal(s.reloads, 0, "knowing is not reloading: nothing moves until the person navigates");
  assert.equal(guard.navigate(), true);
  assert.equal(s.reloads, 1);
});

test("a new build does not reload during a take, an upload or unsaved work, then does once it is safe", async () => {
  const { s, guard } = rig({ safe: false });
  await guard.check();
  s.sha = "bbb";
  await guard.check();
  assert.equal(guard.navigate(), false);
  assert.equal(guard.navigate(), false);
  assert.equal(s.reloads, 0);
  s.safe = true;
  assert.equal(guard.navigate(), true);
});

test("an unknown sha, a failed check or no answer never makes a reload", async () => {
  const { s, guard } = rig();
  await guard.check();
  for (const next of ["unknown", "", new Error("offline")]) {
    s.sha = next;
    await guard.check();
    assert.equal(guard.navigate(), false);
  }
  assert.equal(s.reloads, 0);
});

test("navigation asks the server at most once a minute", async () => {
  const { s, guard } = rig();
  await guard.check();
  const first = s.asked;
  guard.navigate();
  guard.navigate();
  assert.equal(s.asked, first, "just checked");
  s.t += MIN_GAP_MS;
  guard.navigate();
  assert.equal(s.asked, first + 1);
});

test("a change back to the loaded build clears the wish to reload", async () => {
  const { s, guard } = rig();
  await guard.check();
  s.sha = "bbb";
  await guard.check();
  s.sha = "aaa";
  await guard.check();
  assert.equal(guard.navigate(), false);
});

const field = (o) => ({ tagName: "INPUT", type: "text", value: "", defaultValue: "", ...o });
const page = (...fields) => ({ querySelectorAll: () => fields });

test("hasEdits sees typed text, a chosen option, a ticked box and a chosen file, and ignores untouched controls", () => {
  assert.equal(hasEdits(page(field({ value: "Armour" }))), true);
  assert.equal(hasEdits(page(field({ type: "checkbox", checked: true, defaultChecked: false }))), true);
  assert.equal(hasEdits(page(field({ type: "file", files: [{}] }))), true);
  assert.equal(hasEdits(page({ tagName: "SELECT", type: "select-one", options: [{ selected: true, defaultSelected: false }] })), true);
  assert.equal(hasEdits(page(field({}), field({ type: "hidden", value: "x" }), field({ type: "checkbox", checked: false, defaultChecked: false }),
    field({ type: "file", files: [] }), { tagName: "SELECT", type: "select-one", options: [{ selected: true, defaultSelected: true }] })), false);
});
