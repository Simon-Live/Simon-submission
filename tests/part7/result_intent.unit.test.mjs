// The intent carried forward from the parked lane/rubric-result-parked-visual (docs/specs/result-intent.md AC-I1 to
// AC-I4): merged moment marks, how the score adds up, filler said once, the reveal's session rule and slide curve.
//   node --test tests/part7/result_intent.unit.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { partTest } from "./needs-part.mjs";
import { markerGroups, markShare, MARK_SHARE, groupLabel } from "../../web/model/marker-groups.js";
import { scoreSum } from "../../web/model/score-sum.js";
import { dropRepeatedFiller, withoutRepeatedFiller } from "../../web/model/filler.js";
import { revealLedger, REVEAL_PREFIX, easeInOut, spreadAt, SLIDE_MS } from "../../web/model/reveal.js";
import { summaryOf } from "../../web/model/result-summary.js";
import { momentsToReview } from "../../web/coaching.js";

const input = (f) => JSON.parse(fs.readFileSync(new URL(`../../fixtures/input/${f}`, import.meta.url)));
// job 5277380db1e1, a real take: Part 5 reports the same miss at 0.9 s in both of its windows, each ending "nice effort."
const real = JSON.parse(fs.readFileSync(new URL("./fixtures/history/5277380db1e1/analysis.json", import.meta.url)));
const MINUS = "−";
/** scoreSum with its no-break spaces read as spaces, so the expected lines stay readable; the spaces are pinned below. */
const sumOf = (score, faults) => { const s = scoreSum(score, faults); return s && { ...s, text: s.text.replace(/ /g, " ") }; };

test("the sum is held together by no-break spaces, so it never splits across lines", () => {
  const { text } = scoreSum(input("analysis-insights.json").score);
  assert.ok(text.includes(["100", `${MINUS} 19.4`, `${MINUS} 3.7`, "≈ 77."].join(" ")), text);
});

// ---- AC-I1 merged marks ---------------------------------------------------------------------------------------
test("two moments at the same time become one mark that names both and plays the first", () => {
  const moments = momentsToReview(real);
  assert.equal(moments.length, 2, "the real take has two moments at 0.9 s");
  assert.deepEqual(moments.map((m) => m.at), [0.9, 0.9]);
  const groups = markerGroups(moments, 12.8, markShare(366));
  assert.equal(groups.length, 1);
  assert.equal(groups[0].moments.length, 2);
  assert.equal(groups[0].at, 0.9);
  assert.deepEqual(groups[0].ats, [0.9, 0.9]);
  assert.equal(groups[0].label, `2 moments. ${moments[0].label}. ${moments[1].label}`);
  assert.match(groups[0].label, /costs 22\.0 points.*costs 21\.5 points/);
});

test("marks far apart stay apart, close ones merge, and no two marks overlap", () => {
  const mk = (at, kind = "miss", to = at) => ({ at, from: at, to, kind, label: `At ${at} s` });
  const moments = [mk(1), mk(1.4), mk(6), mk(6.2, "window", 8), mk(11.9), mk(12.7)];
  const groups = markerGroups(moments, 12.8, 0.1);
  assert.deepEqual(groups.map((g) => g.ats), [[1, 1.4], [6, 6.2], [11.9, 12.7]]);
  assert.equal(groups[1].kind, "window", "a group with a weak part is drawn as one");
  assert.equal(groups[0].kind, "miss");
  for (let i = 1; i < groups.length; i++) assert.ok(groups[i].left >= groups[i - 1].left + groups[i - 1].width, `mark ${i} clear of mark ${i - 1}`);
  for (const g of groups) assert.ok(g.left >= 0 && g.left + g.width <= 1 + 1e-9, "inside the strip");
  // negative: moments one mark-width apart are not merged
  assert.equal(markerGroups([mk(1), mk(1 + 0.11 * 12.8)], 12.8, 0.1).length, 2);
});

test("an earlier moment listed later still leads its group; edge cases", () => {
  const groups = markerGroups([{ at: 3, from: 2.9, to: 3, label: "b" }, { at: 2.8, from: 2.8, to: 2.8, label: "a" }], 10, 0.12);
  assert.equal(groups.length, 1);
  assert.equal(groups[0].at, 2.8, "a tap plays the earliest moment");
  assert.deepEqual(markerGroups([], 10), []);
  assert.deepEqual(markerGroups(null, 10), []);
  assert.equal(markerGroups([{ at: 1, label: "x" }, { at: 5, label: "y" }], 0).length, 1, "no take length: all at the start, one mark");
  assert.equal(markShare(0), MARK_SHARE);
  assert.equal(markShare(440), 0.1);
  assert.equal(groupLabel([{ label: "At 1.0 s: x" }]), "At 1.0 s: x");
});

// ---- AC-I2 how the score adds up ------------------------------------------------------------------------------
test("v1 take score: 100 minus Part 5's components, printed because it rounds to the score", () => {
  const s = sumOf(input("analysis-1.2.0.json").score);
  assert.equal(s.adds, true);
  assert.equal(s.capped, false);
  assert.equal(s.text, `Your take started at 100 and lost 38.1 points for misses and 0.7 for overall match: 100 ${MINUS} 38.1 ${MINUS} 0.7 ≈ 61.`);
});

test("per rep: the average loss, and why the points next to each miss add up to more", () => {
  const s = sumOf(input("analysis-insights.json").score);
  assert.equal(s.adds, true);
  assert.equal(s.text, `Each rep started at 100 and lost, on average, 19.4 points for misses and 3.7 for overall match: 100 ${MINUS} 19.4 ${MINUS} 3.7 ≈ 77. `
    + "The points next to each miss count only in its own rep, so together they add up to more.");
  const parts = sumOf(real.score);
  assert.match(parts.text, /^Each part started at 100/);
  assert.match(parts.text, /≈ 77\. The points next to each miss count only in its own part/);
});

test("a capped score names the cap; with no uncapped value the sum is not printed (negative)", () => {
  const s = sumOf(input("analysis-capped-low-match.json").score);
  assert.equal(s.adds, false);
  assert.equal(s.capped, true);
  assert.ok(!s.text.includes("≈"), "no equation when it does not land on Part 5's number");
  // the parts (23.3 and 4.0) do not land on the shown deduction, so no figure is printed (bounded figures, rubric audit)
  assert.equal(s.text, "Your take started at 100 and lost points for misses and overall match. "
    + "A warning then limited the score to 59: this take does not closely match the trainer's movement.");
  const withUncapped = sumOf({ ...input("analysis-capped-low-match.json").score, uncapped: { value: 73, grade: "C" } });
  assert.equal(withUncapped.adds, true);
  assert.match(withUncapped.text, /≈ 73 before the warning cap\. A warning then limited the score to 59: /);
  assert.match(sumOf({ value: 59, grade: "F", components: { faults: 30, similarity: 1 }, capped_by: ["quality_blur"] }).text,
    /limited the score to 59: the video quality\.$/);
});

test("v2 and later: the fault cap and the tempo term", () => {
  const v2 = sumOf({ version: "simon.score.v2", value: 89, grade: "B", components: { faults: 5, similarity: 1 }, fault_cap: 89,
    uncapped: { value: 94, grade: "A" } }, 1);
  assert.equal(v2.text, `Your take started at 100 and lost 5.0 points for misses and 1.0 for overall match: 100 ${MINUS} 5.0 ${MINUS} 1.0 ≈ 94 before the fault cap. `
    + "Capped at 89 (B) because the take shows a fault. Without the cap: 94 (A).");
  // negative: a fault cap that did not lower the value says nothing about it
  assert.equal(sumOf({ value: 70, grade: "C", components: { faults: 28, similarity: 2 }, fault_cap: 89 }).capped, false);
  const dance = sumOf({ value: 80, grade: "B", components: { faults: 12, similarity: 2, tempo: 6 } });
  assert.match(dance.text, /lost 12\.0 points for misses and 2\.0 for overall match and 6\.0 for timing: 100 − 12\.0 − 2\.0 − 6\.0 ≈ 80\./);
});

// TICKET-120: the fault cap in Part 5's simon.score.v3 (synthetic fixtures built from the ticket's sample blocks)
const synth = (n) => JSON.parse(fs.readFileSync(new URL(`./fixtures/analysis/synthetic-v3-${n}.analysis.json`, import.meta.url))).score;

test("TICKET-120 two faults: the fault cap is explained once, with the uncapped grade", () => {
  const s = sumOf(synth("two-fault"), 2);
  assert.match(s.text, /≈ 82 before the fault cap\. Capped at 79 \(C\) because the take shows two or more faults\. Without the cap: 82 \(B\)\.[^]*$/);
  assert.equal(s.capped, true);
  assert.equal(s.text.match(/Capped at/g).length, 1);
});

test("TICKET-120 one fault: capped at 89 (B), uncapped grade A", () => {
  assert.match(sumOf(synth("one-fault"), 1).text, /Capped at 89 \(B\) because the take shows a fault\. Without the cap: 93 \(A\)\./);
});

test("TICKET-120 negative: a fault cap that did not lower the value says nothing; so for v1 and for no fault_cap", () => {
  const s = sumOf(synth("fault-cap-not-lowered"));
  assert.equal(s.capped, false);
  assert.doesNotMatch(s.text, /Capped|Without the cap/);
  assert.doesNotMatch(sumOf(input("analysis-insights.json").score).text, /Capped|Without the cap/);
  assert.equal(sumOf({ ...synth("two-fault"), uncapped: { value: 79, grade: "C" } }).capped, false, "uncapped equal to the cap");
  assert.equal(sumOf({ ...synth("two-fault"), fault_cap: undefined }).capped, false);
});

test("TICKET-120 both caps: the fault cap comes first, then the unchanged low-match note", () => {
  const s = sumOf({ ...synth("two-fault"), value: 59, grade: "F", capped_by: ["low_match"] }, 2);
  assert.match(s.text, /Capped at 79 \(C\) because the take shows two or more faults\. Without the cap: 82 \(B\)\. A warning then limited the score to 59: this take does not closely match the trainer's movement\./);
});

// TICKET-120 AC-4: Part 5's published fixtures (modules/part-5, read as files), not the synthetic ones
const p5 = (n) => new URL(`../../modules/part-5/fixtures/output/analysis.${n}.example.json`, import.meta.url);
const p5Test = partTest(5);

p5Test("TICKET-120 AC-4 Part 5 fault-capped fixture: one fault, capped at 89 (B), uncapped 94 (A)", () => {
  const doc = JSON.parse(fs.readFileSync(p5("fault-capped")));
  assert.equal(doc.score.version, "simon.score.v3");
  assert.match(sumOf(doc.score, doc.faults.length).text, /Capped at 89 \(B\) because the take shows a fault\. Without the cap: 94 \(A\)\./);
});

p5Test("TICKET-120 AC-4 Part 5 double-capped fixture: two faults, capped at 79 (C), uncapped 82 (B), said once", () => {
  const doc = JSON.parse(fs.readFileSync(p5("double-capped")));
  const s = sumOf(doc.score, doc.faults.length);
  assert.match(s.text, /Capped at 79 \(C\) because the take shows two or more faults\. Without the cap: 82 \(B\)\./);
  assert.equal(s.text.match(/Capped at/g).length, 1);
});

p5Test("TICKET-120 AC-4 Part 5 no-faults fixture: no fault-cap note", () => {
  const doc = JSON.parse(fs.readFileSync(p5("no-faults")));
  assert.doesNotMatch(sumOf(doc.score, 0).text, /Capped|Without the cap/);
});

test("a sum that does not land on the score prints no equation; no components, no line", () => {
  const off = sumOf({ value: 70, grade: "C", components: { faults: 10, similarity: 1 } });
  assert.equal(off.adds, false);
  assert.ok(!off.text.includes("≈"));
  assert.equal(sumOf({ value: 0, grade: "F", components: null }), null);
  assert.equal(sumOf(null), null);
  assert.equal(sumOf({ value: 61, grade: "D", components: { similarity: 1 } }), null);
});

test("the summary model carries the line for the view", () => {
  assert.equal(summaryOf(input("analysis-insights.json")).sum.adds, true);
  assert.equal(summaryOf({ score: { value: 0, grade: "F", components: null } }).sum, null);
});

// ---- AC-I3 filler said once -----------------------------------------------------------------------------------
test("a short clause already said is left out of the later lines", () => {
  assert.deepEqual(dropRepeatedFiller([
    "You are leaning forward more than the example at 0.9 s, nice effort.",
    "You are leaning forward more than the example at 0.9 s, nice effort.",
    "Your elbows are wider at 3.0 s, Nice effort!",
  ]), [
    "You are leaning forward more than the example at 0.9 s, nice effort.",
    "You are leaning forward more than the example at 0.9 s.",
    "Your elbows are wider at 3.0 s.",
  ]);
});

test("filler edge cases: one-clause lines, lines left empty, clauses with numbers, non-strings", () => {
  assert.deepEqual(dropRepeatedFiller(["Nice effort.", "Nice effort."]), ["Nice effort.", "Nice effort."], "a line that is only the clause stays");
  assert.deepEqual(dropRepeatedFiller(["Keep going, nice effort.", "Nice effort, keep going."]), ["Keep going, nice effort.", "Nice effort, keep going."]);
  assert.deepEqual(dropRepeatedFiller(["Arm up at 2 s, hold it.", "Leg out at 2 s, hold it."]), ["Arm up at 2 s, hold it.", "Leg out at 2 s."]);
  assert.deepEqual(dropRepeatedFiller(["Arm up at 2 s, then 3 reps.", "Leg out, then 3 reps."]), ["Arm up at 2 s, then 3 reps.", "Leg out, then 3 reps."], "a clause with a digit is content");
  assert.deepEqual(dropRepeatedFiller([null, "", "One."]), [null, "", "One."]);
  assert.deepEqual(dropRepeatedFiller(undefined), []);
});

test("the display copy changes the shown lines only and leaves Part 5's analysis as it was", () => {
  const before = JSON.stringify(real);
  const shown = withoutRepeatedFiller(real);
  assert.equal(JSON.stringify(real), before, "the input is not changed");
  const texts = shown.score.timeline.flatMap((w) => w.misses.map((m) => m.text));
  assert.deepEqual(texts, ["You are leaning forward more than the example at 0.9 s, nice effort.", "You are leaning forward more than the example at 0.9 s."]);
  assert.equal(texts.join(" ").match(/nice effort/gi).length, 1, "the filler shows once on the result");
  assert.equal(shown.faults[0].text_timed, real.faults[0].text_timed, "the shown fault line had no filler");
  assert.equal(shown.faults[0].coaching, real.faults[0].coaching, "a field the list does not show is left alone");
  assert.equal(withoutRepeatedFiller(null), null);
});

// ---- AC-I4 the reveal's rules ---------------------------------------------------------------------------------
test("the reveal plays once per result per session; storage that throws falls back to the page", () => {
  const store = new Map();
  const storage = { getItem: (k) => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, v) };
  const a = revealLedger(storage);
  assert.equal(a.seen("job1/"), false);
  a.mark("job1/");
  assert.equal(store.get(`${REVEAL_PREFIX}job1/`), "1");
  assert.equal(revealLedger(storage).seen("job1/"), true, "a new page in the same session has seen it");
  assert.equal(revealLedger(storage).seen("job2/"), false, "negative: another result has not");
  const broken = { getItem() { throw new Error("denied"); }, setItem() { throw new Error("denied"); } };
  const b = revealLedger(broken);
  assert.equal(b.seen("x"), false);
  b.mark("x");
  assert.equal(b.seen("x"), true);
  const none = revealLedger(null);
  none.mark("y");
  assert.equal(none.seen("y"), true);
});

test("the slide eases from side by side (1) to the overlay (0)", () => {
  assert.equal(SLIDE_MS, 900);
  assert.equal(spreadAt(0), 1);
  assert.equal(spreadAt(1), 0);
  assert.equal(easeInOut(0.5), 0.5);
  assert.equal(spreadAt(-1), 1);
  assert.equal(spreadAt(2), 0);
  const ks = [0, 0.1, 0.3, 0.5, 0.7, 0.9, 1].map(spreadAt);
  assert.ok(ks.every((v, i) => !i || v <= ks[i - 1]), "only closes");
});

test("TICKET-193 the fault wording follows the fault count, not the cap value", () => {
  assert.match(sumOf({ ...synth("one-fault"), fault_cap: 79, uncapped: { value: 93, grade: "A" } }, 1).text, /because the take shows a fault\./);
  assert.match(sumOf({ ...synth("two-fault"), fault_cap: 89, uncapped: { value: 93, grade: "A" } }, 3).text, /because the take shows two or more faults\./);
  assert.match(sumOf(synth("two-fault")).text, /because the take shows faults\./, "no count: no number claimed");
});

test("TICKET-193 the warning sentence keeps the caps in order when the fault cap is the lower one", () => {
  const s = sumOf({ ...synth("two-fault"), value: 79, grade: "C", capped_by: ["low_match"] }, 2).text;
  assert.doesNotMatch(s, /then limited the score to 79/);
  assert.match(s, /A warning also applies \(this take does not closely match the trainer's movement\), but the fault cap of 79 is the lower limit\./);
});

test("TICKET-193 a clause that names a joint is never filler, and a line is never cut to its time", () => {
  const same = ["At 1.2 s, straighten your left knee.", "At 4.0 s, straighten your left knee."];
  assert.deepEqual(dropRepeatedFiller(same), same);
  assert.deepEqual(dropRepeatedFiller(["At 1.0 s, hold it.", "At 4.0 s, hold it."]), ["At 1.0 s, hold it.", "At 4.0 s, hold it."], "only the time would remain");
});
