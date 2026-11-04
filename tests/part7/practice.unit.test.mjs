// Unit tests for modes.js, practice.js and reference.js sectionTime (practice-and-modes.md). `node --test`.
import test from "node:test";
import assert from "node:assert/strict";
import {
  MODES, PRESETS, ALL, KEY, LEGACY_KEY, loadChoice, saveChoice, forgetHeaderChoice, defaultForCategory, effectiveMode, matchesMode, learnSpeed,
  countdownFor, promoteChallenges, sectionLabel, scoringLine,
} from "../../web/modes.js";
import {
  deriveSections, repStarts, buildLadder, stepSection, stepLoop, loadProgress, saveProgress, recordScore, isUnlocked,
  isPassed, currentIndex, settlePending, stepScore, emptyProgress, PASS_SCORE,
} from "../../web/practice.js";
import { sectionTime } from "../../web/reference.js";
import { buildSubmit } from "../../web/take-flow.js";

const memory = (init = {}) => {
  const data = { ...init };
  return { getItem: (k) => (k in data ? data[k] : null), setItem: (k, v) => { data[k] = String(v); }, removeItem: (k) => { delete data[k]; }, data };
};
const rep = (rep, ...ms) => ({ rep, movement: "squat", keyframes: ms.map((t_ms, i) => ({ name: `k${i}`, frame: t_ms / 40, t_ms })) });

// ----- modes -------------------------------------------------------------------------------------------
test("the mode defaults from the entry category and the stored choice wins", () => {
  assert.equal(defaultForCategory("dance"), "dance");
  assert.equal(defaultForCategory("exercise"), "fitness");
  assert.equal(defaultForCategory("other"), null);
  assert.equal(effectiveMode({ category: "dance" }, memory()), "dance");
  assert.equal(effectiveMode({ category: "exercise" }, memory()), "fitness");
  assert.equal(effectiveMode({ category: "exercise" }, memory({ [KEY]: "rehab" })), "rehab");
  assert.equal(effectiveMode({ category: "dance" }, memory({ [KEY]: "all" })), "dance"); // All is a filter only
  assert.equal(effectiveMode({}, memory()), "fitness");
});

test("the mode choice round-trips and junk or blocked storage reads as unset", () => {
  const s = memory();
  assert.equal(loadChoice(s), null);
  saveChoice("rehab", s);
  assert.equal(s.data[KEY], "rehab");
  assert.equal(loadChoice(s), "rehab");
  assert.equal(loadChoice(memory({ [KEY]: "zen" })), null);
  const blocked = { getItem() { throw new Error("blocked"); }, setItem() { throw new Error("blocked"); } };
  assert.equal(loadChoice(blocked), null);
  assert.doesNotThrow(() => saveChoice("dance", blocked));
});

test("what the removed header switch stored is ignored and dropped (TICKET-436)", () => {
  const old = memory({ [LEGACY_KEY]: "dance" });
  assert.equal(loadChoice(old), null, "the old key is not read");
  assert.equal(effectiveMode({ category: "exercise" }, old), "fitness", "the entry's own kind decides");
  forgetHeaderChoice(old);
  assert.equal(old.data[LEGACY_KEY], undefined);
  const kept = memory({ [KEY]: "rehab", [LEGACY_KEY]: "dance" });
  forgetHeaderChoice(kept);
  assert.equal(kept.data[KEY], "rehab", "the follow screen's own choice stays");
  const blocked = { getItem() { throw new Error("blocked"); }, removeItem() { throw new Error("blocked"); } };
  assert.doesNotThrow(() => forgetHeaderChoice(blocked));
});

test("the catalog filter follows the documented rules", () => {
  const labels = { a: { tags: ["rehab"] }, b: { tags: ["dance"] }, c: { tags: ["fitness"] }, d: { tags: [] } };
  const E = (id, category) => ({ id, category });
  const entries = [E("a", "exercise"), E("b", "exercise"), E("c", "dance"), E("d", "dance"), E("e", "exercise")];
  const ids = (mode) => entries.filter((e) => matchesMode(e, mode, labels)).map((e) => e.id);
  assert.deepEqual(ids("dance"), ["b", "c", "d"]); // category dance or tag dance
  assert.deepEqual(ids("fitness"), ["a", "b", "c", "e"]); // category exercise or tag fitness
  assert.deepEqual(ids("rehab"), ["a"]); // tag rehab only
  assert.deepEqual(ids(ALL), ["a", "b", "c", "d", "e"]);
  assert.deepEqual(ids(null), ["a", "b", "c", "d", "e"]);
});

test("presets: speed, countdown and promotion per mode", () => {
  assert.deepEqual(MODES.map(learnSpeed), [0.75, 0.5, 1]);
  assert.equal(countdownFor("rehab"), 10);
  assert.ok(countdownFor("rehab") > countdownFor("fitness"));
  assert.equal(promoteChallenges("rehab"), false);
  assert.equal(promoteChallenges("dance"), true);
  assert.match(PRESETS.rehab.safety, /pain-free range; stop if it hurts/);
  assert.equal(PRESETS.dance.safety, undefined);
});

test("labels and the scoring line say only what Part 5 reported", () => {
  assert.equal(sectionLabel({ index: 2, count: 4 }), "Section 2 of 4");
  assert.equal(sectionLabel({ index: 3, count: 4, first: 1 }), "Sections 1 to 3 of 4");
  assert.equal(sectionLabel(null), null);
  const none = scoringLine({ score: { value: 80 } });
  assert.equal(none.profile, "");
  assert.equal(none.text, "This score uses the standard rules.");
  const rehab = scoringLine({ profile: "rehab", profile_source: "part7-rules" });
  assert.equal(rehab.text.startsWith("Scored with rehab rules."), true);
  assert.match(rehab.text, /more forgiving.*not a more accurate measure/);
  assert.match(scoringLine({ profile: "dance" }).text, /^Scored with dance rules\. These practice rules are more forgiving/);
  assert.equal(scoringLine({ profile: "fitness" }).text, "Scored with fitness rules. These are the standard rules.");
});

test("buildSubmit adds mode and section for a follow and mode for a group, nothing when absent", () => {
  const base = { role: "follower", upload: "u", trim: null, peopleJob: "p", choice: { person_id: "0" }, entryId: "e", labels: null };
  assert.equal(buildSubmit(base).args.length, 5);
  const sec = { start_ms: 0, end_ms: 4000, index: 1, count: 2 };
  assert.deepEqual(buildSubmit({ ...base, extra: { mode: "rehab", section: sec } }).args[5], { mode: "rehab", section: sec });
  const group = buildSubmit({ role: "trainer", mode: "group", upload: "u", peopleJob: "p", choice: { trainer_id: 1, follower_ids: [2], labels: {} }, name: "n", category: "dance", labels: null, extra: { mode: "dance" } });
  assert.equal(group.args[0].mode, "dance");
  assert.equal("mode" in buildSubmit({ ...group, role: "trainer", mode: "group", choice: { trainer_id: 1, follower_ids: [2], labels: {} }, name: "n", category: "dance", upload: "u", peopleJob: "p", labels: null }).args[0], false);
});

// ----- sections ----------------------------------------------------------------------------------------
test("sections come from the repetitions of the Part 1 keyframes", () => {
  const doc = { fps: 25, people: [{ id: 0, repetitions: [rep(1, 0, 1000, 2500), rep(2, 4000, 5000), rep(3, 8000, 9000)] }] };
  assert.deepEqual(repStarts(doc), [0, 4000, 8000]);
  const { sections, source } = deriveSections(doc, 12000);
  assert.equal(source, "keyframes");
  assert.deepEqual(sections.map((s) => [s.start_ms, s.end_ms]), [[0, 4000], [4000, 8000], [8000, 12000]]);
  assert.ok(sections.every((s, i) => s.index === i + 1 && s.count === 3));
});

test("frame-only marks use the file's fps, and the person with id 0 is read", () => {
  const doc = { fps: 10, people: [{ id: 5, repetitions: [{ keyframes: [{ name: "x", frame: 1 }] }] }, { id: 0, repetitions: [{ keyframes: [{ name: "a", frame: 0 }] }, { keyframes: [{ name: "a", frame: 50 }] }] }] };
  assert.deepEqual(repStarts(doc), [0, 5000]);
});

test("short rep sections are merged into a neighbour, and more than 8 are joined down to 8", () => {
  const merged = deriveSections({ people: [{ id: 0, repetitions: [rep(1, 0), rep(2, 1000), rep(3, 6000)] }] }, 10000);
  assert.deepEqual(merged.sections.map((s) => [s.start_ms, s.end_ms]), [[0, 6000], [6000, 10000]]);
  const many = { people: [{ id: 0, repetitions: Array.from({ length: 12 }, (_, i) => rep(i + 1, i * 2500)) }] };
  const out = deriveSections(many, 30000);
  assert.equal(out.sections.length, 8);
  assert.equal(out.sections[0].start_ms, 0);
  assert.equal(out.sections.at(-1).end_ms, 30000);
  assert.ok(out.sections.every((s, i, a) => s.end_ms - s.start_ms >= 2000 && (i === 0 || s.start_ms === a[i - 1].end_ms)));
});

test("no keyframes gives equal slices of about 4 s, 2 to 8", () => {
  const eq = (ms) => deriveSections(null, ms);
  assert.equal(eq(12000).sections.length, 3);
  assert.equal(eq(12000).source, "equal");
  assert.deepEqual(eq(12000).sections.map((s) => s.end_ms - s.start_ms), [4000, 4000, 4000]);
  assert.equal(eq(5000).sections.length, 2); // never fewer than 2
  assert.equal(eq(120000).sections.length, 8); // never more than 8
  assert.equal(eq(1500).sections.length, 0); // too short to split
  assert.equal(eq(NaN).sections.length, 0);
  assert.equal(deriveSections({ people: [{ id: 0, repetitions: [rep(1, 0)] }] }, 8000).source, "equal"); // one rep is not a split
  assert.ok(eq(2000).sections.every((s) => s.end_ms - s.start_ms >= 1000)); // the server needs 1 s at least
});

// ----- the ladder --------------------------------------------------------------------------------------
const three = deriveSections(null, 12000).sections;

test("the ladder runs section slow, section full, ..., joined, full routine", () => {
  const steps = buildLadder(three, 0.5);
  assert.deepEqual(steps.map((s) => s.key), ["s1@slow", "s1@full", "s2@slow", "s2@full", "s3@slow", "s3@full", "j1-2", "full"]);
  assert.deepEqual(steps.map((s) => s.speed), [0.5, 1, 0.5, 1, 0.5, 1, 1, 1]);
  assert.deepEqual(buildLadder(three, 1).map((s) => s.key), ["s1@full", "s2@full", "s3@full", "j1-2", "full"]); // fitness: no slow step
  assert.deepEqual(buildLadder([], 0.5), []);
});

test("a step's request: its section range, joined start, slow speed; the full routine sends none", () => {
  const steps = buildLadder(three, 0.75);
  assert.deepEqual(stepSection(steps[2], three), { start_ms: 4000, end_ms: 8000, index: 2, count: 3, speed: 0.75 });
  assert.deepEqual(stepSection(steps[3], three), { start_ms: 4000, end_ms: 8000, index: 2, count: 3 });
  assert.deepEqual(stepSection(steps.find((s) => s.key === "j1-2"), three), { start_ms: 0, end_ms: 8000, index: 2, count: 3, first: 1 });
  assert.equal(stepSection(steps.at(-1), three), null);
  assert.deepEqual(stepLoop(steps[0], three), { start_s: 0, end_s: 4, rate: 0.75 });
  assert.equal(stepLoop(steps.at(-1), three), null);
});

test("a step passes at 80 and unlocks the next; earlier locked steps stay locked", () => {
  const steps = buildLadder(three, 0.5);
  let p = emptyProgress();
  assert.deepEqual(steps.map((_, i) => isUnlocked(steps, p, i)), [true, false, false, false, false, false, false, false]);
  p = recordScore(p, "s1@slow", PASS_SCORE - 1);
  assert.equal(isPassed(p, steps[0]), false);
  assert.equal(isUnlocked(steps, p, 1), false);
  p = recordScore(p, "s1@slow", 80);
  assert.equal(isUnlocked(steps, p, 1), true);
  assert.equal(isUnlocked(steps, p, 2), false);
  assert.equal(currentIndex(steps, p), 1);
  p = recordScore(p, "s1@slow", 60); // a worse take keeps the best score
  assert.equal(p.best["s1@slow"], 80);
  for (const s of steps) p = recordScore(p, s.key, 95);
  assert.equal(currentIndex(steps, p), steps.length);
});

test("progress is stored per entry and junk reads as empty", () => {
  const s = memory();
  const p = recordScore({ ...emptyProgress(), on: true, pending: { key: "s1@slow", job: "j" } }, "s1@slow", 90);
  assert.equal(p.pending, null);
  saveProgress("squat", p, s);
  assert.ok("simon.practice.squat" in s.data);
  assert.deepEqual(loadProgress("squat", s), p);
  assert.deepEqual(loadProgress("other", s), emptyProgress());
  assert.deepEqual(loadProgress("x", memory({ "simon.practice.x": "{bad" })), emptyProgress());
  assert.deepEqual(loadProgress("x", memory({ "simon.practice.x": JSON.stringify({ v: 1, best: { a: "x", b: 70 }, pending: { key: 1 } }) })).best, { b: 70 });
});

test("settling the last take: done counts its score, running waits, failed or gone clears it", async () => {
  const pend = { ...emptyProgress(), pending: { key: "s1@slow", job: "j1" } };
  const read = (job) => async () => job;
  assert.equal((await settlePending(pend, read({ status: "done", result: { score: 83 } }))).best["s1@slow"], 83);
  assert.equal((await settlePending(pend, read({ status: "done", result: { score: 83 } }))).pending, null);
  assert.deepEqual((await settlePending(pend, read({ status: "running" }))).pending, pend.pending);
  assert.equal((await settlePending(pend, read({ status: "failed" }))).pending, null);
  assert.equal((await settlePending(pend, async () => { throw Object.assign(new Error("x"), { status: 404 }); })).pending, null);
  assert.deepEqual((await settlePending(pend, async () => { throw new Error("offline"); })).pending, pend.pending);
  assert.equal(await settlePending(emptyProgress(), async () => { throw new Error("never"); }).then((p) => p.pending), null);
});

// ----- reference ---------------------------------------------------------------------------------------
test("sectionTime loops the take clock inside the section at the playback rate", () => {
  const range = { start_s: 4, end_s: 8 };
  assert.equal(sectionTime(0, 0, range, 1), 4);
  assert.equal(sectionTime(1000, 0, range, 1), 5);
  assert.equal(sectionTime(2000, 0, range, 0.5), 5); // half speed: 2 s of take is 1 s of trainer
  assert.equal(sectionTime(4000, 0, range, 1), 4); // wraps at the end
  assert.equal(sectionTime(0, -1000, range, 1), 7); // a negative offset wraps from the end
  assert.equal(sectionTime(500, 0, { start_s: 3, end_s: 3 }, 1), 3);
});

// the team, 2026-11-03: sections never unlocked, because a step counted the old 0 to 100 score (0 on a 47.5% take)
const creditTake = (percent, value = 0) => ({ score: { value, grade: "F", credit: { version: "simon.credit.v1", percent, points: percent * 10,
  max_points: 1000, grade: "B", tolerance: "normal", grades: [[95, "S"], [85, "A"], [75, "B"], [65, "C"], [55, "D"], [40, "E"], [0, "F"]] } } });

test("a step counts the take's credit percent at Standard, the number the result shows; else the job's score", async () => {
  const done = { status: "done", result: { score: 0 } };
  assert.equal(stepScore(done, creditTake(82.6)), 83, "the credit, rounded, not the old score of 0");
  assert.equal(stepScore(done, null), 0, "no analysis: the job's score");
  assert.equal(stepScore({ status: "done", result: { score: 71 } }, { score: { value: 71, grade: "C" } }), 71, "no credit: the score");
  const pend = { ...emptyProgress(), pending: { key: "s1@slow", job: "j1" } };
  const passed = await settlePending(pend, async () => done, async (id) => (id === "j1" ? creditTake(82.6) : null));
  assert.equal(passed.best["s1@slow"], 83);
  assert.ok(isPassed(passed, { key: "s1@slow" }) && 83 >= PASS_SCORE);
  const offline = await settlePending(pend, async () => done, async () => { throw new Error("offline"); });
  assert.equal(offline.best["s1@slow"], 0, "negative: the analysis unreadable, the job's score still counts");
});
