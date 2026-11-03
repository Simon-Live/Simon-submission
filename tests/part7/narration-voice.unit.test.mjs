// The trainer's own recording next to a fault (TICKET-270).   node --test tests/part7/narration-voice.unit.test.mjs
import test from "node:test";
import assert from "node:assert/strict";

import { installDom, find, findAll } from "./fake-dom.mjs";

installDom();
const { mountNarration } = await import("../../web/narration.js");
const { clipUrl, whoSaid } = await import("../../web/model/narration.js");

const SECTIONS = [
  { index: 1, count: 2, start_ms: 0, end_ms: 5000 },
  { index: 2, count: 2, start_ms: 5000, end_ms: 10000 },
];
const cue = (i, start, text, sec) => ({ index: i, start_s: start, end_s: start + 1, text, section: SECTIONS[sec - 1], also_sections: [] });
const VOICED = {
  sections: SECTIONS,
  cues: [{ ...cue(0, 1.2, "Knees out and chest up.", 1), clip: { file: "cue-0.wav", ms: 1000 } }, cue(1, 7.6, "Slowly back down.", 2)],
};
const DASH = new RegExp(`[${String.fromCharCode(0x2013, 0x2014)}]| - `);

function page(...ats) {
  const root = document.createElement("div");
  ats.forEach((at, i) => {
    const row = document.createElement("button");
    row.setAttribute("data-testid", `fault-${i}`);
    row.setAttribute("data-at-s", String(at));
    root.append(row);
  });
  return root;
}

test("a cue with a clip gets a play button and a caption naming who spoke", async () => {
  const root = page(1.9);
  const played = [];
  await mountNarration(root, { entryId: "squat", trainer: "Dana", load: async () => VOICED, play: (u) => played.push(u) });
  assert.equal(findAll(root, "narration-play").length, 1);
  assert.equal(find(root, "narration-who").textContent, "Dana, in their own voice");
  find(root, "narration-play").click();
  assert.deepEqual(played, ["api/narration/squat/cue-0.wav"]);
});

test("the caption says The trainer when no name is credited", async () => {
  const root = page(1.9);
  await mountNarration(root, { entryId: "squat", trainer: "  ", load: async () => VOICED, play: () => {} });
  assert.equal(find(root, "narration-who").textContent, "The trainer, in their own voice");
});

test("negative: a section with no clip never plays another section's clip", async () => {
  const root = page(8);
  await mountNarration(root, { entryId: "squat", load: async () => VOICED, play: () => assert.fail("played") });
  assert.equal(findAll(root, "narration-cue").length, 1);
  assert.equal(findAll(root, "narration-play").length, 0);
  assert.equal(findAll(root, "narration-who").length, 0);
});

test("negative: a fault with no speech in its section shows nothing", async () => {
  const doc = { sections: SECTIONS, cues: [VOICED.cues[0]] };
  const root = page(8);
  const mounted = await mountNarration(root, { entryId: "squat", load: async () => doc, play: () => {} });
  assert.equal(mounted.count, 0);
  assert.equal(findAll(root, "narration-cue").length, 0);
});

test("clipUrl accepts only a plain cue file name", () => {
  assert.equal(clipUrl("squat", { clip: { file: "cue-3.wav" } }), "api/narration/squat/cue-3.wav");
  for (const file of ["x/cue-3.wav", "cue-3.mp3", "cue-3.wav/x", "", 4, null]) assert.equal(clipUrl("squat", { clip: { file } }), null);
  assert.equal(clipUrl("squat", { text: "x" }), null);
  assert.ok(!DASH.test(whoSaid(null)));
});
