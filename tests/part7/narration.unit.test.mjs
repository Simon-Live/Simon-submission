// Unit tests for web/narration.js (TICKET-146).   node --test tests/part7/narration.unit.test.mjs
import test from "node:test";
import assert from "node:assert/strict";

import { installDom, all, findAll } from "./fake-dom.mjs";

installDom();
const { inSection, cuesFor, mountNarration, TEXT, MAX_PER_FAULT } = await import("../../web/narration.js");

const SECTIONS = [
  { index: 1, count: 2, start_ms: 0, end_ms: 5000 },
  { index: 2, count: 2, start_ms: 5000, end_ms: 10000 },
];
const cue = (i, start, text, sec, also = []) => ({ index: i, start_s: start, end_s: start + 1, text, section: SECTIONS[sec - 1], also_sections: also });
const DOC = {
  sections: SECTIONS,
  cues: [cue(0, 1.2, "Knees out and chest up.", 1), cue(1, 4.6, "Now push the floor away.", 1, [2]), cue(2, 7.6, "Slowly back down.", 2)],
};
const DASH = new RegExp(`[${String.fromCharCode(0x2013, 0x2014)}]| - `);

function page(...ats) {
  const root = document.createElement("div"), list = document.createElement("ol");
  root.append(list);
  ats.forEach((at, i) => {
    const li = document.createElement("li"), row = document.createElement("button");
    row.setAttribute("data-testid", `fault-${i}`);
    row.setAttribute("data-at-s", String(at));
    li.append(row);
    list.append(li);
  });
  const other = document.createElement("button");
  other.setAttribute("data-testid", "moment-chip-insight-0");
  other.setAttribute("data-at-s", "1");
  root.append(other);
  return root;
}
const notes = (root) => findAll(root, "narration-cue");

test("inSection: half open, the last section owns its end", () => {
  assert.ok(inSection(SECTIONS[0], 0));
  assert.ok(inSection(SECTIONS[0], 4.999));
  assert.ok(!inSection(SECTIONS[0], 5));
  assert.ok(inSection(SECTIONS[1], 5));
  assert.ok(inSection(SECTIONS[1], 10));
  assert.ok(!inSection(SECTIONS[1], 10.01));
  assert.ok(!inSection(SECTIONS[0], NaN));
  assert.ok(!inSection(null, 1));
});

test("cuesFor: the fault's section, and a phrase spanning two sections shows in both", () => {
  assert.deepEqual(cuesFor(DOC, 1.9).map((c) => c.index), [0, 1]);
  assert.deepEqual(cuesFor(DOC, 7).map((c) => c.index), [1, 2]);
});

test("cuesFor: nearest cues first, at most two, back in time order", () => {
  const many = { sections: SECTIONS, cues: [cue(0, 0.5, "a", 1), cue(1, 3.0, "b", 1), cue(2, 3.4, "c", 1), cue(3, 3.9, "d", 1)] };
  const got = cuesFor(many, 3.5);
  assert.equal(got.length, MAX_PER_FAULT);
  assert.deepEqual(got.map((c) => c.text), ["c", "d"]);
});

test("cuesFor: no cues, no sections, a time outside every section, malformed cues", () => {
  assert.deepEqual(cuesFor(null, 1), []);
  assert.deepEqual(cuesFor({ sections: SECTIONS, cues: [] }, 1), []);
  assert.deepEqual(cuesFor({ cues: DOC.cues }, 1), []);
  assert.deepEqual(cuesFor(DOC, 30), []);
  assert.deepEqual(cuesFor({ sections: SECTIONS, cues: [{ section: SECTIONS[0] }, null, { text: 3, start_s: 1, section: SECTIONS[0] }] }, 1), []);
});

test("mountNarration puts the words under the matching fault row only", async () => {
  const root = page(1.9, 8);
  const mounted = await mountNarration(root, { entryId: "squat", load: async () => DOC });
  assert.equal(mounted.count, 2);
  const lines = notes(root);
  assert.equal(lines.length, 4);
  const first = all(root).find((n) => n.attrs && n.attrs["data-testid"] === "fault-0-narration");
  assert.deepEqual(first.children.map((k) => k.textContent), [
    `${TEXT.said(1.2)}: “Knees out and chest up.”`,
    `${TEXT.said(4.6)}: “Now push the floor away.”`,
  ]);
  assert.ok(first.parentElement.tag === "li");
  // negative: the moment chip is not a fault row and gets nothing
  assert.equal(findAll(root, "moment-chip-insight-0-narration").length, 0);
});

test("mountNarration: a fault in a section nobody spoke in gets nothing", async () => {
  const doc = { sections: SECTIONS, cues: [cue(0, 1, "Only here.", 1)] };
  const root = page(8);
  const mounted = await mountNarration(root, { entryId: "squat", load: async () => doc });
  assert.equal(mounted.count, 0);
  assert.equal(notes(root).length, 0);
});

test("mountNarration: no narration, a failing load or a missing entry leaves the rows alone", async () => {
  for (const load of [async () => null, async () => ({ cues: [] }), async () => { throw new Error("down"); }]) {
    const root = page(1.9);
    assert.equal(await mountNarration(root, { entryId: "squat", load }), null);
    assert.equal(notes(root).length, 0);
  }
  assert.equal(await mountNarration(page(1), { load: async () => DOC }), null);
  assert.equal(await mountNarration(null, { entryId: "x" }), null);
});

test("mountNarration: the default load reads api/narration/<entry>; 404 and network errors mean nothing", async () => {
  const seen = [];
  globalThis.fetch = async (url) => { seen.push(url); return { ok: true, json: async () => DOC }; };
  const root = page(1.9);
  assert.equal((await mountNarration(root, { entryId: "a b" })).count, 1);
  assert.deepEqual(seen, ["api/narration/a%20b"]);
  globalThis.fetch = async () => ({ ok: false, status: 404 });
  assert.equal(await mountNarration(page(1.9), { entryId: "x" }), null);
  globalThis.fetch = async () => { throw new Error("offline"); };
  assert.equal(await mountNarration(page(1.9), { entryId: "x" }), null);
});

test("destroy removes what was added; no dash in the copy", async () => {
  const root = page(1.9);
  const mounted = await mountNarration(root, { entryId: "squat", load: async () => DOC });
  await mountNarration(page(1.9), { entryId: "squat", load: async () => DOC });
  mounted.destroy();
  assert.equal(notes(root).length, 0);
  assert.ok(!DASH.test(TEXT.said(1.2)));
});
