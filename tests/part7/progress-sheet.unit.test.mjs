// The progress sheet's model (web/model/progress-sheet.js, TICKET-283): calendar, trend, replay frames, the share body, and the
// copy scan of AC-3 over every word the sheet can show (the browser test scans the drawn pages too).
//   node --test tests/part7/progress-sheet.unit.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { TEXT, BANNED, bannedIn, calendar, trend, pose, frameAt, viewModel, shareBody, offersSheet, pageHash, programmeHash, MAX_WEEKS } from "../../web/model/progress-sheet.js";
import { kindWord } from "../../web/model/share.js";

const DAYS = [
  { day: "2026-10-27", sessions: 1, peak_deg: 40.2 },
  { day: "2026-10-28", sessions: 2, peak_deg: 52.3 },
  { day: "2026-10-30", sessions: 1, peak_deg: null },
  { day: "2026-11-01", sessions: 1, peak_deg: 61 },
];

/** Every string TEXT can produce, the functions called with sample values. */
const allCopy = () => Object.values(TEXT).flatMap((v) => (typeof v === "function" ? [v(1, 1), v(3, 2), v("left knee bend"), v(null), v(4.5)] : [v]));

test("AC-3: no advice verb, judgement or medical term anywhere in the sheet's words", () => {
  for (const line of [...allCopy(), kindWord("progress_sheet")]) assert.deepEqual(bannedIn(line), [], line);
  for (const word of ["should", "safe", "recommend", "increase", "decrease"]) assert.ok(BANNED.includes(word), word);
});

test("AC-3: the scan catches advice, judgement and medical words (negative)", () => {
  assert.deepEqual(bannedIn("You should bend more"), ["should"]);
  assert.deepEqual(bannedIn("Safe range"), ["safe"]);
  assert.deepEqual(bannedIn("We recommend you increase the reps"), ["recommend", "increase"]);
  assert.ok(bannedIn("Good work, next time decrease the pace").includes("next"));
  assert.ok(bannedIn("After the injury, mind the pain").includes("pain"));
  assert.ok(bannedIn("Medical advice from your physio").includes("medical"));
  assert.ok(bannedIn("Your coach says").includes("coach"));
});

test("no dash stands in for punctuation in the copy", () => {
  for (const line of allCopy()) assert.equal(/[\u2013\u2014]| - /.test(String(line)), false, line);
});

test("the calendar runs Monday to Sunday from the first to the last session week", () => {
  const weeks = calendar(DAYS);
  assert.equal(weeks.length, 1);
  assert.equal(weeks[0].cells[0].day, "2026-10-26"); // a Monday
  assert.equal(weeks[0].cells[6].day, "2026-11-01"); // a Sunday
  assert.equal(calendar([...DAYS, { day: "2026-11-02", sessions: 1 }]).length, 2, "a Monday session opens a new week");
  const cell = weeks[0].cells.find((c) => c.day === "2026-10-28");
  assert.equal(cell.sessions, 2);
  assert.equal(cell.label, "28 Oct 2026: 2");
  assert.deepEqual(calendar([]), []);
  const long = calendar([{ day: "2026-01-05", sessions: 1 }, { day: "2026-11-01", sessions: 1 }]);
  assert.equal(long.length, MAX_WEEKS, "only the last twelve weeks");
});

test("the trend puts days by date, leaves out unmeasured days and scales to the top ten", () => {
  const c = trend(DAYS);
  assert.equal(c.top, 70);
  assert.deepEqual(c.dots.map((d) => d.value), [40, 52, 61]);
  assert.equal(c.bars.length, 4);
  assert.ok(c.dots[0].x < c.dots[1].x && c.dots[1].x < c.dots[2].x);
  assert.ok(c.dots[2].y < c.dots[0].y, "more degrees sit higher");
  assert.match(c.path, /^M[\d.]+ [\d.]+ L/);
  assert.equal(c.label, "Degrees reached from 40 to 61, 4 days");
  assert.equal(trend([{ day: "2026-11-02", sessions: 5, peak_deg: 115.5 }]).label, "Degrees reached from 116 to 116, 1 day", "staging 2026-11-02: one day reads singular");
  assert.equal(trend([]), null);
  assert.equal(trend([{ day: "2026-11-01", sessions: 1, peak_deg: null }]).label, TEXT.trendNone);
});

test("a replay frame draws bones whose two ends are seen and loops in time", () => {
  const skel = { bones: [[0, 1], [1, 2]], t: [0, 0.1, 0.2], frames: [[[0, 0], [0.5, 0.5], null], [[0, 0], [1, 1], [0.5, 1]], [[0, 0], [1, 1], [1, 1]]] };
  assert.deepEqual(pose(skel, 0, 100), { lines: [[0, 0, 50, 50]], dots: [[0, 0], [50, 50]] });
  assert.equal(pose(skel, 1, 100).lines.length, 2);
  assert.deepEqual(pose(skel, 9, 100), { lines: [], dots: [] });
  assert.equal(frameAt(skel, 0.15), 1);
  assert.equal(frameAt(skel, 0.25), 0, "0.25 s loops back past the 0.2 s end");
  assert.equal(frameAt({ t: [] }, 1), 0);
});

test("the view model states measured numbers only and starts the replay on the peak", () => {
  const vm = viewModel({ title: "Sit to stand", measure_label: "left knee bend", error: { deg: null }, days: DAYS,
    takes: [{ at: "2026-10-27T09:00:00Z", reps: 5, peak_deg: 40.2, tempo_ratio: 1.234 }, { at: "2026-11-01T09:00:00Z", reps: null, peak_deg: null, tempo_ratio: null }],
    skeleton: { frames: [[[0, 0]]], bones: [], t: [0], peak_frame: 0 }, skeleton_on: "2026-11-01T09:00:00Z", synthetic: false });
  assert.equal(vm.measure, "Measured: left knee bend");
  assert.equal(vm.error, "Angle accuracy: not yet validated against a measured reference.");
  assert.equal(vm.totals, "2 sessions on 4 days");
  assert.deepEqual(vm.rows[1], { day: "27 Oct 2026", reps: "5", peak: "40 degrees", tempo: "1.23 x" });
  assert.deepEqual(vm.rows[0], { day: "1 Nov 2026", reps: "Not measured", peak: "Not measured", tempo: "Not measured" });
  assert.equal(viewModel({ error: { deg: 4 } }).error, "Angle accuracy: within 4 degrees on a measured reference.");
  assert.equal(viewModel(null).measure, TEXT.notMeasured);
  assert.equal(viewModel(null).skeleton, null);
  for (const row of vm.rows) for (const v of Object.values(row)) assert.deepEqual(bannedIn(v), []);
});

test("sharing asks for no name and no clip; links and the history offer", () => {
  assert.deepEqual(shareBody("squat-1"), { kind: "progress_sheet", item_ref: "squat-1", show_name: false, show_clip: false, days: 30, confirm: true });
  assert.equal(pageHash("a b"), "#/me/a%20b/progress");
  assert.equal(programmeHash("sit-1"), "#/follow/sit-1");
  assert.equal(offersSheet({ takes: [{ mode: "fitness" }, { mode: "rehab" }] }), true);
  assert.equal(offersSheet({ takes: [{ mode: "fitness" }] }), false);
  assert.equal(offersSheet(null), false);
  assert.equal(kindWord("progress_sheet"), "Progress sheet");
  assert.equal(kindWord("take_result"), "Result");
});
