// Release 16: the places a rep row's sentence shows besides the row (docs/specs/result-release-16.md AC-R16-1a). A miss the model
// worded (`ai`, set by withModelFlags before any display rewrite) never reaches a caption, a pop label, a moment label or a drift
// mark name as the model's sentence. Run: node --test tests/part7/ai-surfaces.unit.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { withModelFlags } from "../../web/model/fault-line.js";
import { cueAt } from "../../web/model/result-stage.js";
import { popsOf } from "../../web/model/score-pops.js";
import { momentsToReview } from "../../web/coaching.js";
import { driftOf } from "../../web/model/result-summary.js";

const real = JSON.parse(fs.readFileSync(new URL("../../fixtures/input/analysis-real-j7.json", import.meta.url)));
const flagged = withModelFlags(real);
const sentences = real.phrasing.faults.map((f) => f.text);
const lone = (miss) => ({ score: { value: 60, timeline: [{ t_s: [0, 5], value: 60, compared: true, misses: [miss] }] } });

test("the real j7 take: every rep row is flagged, and the raw take is not changed", () => {
  const misses = flagged.score.timeline.flatMap((w) => w.misses);
  assert.equal(misses.length, 7);
  assert.ok(misses.every((m) => m.ai === true));
  assert.ok(real.score.timeline.flatMap((w) => w.misses).every((m) => m.ai === undefined));
});

test("score pops: the word names the body part from the sentence as before, the label is the fixed cue", () => {
  const was = popsOf(real).filter((p) => p.kind === "miss");
  const now = popsOf(flagged).filter((p) => p.kind === "miss");
  assert.deepEqual(now.map((p) => p.text), was.map((p) => p.text), "the on-screen words are the ones the owner's rule gave");
  for (const w of ["Head", "Torso", "Elbows", "Left thigh"]) assert.ok(now.some((p) => p.text === w), `${w} stays`);
  assert.ok(!now.some((p) => p.text === "Back"), "Pull your head back does not become Back");
  for (const p of now) assert.ok(!sentences.some((s) => p.label.includes(s.replace(/\.$/, ""))) && !/ at \d/.test(p.label), `label ${p.label} holds no model sentence`);
  assert.ok(was.some((p) => /your|Your|Around/.test(p.label)), "the unflagged take shows the sentence, so the test can tell");
});

test("stage caption fallback: a model-worded miss shows its fixed cue, else nothing; a fixed miss keeps its text", () => {
  const miss = { text: "Your elbows are bent much more than the example at 1.0 s.", cue: "Straighten your arms more", at_s: 1 };
  assert.equal(cueAt(lone({ ...miss, ai: true }), 1).text, "Straighten your arms more");
  assert.equal(cueAt(lone({ ...miss, cue: undefined, ai: true }), 1), null);
  assert.equal(cueAt(lone({ ...miss, text: "elbows bent much more than the example at 1.0 s" }), 1).text, "Elbows bent much more than the example at 1.0 s");
});

test("moments to review: a model-worded miss is named by its cue, or neutrally, never by the sentence", () => {
  const big = (m) => ({ score: { value: 80, timeline: [{ t_s: [0, 5], value: 80, compared: true, misses: [{ at_s: 2, points: 20, ...m }] }] } });
  const text = "Your elbows are bent much more than the example at 2.0 s.";
  assert.match(momentsToReview(big({ text, cue: "Straighten your arms more", ai: true })).find((m) => m.kind === "miss").label, /Straighten your arms more/);
  const bare = momentsToReview(big({ text, ai: true })).find((m) => m.kind === "miss").label;
  assert.ok(!bare.includes("elbows") && /a miss/.test(bare));
  assert.match(momentsToReview(big({ text: "elbows bent", ai: false })).find((m) => m.kind === "miss").label, /elbows bent/);
});

test("drift marks carry the flag and the cue, so the view names a mark by the cue", () => {
  const marks = driftOf(flagged).marks;
  assert.equal(marks.length, 7);
  assert.ok(marks.every((x) => x.ai === true && x.cue));
  assert.ok(driftOf(real).marks.every((x) => x.ai === false));
});
