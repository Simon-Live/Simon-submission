// Unit tests for the pure parts of the teacher page: chart geometry, labels, dates, URL.   node --test tests/part7/
import test from "node:test";
import assert from "node:assert/strict";
import { chartModel, chartLabel, formatAt, cueShare, plural, teacherUrl, teacherView, toneOf, CHART } from "../../web/model/teacher.js";

const T = (score, grade = "B") => ({ score, grade });

test("the chart has no points and no line without takes", () => {
  for (const input of [[], undefined, null, [{ score: "x" }, null]]) {
    const m = chartModel(input);
    assert.deepEqual(m.points, []);
    assert.equal(m.path, "");
  }
});

test("one take is a dot in the middle with no line", () => {
  const m = chartModel([T(50)]);
  assert.equal(m.points.length, 1);
  assert.equal(m.path, "");
  assert.equal(m.points[0].x, CHART.left + (CHART.width - CHART.left - CHART.right) / 2);
});

test("scores sit on a fixed 0 to 100 scale and x runs oldest to newest", () => {
  const m = chartModel([T(0, "F"), T(100, "A"), T(50, "C")]);
  const bottom = CHART.height - CHART.bottom;
  assert.equal(m.points[0].y, bottom);
  assert.equal(m.points[1].y, CHART.top);
  assert.ok(m.points[0].x < m.points[1].x && m.points[1].x < m.points[2].x);
  assert.equal(m.points[0].x, CHART.left);
  assert.equal(m.points[2].x, CHART.width - CHART.right);
  assert.match(m.path, /^M[\d.]+ [\d.]+ L[\d.]+ [\d.]+ L[\d.]+ [\d.]+$/);
  assert.deepEqual(m.ticks.map((t) => t.value), [0, 50, 100]);
});

test("a score outside 0 to 100 is drawn on the edge, not off the chart", () => {
  const m = chartModel([T(140), T(-5)]);
  assert.equal(m.points[0].y, CHART.top);
  assert.equal(m.points[1].y, CHART.height - CHART.bottom);
});

test("the chart label says the count, first, last, lowest and highest", () => {
  assert.equal(chartLabel([]), "No scores yet.");
  assert.equal(chartLabel([T(64)]), "One score: 64.");
  assert.equal(chartLabel([T(60), T(90), T(75)]), "3 scores, oldest to newest, from 60 to 75. Lowest 60, highest 90.");
});

test("dates read the same in a given zone and are empty when unusable", () => {
  assert.equal(formatAt("2026-10-31T10:05:00Z", "UTC"), "Oct 31, 10:05 AM");
  assert.equal(formatAt("", "UTC"), "");
  assert.equal(formatAt("not a date", "UTC"), "");
  assert.equal(formatAt(undefined, "UTC"), "");
});

test("cue share and plural wording", () => {
  assert.equal(cueShare(1, 1), "in 1 of 1 take");
  assert.equal(cueShare(2, 3), "in 2 of 3 takes");
  assert.equal(plural(0, "take", "takes"), "0 takes");
});

test("the entry id is encoded into the api path", () => {
  assert.equal(teacherUrl("body-squat-19b06562"), "api/teacher/body-squat-19b06562");
  assert.equal(teacherUrl("a/b ?"), "api/teacher/a%2Fb%20%3F");
});

test("the view model: newest take first, cue shares, tones, empty flag, name fallback", () => {
  const doc = {
    takes: [{ score: 60, grade: "D", at: "2026-10-30T09:00:00Z", top_cues: ["a", "b"] }, { score: 90, grade: "A", at: "2026-10-31T09:00:00Z", top_cues: [] }],
    cue_counts: [{ text: "a", count: 1 }],
  };
  const vm = teacherView(doc, { name: "Side raise" }, "side-raise");
  assert.equal(vm.name, "Side raise");
  assert.equal(vm.empty, false);
  assert.equal(vm.summary, "2 takes from people who followed it");
  assert.deepEqual(vm.takes.map((t) => [t.score, t.tone, t.cues]), [["90", "good", "No cues in this take"], ["60", "warn", "a, b"]]);
  assert.deepEqual(vm.cues, [{ text: "a", share: "in 1 of 2 takes" }]);
  assert.equal(vm.chart.points.length, 2);
  const empty = teacherView({ takes: [], cue_counts: [] }, null, "quiet-move");
  assert.equal(empty.empty, true);
  assert.equal(empty.name, "quiet-move");
  assert.equal(teacherView(null, null, "x").empty, true);
  assert.deepEqual(["A", "B", "C", "D", "F", "?"].map(toneOf), ["good", "good", "warn", "warn", "bad", "warn"]);
});
