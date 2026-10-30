// Unit tests for the pure parts of the result experience: frame picking (AC-C1), clock (AC-C4, C6),
// replay validation (AC-C7), score bands (AC-A12, J9), fault fallback summary. Run: node --test tests/part7/
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { pickFrames, createClock, normalizeReplay, normalizeAnimation, MSG_BAD_REPLAY } from "../../web/compare.js";
import { BANDS, hasScore } from "../../web/score.js";
import { fallbackSummary, resultWarnings, withScore } from "../../web/result.js";

const load = (f) => JSON.parse(fs.readFileSync(new URL(`../../fixtures/input/${f}`, import.meta.url)));
const replay = load("replay.json");
const analysis = load("analysis-1.2.0.json");

test("AC-C1 follower frame is round(t*fps); expected frame is the largest e with exp_to_fol[e] <= f", () => {
  const m = normalizeReplay(replay);
  for (const t of [0, 0.5, 1.9, 2.95, 3.2]) {
    const { follower, expected } = pickFrames(t, m);
    assert.equal(follower, Math.min(m.follower.length - 1, Math.round(t * m.fps)));
    assert.ok(m.expToFol[expected] <= follower || expected === 0);
    if (expected + 1 < m.expToFol.length) assert.ok(m.expToFol[expected + 1] > follower);
  }
});

test("AC-C1 first expected frame when none maps at or below the follower frame", () => {
  const m = { kind: "compare", fps: 10, follower: [1, 2, 3, 4, 5], expToFol: [3, 4, 5] };
  assert.deepEqual(pickFrames(0.1, m), { follower: 1, expected: 0 });
  assert.deepEqual(pickFrames(0.4, m), { follower: 4, expected: 1 });
});

test("edge: follower longer than expected holds the last expected pose", () => {
  const m = { kind: "compare", fps: 10, follower: new Array(20).fill(0), expToFol: [0, 2, 4] };
  assert.equal(pickFrames(1.9, m).expected, 2);
  assert.equal(pickFrames(99, m).follower, 19);
});

test("AC-C4 seek sets the clock and leaves it paused; AC-C6 paused never moves", () => {
  let n = 0;
  const seen = [];
  const clock = createClock(3, (t, p) => seen.push([t, p]), () => n);
  clock.seek(1.9);
  assert.equal(clock.t, 1.9);
  assert.equal(clock.playing, false);
  n = 2000;
  assert.equal(clock.tick(), false);
  assert.equal(clock.t, 1.9);
});

test("clock plays in real time at 1x and stops at the end", () => {
  let n = 0;
  const clock = createClock(2, () => {}, () => n);
  clock.play();
  n = 500;
  assert.equal(clock.tick(), true);
  assert.ok(Math.abs(clock.t - 0.5) < 1e-9);
  n = 3000;
  assert.equal(clock.tick(), false);
  assert.equal(clock.t, 2);
  assert.equal(clock.playing, false);
  clock.play(); // at the end, play restarts
  assert.equal(clock.t, 0);
});

test("seek clamps to the take", () => {
  const clock = createClock(3, () => {});
  clock.seek(99);
  assert.equal(clock.t, 3);
  clock.seek(-4);
  assert.equal(clock.t, 0);
});

test("AC-C7 a bad replay is refused with the product message", () => {
  for (const bad of [null, {}, { ...replay, fps: 0 }, { ...replay, exp_to_fol: [1] }, { ...replay, bones: [[0, 99]] }, { ...replay, follower: [] }]) {
    assert.throws(() => normalizeReplay(bad), (e) => e.message === MSG_BAD_REPLAY);
  }
  const m = normalizeReplay(replay);
  assert.equal(m.joints.length, 17);
  assert.ok(Math.abs(m.duration - replay.follower_t.at(-1)) < 1e-9);
});

test("null joint positions are accepted (the bone is hidden by the stage)", () => {
  const r = structuredClone(replay);
  r.follower[3][5] = null;
  assert.doesNotThrow(() => normalizeReplay(r));
});

test("animation.json is normalised to one figure", () => {
  const anim = {
    fps: 30, joints: ["a", "b"], bones: [{ name: "x", parent: "a", child: "b" }],
    frames: [{ t: 0, joints: { a: [0, 0, 0], b: [0, 1, 0] } }, { t: 0.5, joints: { a: [0, 0, 0] } }],
  };
  const m = normalizeAnimation(anim);
  assert.deepEqual(m.bones, [[0, 1]]);
  assert.equal(m.frames[1][1], null);
  assert.equal(m.duration, 0.5);
  assert.throws(() => normalizeAnimation(null), (e) => e.message === "This movement has no 3D animation yet.");
});

test("AC-A12/J9 the fixture score is displayable and refusals carry none", () => {
  assert.equal(hasScore(analysis), true);
  assert.equal(hasScore({ score: null }), false);
  assert.deepEqual(BANDS.map((b) => b.grade), ["A", "B", "C", "D", "F"]);
  const band = BANDS.find((b) => b.grade === analysis.score.grade);
  assert.ok(band);
});

test("fallback summary counts rows with a fallback reason", () => {
  const a = structuredClone(analysis);
  assert.equal(fallbackSummary(a).count, 0);
  a.phrasing.faults[1].fallback_reason = "timeout";
  assert.deepEqual(fallbackSummary(a), { count: 1, total: 2, reasons: ["timeout"] });
  a.faults[0].phrasing = { fallback_reason: "timeout" };
  assert.equal(fallbackSummary(a).reasons.length, 1);
});

test("warnings: the list, an old-pin refusal read as one, no duplicates; a missing score is 0 and F", () => {
  assert.deepEqual(resultWarnings(analysis), []);
  const w = resultWarnings({ warnings: [{ code: "low_match", text: "Low." }, { code: "low_match", text: "again" }, { code: "no_person" }] });
  assert.deepEqual(w.map((x) => x.code), ["low_match", "no_person"]);
  assert.equal(w[0].text, "Low.");
  assert.match(w[1].text, /No person/);
  const old = resultWarnings({ status: { code: "different_movement", text: "Different." }, score: null });
  assert.deepEqual(old, [{ code: "different_movement", text: "Different." }]);
  assert.deepEqual(withScore({ score: null }).score, { value: 0, grade: "F", components: null });
  assert.equal(withScore(analysis), analysis);
});
