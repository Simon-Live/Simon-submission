// Build line formatting (app.md AC-A15, AC-A16).   node --test tests/part7/build.unit.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { formatUtc, buildLine, buildDetails } from "../../web/build.js";

test("time is written in UTC whatever the zone", () => {
  assert.equal(formatUtc("2026-10-30T16:50:12Z"), "30 Oct 2026, 16:50 UTC");
  assert.equal(formatUtc("2026-01-02T03:04:00+02:00"), "2 Jan 2026, 01:04 UTC");
  assert.equal(formatUtc("unknown"), "");
});

test("build line shows the short sha and the update time", () => {
  assert.equal(buildLine({ short: "d0f339ab6", started_at: "2026-10-30T16:50:00Z" }),
    "Build d0f339ab6 · updated 30 Oct 2026, 16:50 UTC");
});

test("unknown build degrades to plain words", () => {
  assert.equal(buildLine({ short: "unknown", started_at: "unknown" }), "Build not known");
  assert.equal(buildLine(null), "Build not known");
  assert.equal(buildLine({ short: "unknown", started_at: "2026-10-30T16:50:00Z" }),
    "Build not known · updated 30 Oct 2026, 16:50 UTC");
});

test("phone form drops the year and keeps UTC", () => {
  const line = buildLine({ short: "7d8b42438", started_at: "2026-10-31T04:12:00Z" }, { year: false });
  assert.equal(line, "Build 7d8b42438 \u00b7 updated 31 Oct, 04:12 UTC");
  assert.ok(line.length <= 46);
});

test("details give the full update date first", () => {
  const rows = buildDetails({ started_at: "2026-10-31T04:12:00Z", committed_at: "unknown", parts: {} });
  assert.deepEqual(rows, [["Updated", "31 Oct 2026, 04:12 UTC"]]);
});

test("details list the commit time and every pinned part", () => {
  const rows = buildDetails({ committed_at: "2026-10-30T15:00:00Z", parts: { 1: "aaaaaaaaa", 2: "bbbbbbbbb" } });
  assert.deepEqual(rows, [["Commit made", "30 Oct 2026, 15:00 UTC"], ["Part 1", "aaaaaaaaa"], ["Part 2", "bbbbbbbbb"]]);
  assert.deepEqual(buildDetails({ committed_at: "unknown", parts: {} }), []);
});
