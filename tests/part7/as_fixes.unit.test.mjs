// Pure logic of the auth-social fixes: the profile summary lines (TICKET-231 AC-6), the follow default mode (AC-4),
// the share ticks and the created date (TICKET-233), the entry author URL (TICKET-232 AC-3).
import test from "node:test";
import assert from "node:assert/strict";
import { summaryLines, defaultModeFrom, entryRows, cappedLine, TEXT as PROFILE_TEXT } from "../../web/model/profile.js";
import { createBody, createdText, TEXT } from "../../web/model/share.js";
import { authorUrl } from "../../web/model/teacher.js";

const group = { section: "full", mode: "rehab", score_version: "simon.score.v2:e818635b", takes: 3, movements: 2, first_score: 60, latest_score: 72, came_back: 1 };

test("the summary words each like-with-like group with its first and latest score", () => {
  const [line] = summaryLines({ summary: { kept: true, groups: [group] } }, null);
  assert.equal(line, "Whole movement, rehab mode: 3 takes of 2 movements. First score 60, latest 72. 1 measure came back.");
});

test("a part of the movement and a single take are worded plainly", () => {
  const one = { ...group, section: "s2of4", takes: 1, movements: 1, first_score: 55, latest_score: 55, came_back: 0 };
  assert.equal(summaryLines({ summary: { kept: true, groups: [one] } }, null)[0], "Part 2 of 4, rehab mode: 1 take of 1 movement. First score 55, latest 55.");
});

test("the score version is named only where two groups share a section and a mode", () => {
  const lines = summaryLines({ summary: { kept: true, groups: [group, { ...group, score_version: "simon.score.v3:00000000" }] } }, null);
  assert.ok(lines.every((l) => l.includes("Score version")), lines.join(" | "));
});

test("nothing kept gives no lines (the page says so), not zeros", () => {
  assert.deepEqual(summaryLines({ summary: { kept: false, groups: [] } }, null), []);
  assert.deepEqual(summaryLines({ summary: { kept: false, groups: [] } }, { entries: [{ takes: 4 }] }), [], "negative: the history count is not used when the server says nothing is kept");
});

test("entries come from the profile answer with a count and the last date", () => {
  const [row] = entryRows({ entries: [{ entry_id: "squat", name: "Squat", count: 2, last_at: "2026-11-01T10:00:00Z" }] });
  assert.equal(row.name, "Squat");
  assert.match(row.line, /^2 takes, last /);
});

test("the follow default is the first saved mode that is valid", () => {
  const valid = (m) => ["dance", "rehab", "fitness"].includes(m);
  assert.equal(defaultModeFrom({ modes: ["rehab", "dance"] }, valid), "rehab");
  assert.equal(defaultModeFrom({ modes: ["nonsense", "dance"] }, valid), "dance");
  assert.equal(defaultModeFrom({ modes: [] }, valid), null);
  assert.equal(defaultModeFrom(null, valid), null);
  assert.equal(defaultModeFrom({ modes: ["rehab"] }, () => false), null, "no mode is valid in the submission profile");
});

test("share body: score and faults are always in, so the body never carries a tick for them", () => {
  assert.equal("include_score" in createBody({ kind: "take_result", itemRef: "a" }), false);
  assert.equal("include_faults" in createBody({ kind: "take_result", itemRef: "a", includeFaults: false }), false);
});

test("the share list shows the day a link was made", () => {
  assert.equal(createdText({ created_utc: "2026-11-01T10:00:00Z" }), "Made 1 Nov 2026");
  assert.equal(createdText({}), "");
  assert.ok(TEXT.revokeAll && TEXT.revokeAllSure && TEXT.revokeAllYes && TEXT.revokeAllNo && TEXT.revokedAll);
});

test("the author line URL is the light route", () => {
  assert.equal(authorUrl("a b"), "api/teacher/a%20b/author");
});

test("the cap line shows only when the server says the counts are capped", () => {
  assert.equal(PROFILE_TEXT.capped, "Counts cover your latest 200 takes.");
  assert.equal(cappedLine({ summary: { kept: true, groups: [], capped: true } }), PROFILE_TEXT.capped);
  assert.equal(cappedLine({ summary: { kept: true, groups: [], capped: false } }), "");
  assert.equal(cappedLine({}), "");
});
