// The routine library's view model (web/model/library.js) and the kind state (web/model/kind.js).
import test from "node:test";
import assert from "node:assert/strict";
import { libraryOf, durationText, cardOf, matches } from "../../web/model/library.js";
import { kindOfEntry, currentKind, entryInKind } from "../../web/model/kind.js";

const E = [
  { id: "squat", name: "Squat", category: "exercise", duration_ms: 120000, files_source: "fixture" },
  { id: "wave", name: "Arm wave", category: "dance", duration_ms: 15000, video_uri: "video.mp4" },
  { id: "misc", name: "Stretch" },
];
const mem = (v) => ({ getItem: () => v, setItem() {} });

test("the chosen kind's section comes first; uncategorised entries go last", () => {
  const lib = libraryOf(E, { kind: "dance" });
  assert.deepEqual(lib.sections.map((s) => s.key), ["dance", "exercise", "other"]); // rehab: nothing tagged, not chosen
  assert.equal(lib.sections.at(0).cards.at(0).id, "wave");
  assert.equal(libraryOf(E, { kind: "exercise" }).sections.at(0).key, "exercise");
});

test("cards carry duration, links and video", () => {
  const c = cardOf(E.at(1));
  assert.equal(c.duration, "0:15");
  assert.equal(c.followHref, "#/follow/wave");
  assert.ok(c.hasVideo && c.videoUrl.endsWith("/video.mp4"));
  assert.equal(durationText(120000), "2:00");
  assert.equal(durationText(undefined), "");
});

test("statuses: loading, empty, no match", () => {
  assert.equal(libraryOf([], { loading: true }).status.kind, "loading");
  assert.equal(libraryOf([]).status.kind, "empty");
  assert.equal(libraryOf(E, { query: "salsa" }).status.kind, "no-match");
  assert.ok(matches(E.at(0), "squ"));
});

test("kind: category maps, stored dance reads dance, anything else exercise", () => {
  assert.equal(kindOfEntry(E.at(1)), "dance");
  assert.equal(kindOfEntry(E.at(2)), null);
  assert.equal(currentKind(mem("dance")), "dance");
  assert.equal(currentKind(mem("rehab")), "rehab");
  assert.equal(currentKind(mem("fitness")), "exercise");
  assert.equal(currentKind(mem(null)), "exercise");
});

test("rehab: tagged entries show under Rehab, first when chosen, and still under their category", () => {
  const labels = { squat: { tags: ["rehab"] } };
  assert.ok(entryInKind(E.at(0), "rehab", labels));
  const lib = libraryOf(E, { kind: "rehab", labels });
  assert.deepEqual(lib.sections.map((s) => s.key), ["rehab", "exercise", "dance", "other"]);
  assert.equal(lib.sections.at(0).cards.at(0).id, "squat");
  assert.equal(libraryOf(E, { kind: "rehab" }).sections.at(0).key, "rehab"); // chosen: shown even when empty
});
