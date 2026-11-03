// The judge's take in 60 s (docs/specs/judge-take.md, TICKET-260): the Quick take preferences, when a take skips the
// details step, and the stage split rows.  node --test tests/part7/judge-take.unit.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { loadPrefs, DEFAULTS, QUICK_TAKE, DURATIONS } from "../../web/countdown.js";
import { autoStarts, stageSplit, secondsText, SPLIT_TEXT } from "../../web/model/judge-take.js";

const store = (value) => ({ getItem: () => value, setItem() {} });

test("AC-3 Quick take: 6 s after 3 s is a duration choice and the submission default; saved choices still win", () => {
  assert.deepEqual(QUICK_TAKE, { countdown: 3, duration: 6 });
  assert.ok(DURATIONS.includes(6));
  assert.deepEqual(loadPrefs(store(null), QUICK_TAKE), QUICK_TAKE);
  assert.deepEqual(loadPrefs(store(null)), DEFAULTS, "negative: the default profile keeps 5 s and 15 s");
  assert.deepEqual(loadPrefs(store(JSON.stringify({ countdown: 10, duration: 30 })), QUICK_TAKE), { countdown: 10, duration: 30 });
});

test("AC-1 auto start: only a follower's one-person clip under the submission profile", () => {
  const one = { person_id: "0", auto: true, count: 1 };
  assert.equal(autoStarts({ role: "follower", mode: "single", choice: one, submission: true }), true);
  assert.equal(autoStarts({ role: "follower", mode: "single", choice: one, submission: false }), false, "default profile keeps the details step");
  assert.equal(autoStarts({ role: "trainer", mode: "single", choice: one, submission: true }), false, "a trainer names the movement");
  assert.equal(autoStarts({ role: "follower", mode: "group", choice: one, submission: true }), false);
  assert.equal(autoStarts({ role: "follower", mode: "single", choice: { person_id: "0", auto: true, count: 2 }, submission: true }), false,
    "AC-2 negative: two people in the clip never start by themselves");
  assert.equal(autoStarts({ role: "follower", mode: "single", choice: { person_id: "1" }, submission: true }), false, "a hand pick is not auto");
  assert.equal(autoStarts({ role: "follower", mode: "single", choice: null, submission: true }), false);
});

test("AC-4 split rows come from the job's timing in log order, with the picker and people seconds", () => {
  const got = stageSplit({ recorded: true, total_s: 102.6, picker: "skipped", people_s: 9.4,
    stages: [{ name: "pose", seconds: 95.8, gpu_wait_s: 1.2 }, { name: "analyse", seconds: 6.3 }, { name: "mystery", seconds: 0.5 }] });
  assert.equal(got.recorded, true);
  assert.deepEqual(got.rows.map((r) => [r.key, r.label, r.value]), [
    ["picker", SPLIT_TEXT.pickerSkipped, ""], ["people", "Finding people", "9.4 s"], ["stage-pose", "Pose", "1 min 36 s"],
    ["stage-analyse", "Analyse", "6.3 s"], ["stage-mystery", "mystery", "0.5 s"], ["total", SPLIT_TEXT.total, "1 min 43 s"]]);
  assert.equal(stageSplit({ recorded: true, total_s: 5, picker: "shown", stages: [{ name: "pose", seconds: 5 }] }).rows[0].label, SPLIT_TEXT.pickerShown);
});

test("AC-4 negative: an old job says 'Timing not recorded', never zeros; no timing field shows nothing", () => {
  for (const timing of [{ recorded: false }, { recorded: true, stages: [] }]) {
    const got = stageSplit(timing);
    assert.equal(got.recorded, false);
    assert.deepEqual(got.rows.map((r) => r.label), ["Timing not recorded"]);
    assert.ok(!got.rows.some((r) => /0\.0 s/.test(r.value)));
  }
  assert.equal(stageSplit(undefined), null);
  assert.equal(stageSplit(null), null);
  assert.equal(secondsText(NaN), "");
  assert.equal(secondsText(-1), "");
});
