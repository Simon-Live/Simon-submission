// The score pops over the You pane (web/model/score-pops.js): which pops a take has (each window's value at its end,
// each miss's points and a short cue at its moment), their words, and when they fire as the stage's clock moves
// (once per pass, only near their moment, again after a seek back, stacked in lanes while earlier ones still show).
// analysis-timeline.json is 8 reps, 77 / C, 11 misses; analysis-credit.json is the same take with a credit block.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { popsOf, popWord, shortCue, missWords, createPopScheduler, NEAR_S, LIFE_MS, LANES, QUEUE_S } from "../../web/model/score-pops.js";

const load = (f) => JSON.parse(fs.readFileSync(new URL(`../../fixtures/input/${f}`, import.meta.url)));
const plain = load("analysis-timeline.json");
const withCredit = load("analysis-credit.json");

test("shortCue: the body part a cue names, else its first meaningful words", () => {
  assert.equal(shortCue("Straighten your right knee more", "right knee bent more than the example at 3.7 s"), "knee");
  assert.equal(shortCue("Keep your elbows closer in"), "elbows");
  assert.equal(shortCue("Keep your chest up", "leaning forward more than the example at 9.3 s"), "chest");
  assert.equal(shortCue(null, "left arm too far right at 4.6 s"), "arm");
  assert.equal(shortCue(null, "upper arm out at 2 s"), "upper arm", "the longer part wins");
  assert.equal(shortCue("Slow down at 2.0 s"), "slow down", "no body part: two words, the time dropped");
  assert.equal(shortCue("", null), "");
  assert.equal(shortCue(undefined, 7), "", "negative: not text");
});

test("popsOf with credit: every window's credit at its end in the viewer's unit, then the misses", () => {
  const pops = popsOf(withCredit, { mode: "percent" });
  const windows = pops.filter((p) => p.kind === "window");
  assert.equal(windows.length, withCredit.score.timeline.length);
  assert.equal(windows[0].at, withCredit.score.timeline[0].t_s[1], "at the window's end");
  assert.equal(windows[0].text, "+95%", "in percent when chosen");
  assert.equal(popsOf(withCredit).find((p) => p.id === "w0").text, "+1,474", "points by default");
  assert.deepEqual(pops.map((p) => p.at), pops.map((p) => p.at).slice().sort((a, b) => a - b), "time order");
});

test("popsOf without credit: the window's own value; misses read '−points  part'", () => {
  const pops = popsOf(plain);
  assert.equal(pops.find((p) => p.id === "w0").text, String(plain.score.timeline[0].value));
  const misses = pops.filter((p) => p.kind === "miss");
  assert.equal(misses.length, 11, "each names its own part at its moment");
  const first = misses[0];
  assert.deepEqual([first.at, first.text, first.label], [4.6, "Left arm", "Left arm too far right"], "the part in the pop, Part 5's words as its label");
  assert.doesNotMatch(misses.map((p) => `${p.text} ${p.label}`).join(" "), /\d|points|lost/i, "words only: no points anywhere");
});

test("popsOf: one pop per moment and body part, the larger points; faults stand in when no miss has a time", () => {
  const miss = { at_s: 3.7, points: 17.3, cue: "Straighten your right knee more", text: "right knee bent" };
  const a = { score: { timeline: [{ t_s: [0, 5], value: 80, misses: [miss] }, { t_s: [5, 9], value: 70, misses: [{ ...miss }] }] } };
  assert.equal(popsOf(a).filter((p) => p.kind === "miss").length, 1);
  const two = { score: { timeline: [{ t_s: [0, 5], value: 80, misses: [{ ...miss, points: 13 }, { ...miss, points: 18.6, cue: "Keep your knee out" }, { at_s: 3.7, points: 9, cue: "Keep your chest up" }] }] } };
  assert.deepEqual(popsOf(two).filter((p) => p.kind === "miss").map((p) => p.text), ["Right knee", "Chest"], "one per part; a miss without its own line names its cue's part");
  const b = { score: { timeline: [{ t_s: [0, 5], value: 80, misses: [] }] }, faults: [{ at_s: 2.5, cue: "Keep your chest up" }, { text: "no time" }] };
  const f = popsOf(b).filter((p) => p.kind === "miss");
  assert.deepEqual(f.map((p) => [p.at, p.text, p.label]), [[2.5, "Chest", "Keep your chest up"]], "a fault without points names its cue's part; one without a time none");
  assert.deepEqual(popsOf(null), []);
  assert.deepEqual(popsOf({ score: { timeline: [{ t_s: [0, 1] }] } }), [], "negative: no value and no credit, nothing to pop");
});

const P = (id, at, kind = "miss") => ({ id, at, kind, text: id, label: id });
const ids = (out) => out.map((x) => x.pop.id);

test("scheduler: fires once as the clock passes; nothing on the first reading", () => {
  const s = createPopScheduler([P("a", 1.0), P("b", 2.0, "window")]);
  assert.deepEqual(s.update(1.5, 0), [], "the first reading only notes the time");
  assert.deepEqual(ids(s.update(1.9, 100)), []);
  assert.deepEqual(ids(s.update(2.05, 200)), ["b"]);
  assert.deepEqual(ids(s.update(2.2, 300)), [], "once per pass");
});

test("scheduler: a scrub forward fires none of the skipped pops, only those within NEAR_S", () => {
  const s = createPopScheduler([P("a", 1), P("b", 2), P("c", 3), P("d", 4.8)]);
  s.update(0, 0);
  assert.deepEqual(ids(s.update(5.0, 100)), ["d"], `only the pop within ${NEAR_S} s`);
  assert.deepEqual(ids(s.update(5.1, 200)), []);
});

test("scheduler: a seek back resets the pops after it, so a replay shows them again", () => {
  const s = createPopScheduler([P("a", 1), P("b", 2)]);
  s.update(0.5, 0);
  assert.deepEqual(ids(s.update(1.1, 100)), ["a"]);
  assert.deepEqual(ids(s.update(2.1, 1200)), ["b"]);
  assert.deepEqual(s.update(0.2, 2400), [], "the seek back itself fires nothing behind it");
  assert.deepEqual(ids(s.update(1.05, 3500)), ["a"], "the replay shows it again");
  assert.deepEqual(ids(s.update(2.0, 4600)), ["b"]);
  assert.deepEqual(s.update(1.99, 4700), [], "a tiny step back (clock jitter) is not a seek");
});

test("scheduler: pops close together take lanes until the earlier ones are gone; extra ones wait, then lapse", () => {
  const many = Array.from({ length: LANES + 1 }, (_, i) => P(`m${i}`, 3.2));
  const s = createPopScheduler([...many, P("w", 3.2, "window")]);
  s.update(3.0, 0);
  const out = s.update(3.25, 1000);
  assert.deepEqual(out.filter((x) => x.pop.kind === "miss").map((x) => x.lane), [0, 1, 2]);
  assert.equal(out.find((x) => x.pop.id === "w").lane, 0, "each kind has its own lanes");
  assert.deepEqual(s.update(3.6, 1000 + LIFE_MS - 1).length, 0, "every lane still shows a pop");
  const late = s.update(3.9, 1000 + LIFE_MS);
  assert.deepEqual(late.map((x) => [x.pop.id, x.lane]), [[`m${LANES}`, 0]], "the queued one takes the freed lane");
  const t = createPopScheduler(many);
  t.update(3.0, 0);
  t.update(3.25, 0);
  assert.deepEqual(t.update(3.2 + QUEUE_S + 0.1, 10), [], "negative: still no lane once the clock is QUEUE_S past it: it lapses");
  assert.deepEqual(t.update(3.2 + QUEUE_S + 0.2, 5000), [], "and does not come back");
  const u = createPopScheduler([P("a", 1), P("b", 2)]);
  u.update(0.9, 0);
  assert.deepEqual(u.update(1.0, 100).map((x) => x.lane), [0]);
  assert.deepEqual(u.update(2.0, 100 + LIFE_MS).map((x) => x.lane), [0], "a lane frees when its pop is gone");
});

test("scheduler: a moment past the clip's end fires just before the end; setPops keeps what fired", () => {
  const s = createPopScheduler([P("last", 10.2, "window")]);
  s.update(9.5, 0);
  assert.deepEqual(ids(s.update(9.97, 100, 10.0)), ["last"]);
  s.setPops([{ ...P("last", 10.2, "window"), text: "+1,474" }]);
  assert.deepEqual(s.update(10.0, 200, 10.0), [], "a unit change does not fire it again");
  s.reset();
  assert.deepEqual(s.update(0, 300), [], "after reset the next reading only notes the time");
  assert.deepEqual(s.update(Number.NaN, 400), [], "negative: no time, nothing");
});

test("missWords: Part 5's line without its time or count, capitalised; else the cue", () => {
  assert.equal(missWords("left arm much too low at 3.2 s"), "Left arm much too low");
  assert.equal(missWords("Hands too close in at 11.0 s (2 times)"), "Hands too close in");
  assert.equal(missWords(null, "Keep your chest up"), "Keep your chest up");
  assert.equal(missWords("", "  "), "", "negative: nothing usable");
  assert.equal(missWords(7, undefined), "", "negative: not text");
});

test("popWord: one or two words, the part with its side when the line puts one before it", () => {
  assert.equal(popWord(null, "left arm too far right at 4.6 s"), "Left arm", "the side before the part, not the direction after");
  assert.equal(popWord("Straighten your right knee more", "right knee bent"), "Right knee");
  assert.equal(popWord("Keep your elbows closer in"), "Elbows");
  assert.equal(popWord(null, "left upper arm out"), "Left upper arm", "the longer part wins");
  assert.equal(popWord("Slow down at 2.0 s"), "Slow down", "no body part: shortCue's words");
  assert.equal(popWord("", null), "");
  assert.equal(popWord(undefined, 7), "", "negative: not text");
  for (const t of ["left arm much too low at 3.2 s", "Hands too close in at 11.0 s (2 times)", "leaning forward more than the example"]) {
    assert.ok(popWord(null, t).split(" ").length <= 3, `short: ${t}`);
  }
});
