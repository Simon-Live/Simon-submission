// "Fix it for me" (docs/specs/fix-it-for-me.md, TICKET-265), the pure part and the panel. AC-1 to AC-5.
//   node --test tests/part7/fix-it.unit.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { installDom, find, findAll } from "./fake-dom.mjs";
import { normalizeReplay, pickFrames } from "../../web/compare.js";
import * as fx from "../../web/model/fix-it.js";

const read = (p) => JSON.parse(fs.readFileSync(new URL(`../../fixtures/input/${p}`, import.meta.url), "utf8"));
const replay = read("replay.json");
const analysis = read("analysis-1.2.0.json");
const model = normalizeReplay(replay);
const index = new Map(model.joints.map((n, i) => [n, i]));
const faults = fx.fixableFaults(analysis, model, pickFrames);
const elbow = faults.find((f) => f.limbs[0] === "left arm");
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
const framesAt = (t) => { const p = pickFrames(t, model); return { own: model.follower[p.follower], trainer: model.expected[p.expected] }; };

test("AC-1 chains: an elbow fault is that arm, a hip fault that leg, a torso fault nothing", () => {
  assert.deepEqual(fx.chainsOf({ joints: ["left_elbow"] }).map((c) => c.joints), [["left_shoulder", "left_elbow", "left_wrist"]]);
  assert.deepEqual(fx.chainsOf({ joints: ["right_knee"] }).map((c) => c.joints), [["right_hip", "right_knee", "right_ankle"]]);
  assert.deepEqual(fx.chainsOf({ joints: ["left_shoulder", "right_shoulder"] }).map((c) => c.key), ["left_arm", "right_arm"]);
  assert.deepEqual(fx.chainsOf({ joints: ["left_elbow", "left_wrist"] }).map((c) => c.key), ["left_arm"], "one chain per limb");
  assert.deepEqual(fx.chainsOf({ joints: ["left_shoulder", "right_shoulder"], body_part: "torso" }), [], "a trunk lean names the shoulders but is not an arm fault");
  assert.deepEqual(fx.chainsOf({ joints: ["nose", "spine", "left_eye"] }), []);
  assert.deepEqual(fx.chainsOf(null), []);
  assert.deepEqual(fx.limbNames(fx.chainsOf({ joints: ["left_elbow", "right_knee"] })), ["left arm", "right leg"]);
});

test("AC-1 window: Part 5's follower_t_s, widened to hold at_s; null without a time", () => {
  assert.deepEqual(fx.windowOf({ follower_t_s: [0.533, 2.867], at_s: 0.5 }), { start: 0.5, end: 2.867, at: 0.5 });
  assert.deepEqual(fx.windowOf({ follower_t_s: [1, 2], at_s: 1.5 }), { start: 1, end: 2, at: 1.5 });
  assert.deepEqual(fx.windowOf({ at_s: 2 }), { start: 2, end: 2, at: 2 });
  assert.equal(fx.windowOf({ follower_t_s: [1] }), null);
  assert.equal(fx.windowOf({}), null);
});

test("AC-1 weight: 1 in the window, eased over 0.3 s each side, 0 beyond, monotonic", () => {
  const win = { start: 1, end: 2, at: 1.5 };
  assert.equal(fx.blendWeight(1, win), 1);
  assert.equal(fx.blendWeight(1.5, win), 1);
  assert.equal(fx.blendWeight(2, win), 1);
  assert.equal(fx.blendWeight(0.7, win), 0);
  assert.equal(fx.blendWeight(2.3, win), 0);
  assert.equal(fx.blendWeight(0, win), 0);
  assert.equal(fx.blendWeight(NaN, win), 0);
  assert.equal(fx.blendWeight(1.5, null), 0);
  assert.ok(Math.abs(fx.blendWeight(0.85, win) - 0.5) < 1e-9, "half way up the ease is half");
  let last = 0;
  for (let t = 0.7; t <= 1; t += 0.01) { const w = fx.blendWeight(t, win); assert.ok(w >= last - 1e-12); last = w; }
  assert.deepEqual(fx.touchedSpan(win), { start: 0.7, end: 2.3 });
});

test("AC-1 the fixture: the faults the button acts on, with their limbs, labels and gaps", () => {
  assert.equal(faults.length, 2);
  assert.deepEqual(faults.map((f) => f.limbs), [["left arm"], ["right leg"]]);
  assert.equal(elbow.label, "Your take, with the left arm moved toward the trainer's pose");
  for (const f of faults) assert.ok(f.peak.gap >= fx.MIN_MOVED_DEG && f.peak.gap >= f.gap, `peak ${f.peak.gap} gap ${f.gap}`);
  for (const f of faults) assert.ok(f.peak.at >= f.win.start && f.peak.at <= f.win.end + 1e-9, "the peak is inside the window");
});

test("AC-1 at the fault, the chain is within 5 degrees of the trainer's aligned frame and every other joint is unchanged", () => {
  for (const [f, when] of faults.flatMap((x) => [[x, x.at], [x, x.peak.at]])) {
    const { own, trainer } = framesAt(when);
    const w = fx.blendWeight(when, f.win);
    assert.equal(w, 1);
    const shown = fx.correctPose(own, trainer, index, f.chains, w);
    const r = fx.report(own, shown, trainer, index, f.chains);
    assert.ok(r.toward <= 5, `${f.limbs}: ${r.toward} degrees left to the trainer`);
    assert.ok(r.moved >= fx.MIN_MOVED_DEG, "and it did move");
    assert.equal(r.outside, 0, "joints outside the chain have a max delta of 0");
    const inChain = new Set(f.chains.flatMap((c) => c.joints.slice(1)));
    model.joints.forEach((n, i) => { if (!inChain.has(n)) assert.deepEqual(shown[i], own[i], `${n} unchanged`); });
  }
});

test("AC-1 the correction keeps the student's own bone lengths", () => {
  const { own, trainer } = framesAt(elbow.at);
  const shown = fx.correctPose(own, trainer, index, elbow.chains, 1);
  const len = (p, a, b) => Math.hypot(...[0, 1, 2].map((i) => p[index.get(b)][i] - p[index.get(a)][i]));
  for (const [a, b] of fx.bonesOf(elbow.chains)) assert.ok(Math.abs(len(shown, a, b) - len(own, a, b)) < 1e-9, `${a}-${b}`);
});

test("AC-2 outside the eased window the corrected pose is the take's own, joint for joint", () => {
  const span = fx.touchedSpan(elbow.win);
  let checked = 0;
  for (let t = 0; t < model.duration; t += 1 / model.fps) {
    const { own, trainer } = framesAt(t);
    const shown = fx.correctPose(own, trainer, index, elbow.chains, fx.blendWeight(t, elbow.win));
    if (t < span.start - 1e-9 || t > span.end + 1e-9) { assert.ok(same(shown, own), `t=${t.toFixed(3)} is not the take's own`); checked++; }
  }
  assert.ok(checked > 3, `${checked} frames outside the window checked`);
});

test("AC-2 inside the ease the limb is part of the way: strictly between the take and the trainer", () => {
  const t = elbow.win.start - fx.EASE_S / 2;
  const { own, trainer } = framesAt(t);
  const w = fx.blendWeight(t, elbow.win);
  assert.ok(w > 0.4 && w < 0.6);
  const before = fx.report(own, own, trainer, index, elbow.chains).toward;
  const mid = fx.report(own, fx.correctPose(own, trainer, index, elbow.chains, w), trainer, index, elbow.chains).toward;
  assert.ok(mid < before && mid > 0, `${mid} between 0 and ${before}`);
});

test("AC-2 the blend never changes its inputs (nor, so, any score)", () => {
  const { own, trainer } = framesAt(elbow.at);
  const a = structuredClone(own), b = structuredClone(trainer);
  const scoreBefore = JSON.stringify(analysis.score);
  fx.correctPose(own, trainer, index, elbow.chains, 1);
  assert.deepEqual(own, a);
  assert.deepEqual(trainer, b);
  assert.equal(JSON.stringify(analysis.score), scoreBefore);
});

test("AC-2 a joint the student or the trainer did not show rides with its parent and is not turned", () => {
  const { own, trainer } = framesAt(elbow.at);
  const cut = structuredClone(trainer);
  cut[index.get("left_wrist")] = null;
  const shown = fx.correctPose(own, cut, index, elbow.chains, 1);
  const el = index.get("left_elbow"), wr = index.get("left_wrist");
  const shift = [0, 1, 2].map((i) => shown[el][i] - own[el][i]);
  assert.ok([0, 1, 2].every((i) => Math.abs(shown[wr][i] - own[wr][i] - shift[i]) < 1e-9), "the wrist keeps its offset from the elbow");
  const none = structuredClone(own);
  none[index.get("left_elbow")] = null;
  const kept = fx.correctPose(none, trainer, index, elbow.chains, 1);
  assert.deepEqual(kept[index.get("left_wrist")], own[index.get("left_wrist")], "no elbow, nothing to turn");
  assert.deepEqual(fx.correctPose(own, null, index, elbow.chains, 1), own, "no trainer frame, no change");
  assert.deepEqual(fx.correctPose(own, trainer, index, elbow.chains, 0), own, "weight 0, no change");
});

test("slerp and angleDeg: half way is half the angle, opposite vectors turn through a perpendicular", () => {
  const a = [1, 0, 0], b = [0, 1, 0];
  const m = fx.slerp(a, b, 0.5);
  assert.ok(Math.abs(fx.angleDeg(a, m) - 45) < 1e-9);
  assert.ok(Math.abs(Math.hypot(...m) - 1) < 1e-9);
  assert.deepEqual(fx.slerp(a, a, 0.3), a);
  const mid = fx.slerp([0, 1, 0], [0, -1, 0], 0.5);
  assert.ok(Math.abs(Math.hypot(...mid) - 1) < 1e-9 && Math.abs(fx.angleDeg(mid, [0, 1, 0]) - 90) < 1e-9);
  assert.equal(fx.angleDeg([0, 0, 0], a), 0);
});

test("AC-3 the button needs a limb fault with a time and a real difference: none of these shows it", () => {
  const none = (a) => fx.fixableFaults(a, model, pickFrames);
  assert.deepEqual(none({ faults: [] }), [], "a take with no fault");
  assert.deepEqual(none(null), []);
  assert.deepEqual(none({}), []);
  assert.deepEqual(none({ faults: [{ joints: ["left_shoulder"], body_part: "torso", at_s: 0.5 }] }), [], "a trunk fault");
  assert.deepEqual(none({ faults: [{ joints: ["left_elbow"] }] }), [], "no time");
  assert.deepEqual(fx.fixableFaults({ faults: [{ joints: ["left_elbow"], at_s: 1 }] }, { ...model, follower: model.follower.map(() => model.expected[0]), expected: model.expected.map(() => model.expected[0]) }, pickFrames), [], "a limb that already matches");
});

test("AC-4 the clip and the words", () => {
  const clip = fx.clipOf({ start: 1, end: 2 }, 10);
  assert.ok(Math.abs(clip.start - 0.1) < 1e-9 && Math.abs(clip.end - 2.9) < 1e-9);
  assert.deepEqual(fx.clipOf({ start: 0.2, end: 9.8 }, 10), { start: 0, end: 10 });
  assert.equal(fx.labelFor(["left arm", "right leg"]), "Your take, with the left arm and right leg moved toward the trainer's pose");
  const text = Object.values(fx.TEXT).concat(fx.labelFor(["left arm"])).join("\n");
  assert.ok(!/[\u2013\u2014]/.test(text) && !/ - /.test(text), "no em dash, en dash or spaced hyphen");
  assert.match(fx.TEXT.caption, /preview of the trainer's pose on your body, not a measurement/);
  assert.match(fx.TEXT.caption, /score is unchanged/);
  assert.ok(!/you did|you moved|you achieved/i.test(text), "never claims the student did it");
});

test("AC-5 the panel: the label, the note, Before and After, one view or two, the clock", async () => {
  installDom();
  const { renderFixIt } = await import("../../web/views/fix-it.js");
  const host = new (await import("./fake-dom.mjs")).El("div");
  const calls = [];
  const on = Object.fromEntries(["open", "close", "which", "split", "play", "scrub"].map((k) => [k, (...a) => calls.push([k, ...a])]));
  const view = renderFixIt(host, { t: fx.TEXT, options: [{ index: 3, text: "left arm: x" }] }, on);
  assert.equal(find(host, "fix-it-button").textContent, "Fix it for me");
  assert.equal(find(host, "fix-it-pick"), null, "one moment, no picker");
  assert.notEqual(find(host, "fix-it-panel").getAttribute("hidden"), null);
  find(host, "fix-it-button").click();
  assert.deepEqual(calls.pop(), ["open", 3]);
  view.visible(true);
  view.label("Your take, with the left arm moved toward the trainer's pose");
  assert.equal(find(host, "fix-it-label").textContent, "Your take, with the left arm moved toward the trainer's pose");
  assert.match(find(host, "fix-it-note").textContent, /not a measurement/);
  view.show({ which: "after", split: false });
  assert.equal(find(host, "fix-it-after").getAttribute("aria-pressed"), "true");
  assert.equal(find(host, "fix-it-before").getAttribute("aria-pressed"), "false");
  assert.equal(find(host, "fix-it-caption-a").textContent, "You, corrected");
  find(host, "fix-it-before").click();
  assert.deepEqual(calls.pop(), ["which", "before"]);
  view.show({ which: "before", split: false });
  assert.equal(find(host, "fix-it-caption-a").textContent, "You");
  find(host, "fix-it-split").click();
  assert.deepEqual(calls.pop(), ["split", true]);
  view.show({ which: "before", split: true });
  assert.equal(find(host, "fix-it-before").disabled, true);
  assert.equal(find(host, "fix-it-caption-b").textContent, "You, corrected");
  view.clock(1.234, true, 3);
  assert.equal(find(host, "fix-it-clock").textContent, "1.2 s");
  assert.equal(find(host, "fix-it-play").getAttribute("data-playing"), "true");
  find(host, "fix-it-play").click();
  assert.deepEqual(calls.pop(), ["play"]);
  view.data({ weight: 1 });
  assert.equal(find(host, "fix-it").getAttribute("data-weight"), "1");
  assert.equal(findAll(host, "fix-it-button").length, 1);
  const src = fs.readFileSync(new URL("../../web/views/fix-it.js", import.meta.url), "utf8");
  assert.ok(!/\bfetch\b|localStorage|sessionStorage/.test(src.replace(/^\/\/.*$/gm, "")), "a view holds no fetch or storage");
  const css = fs.readFileSync(new URL("../../web/theme/fix-it.css", import.meta.url), "utf8");
  assert.ok(!/#[0-9a-f]{3,8}\b|rgb\(|hsl\(/i.test(css.replace(/\/\*.*?\*\//gs, "")), "colours only through the tokens");
});

test("AC-5 the model has no DOM", () => {
  const src = fs.readFileSync(new URL("../../web/model/fix-it.js", import.meta.url), "utf8").replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/.*$/gm, "");
  assert.ok(!/\bdocument\b|\bwindow\b|\bfetch\b|localStorage/.test(src));
});
