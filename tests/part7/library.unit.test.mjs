// The routine library's view model (web/model/library.js) and the kind state (web/model/kind.js).
import test from "node:test";
import assert from "node:assert/strict";
import { durationText, cardOf, matches } from "../../web/model/library.js";
import * as kindModule from "../../web/model/kind.js";
import { kindOfEntry, kindForMode, entryInKind } from "../../web/model/kind.js";

const E = [
  { id: "squat", name: "Squat", category: "exercise", duration_ms: 120000, files_source: "fixture" },
  { id: "wave", name: "Arm wave", category: "dance", duration_ms: 15000, video_uri: "video.mp4" },
  { id: "misc", name: "Stretch" },
];

test("cards carry duration, links and video", () => {
  const c = cardOf(E.at(1));
  assert.equal(c.duration, "0:15");
  assert.equal(c.followHref, "#/follow/wave");
  assert.ok(c.hasVideo && c.videoUrl.endsWith("/video.mp4"));
  assert.equal(durationText(120000), "2:00");
  assert.equal(durationText(undefined), "");
});

test("kind: an entry's category and a take's mode name the kind; no stored choice is read (TICKET-436)", () => {
  assert.equal(kindOfEntry(E.at(1)), "dance");
  assert.equal(kindOfEntry(E.at(2)), null);
  assert.equal(kindForMode("dance"), "dance");
  assert.equal(kindForMode("rehab"), "rehab");
  assert.equal(kindForMode("fitness"), "exercise");
  assert.equal(kindForMode(undefined), null);
  for (const gone of ["currentKind", "setKind", "onKindChange", "routeAfterKindChange", "routeForKindTap", "KIND_EVENT"]) {
    assert.equal(kindModule[gone], undefined, `${gone} left with the header switch`);
  }
});

test("a search matches the name, category, id and tags", () => {
  assert.ok(matches(E.at(0), "squ"));
  assert.ok(matches(E.at(2), "stretch"));
  assert.ok(!matches(E.at(0), "salsa"));
  assert.ok(matches(E.at(2), "gentle", { misc: { tags: ["gentle"] } }));
});

test("rehab: tagged entries are of the rehab kind", () => {
  assert.ok(entryInKind(E.at(0), "rehab", { squat: { tags: ["rehab"] } }));
  assert.ok(!entryInKind(E.at(0), "rehab", {}));
});
