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

test("rehab: each test id appears once; entry-<id> stays on the category card", () => {
  const labels = { squat: { tags: ["rehab"] }, misc: { tags: ["rehab"] } };
  const lib = libraryOf(E, { kind: "exercise", labels });
  const ids = lib.sections.flatMap((s) => s.cards.map((c) => c.testId));
  assert.equal(new Set(ids).size, ids.length);
  const card = (key, id) => lib.sections.find((s) => s.key === key).cards.find((c) => c.id === id);
  assert.equal(card("exercise", "squat").testId, "entry-squat");
  assert.equal(card("rehab", "squat").testId, "entry-rehab-squat");
  assert.equal(card("rehab", "misc").testId, "entry-misc", "an uncategorised rehab entry has the one card");
  assert.ok(!lib.sections.some((s) => s.key === "other"), "negative: it is not repeated under More moves");
  const plain = libraryOf(E, { kind: "exercise" }).sections.flatMap((s) => s.cards);
  assert.ok(plain.every((c) => c.testId === `entry-${c.id}`), "without tags every card keeps entry-<id>");
});

test("the submission profile hides the Rehab section, even when rehab was chosen", () => {
  const labels = { squat: { tags: ["rehab"] } };
  const lib = libraryOf(E, { kind: "rehab", labels, showRehab: false });
  assert.ok(!lib.sections.some((s) => s.key === "rehab"));
  assert.equal(lib.sections.at(0).key, "exercise");
});

test("routeAfterKindChange: watch, follow and record pages go to the library; everything else stays (TICKET-186)", async () => {
  const { routeAfterKindChange } = await import("../../web/model/kind.js");
  for (const h of ["#/watch/squat", "#/follow/arm-wave", "#/follow/arm-wave/c/ch1", "#/record", "#/watch/squat?x=1"]) assert.equal(routeAfterKindChange(h), "#/", h);
  for (const h of ["", "#", "#/", "#/result/rj1", "#/result/rj1/0", "#/job/j1", "#/group/g1", "#/me", "#/me/squat", "#/pending", "#/signin", "#/watching", undefined]) assert.equal(routeAfterKindChange(h), null, String(h));
});

test("routeForKindTap: same kind and a held take on record or follow stay; otherwise as routeAfterKindChange (TICKET-193)", async () => {
  const { routeForKindTap } = await import("../../web/model/kind.js");
  assert.equal(routeForKindTap("#/record", { changed: false, holdsTake: false }), null);
  assert.equal(routeForKindTap("#/watch/squat", { changed: false, holdsTake: false }), null);
  assert.equal(routeForKindTap("#/record", { changed: true, holdsTake: true }), null);
  assert.equal(routeForKindTap("#/follow/arm-wave", { changed: true, holdsTake: true }), null);
  assert.equal(routeForKindTap("#/record", { changed: true, holdsTake: false }), "#/");
  assert.equal(routeForKindTap("#/follow/arm-wave", { changed: true, holdsTake: false }), "#/");
  assert.equal(routeForKindTap("#/watch/squat", { changed: true, holdsTake: true }), "#/");
});
