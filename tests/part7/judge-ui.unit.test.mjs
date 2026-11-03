// TICKET-316: the submission profile lists only movements with a trainer video; "Your followers" is the owner's alone;
// the two sharing buttons carry different labels.   node --test tests/part7/judge-ui.unit.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { judgeListed, hasTrainerVideo } from "../../web/judge-catalog.js";
import { visible } from "../../web/catalog.js";
import { isOwner } from "../../web/owner-link.js";
import { LABELS, relabelActions } from "../../web/judge-actions.js";
import { hideStaticTimes } from "../../web/job-eta.js";

const E = [
  { id: "squat", name: "Squat" },
  { id: "arm-wave", name: "Arm wave", video_uri: "video.mp4" },
  { id: "hip-twist", name: "Hip twist", video_uri: null },
  { id: "forward-lunge", name: "Forward lunge", video_uri: "video.webm" },
];

test("submission profile: an entry without a trainer video is hidden from the list", () => {
  const ids = visible(judgeListed(E, { submission: true }), {}, { curatedOnly: true }).map((e) => e.id);
  assert.deepEqual(ids, ["arm-wave", "forward-lunge"]);
  assert.ok(!ids.includes("squat") && !ids.includes("hip-twist"));
});

test("negative: entries with a video are still listed, and the default profile lists all", () => {
  assert.ok(judgeListed(E, { submission: true }).every(hasTrainerVideo));
  assert.equal(judgeListed(E, { submission: false }).length, 4);
});

test("a signed-in owner still sees their own entry without a video", () => {
  const ids = judgeListed(E, { submission: true, owned: new Set(["squat"]) }).map((e) => e.id);
  assert.ok(ids.includes("squat"));
  assert.ok(!ids.includes("hip-twist"));
});

test("Your followers: shown only when the server says the viewer owns the movement", () => {
  assert.equal(isOwner({ attribution: { mine: true } }), true);
  assert.equal(isOwner({ attribution: { mine: false } }), false);
  assert.equal(isOwner({ attribution: { kind: "entry" } }), false);
  assert.equal(isOwner(null), false);
});

test("the Share and Challenge buttons get different labels", () => {
  const actions = relabelActions({ share: { textContent: "Share" }, challenge: { textContent: "Challenge a friend" } });
  assert.equal(actions.share.textContent, LABELS.share);
  assert.equal(actions.challenge.textContent, LABELS.challenge);
  assert.notEqual(LABELS.share, LABELS.challenge);
});

test("hideStaticTimes strips only the 'Usually' text, and only while a time shows", () => {
  const mk = () => ({ detail: { textContent: "Finding the joints. Usually about 1 to 3 min." }, list: { setAttribute(k, v) { this[k] = v; } } });
  const a = mk();
  hideStaticTimes({ ...a, shown: true });
  assert.equal(a.detail.textContent, "Finding the joints.");
  const b = mk();
  hideStaticTimes({ ...b, shown: false });
  assert.match(b.detail.textContent, /Usually about/);
});
