// TICKET-309: a 400 shows the server's own sentence; "not a video" is only the fallback when the server gave none.
//   node --test tests/part7/api-message.unit.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { messageFor } from "../../web/api.js";

const NOT_VIDEO = "This file is not a video. Pick an MP4 or WebM file.";

test("a 400 with a reason shows the reason", () => {
  const said = "The selection must start before it ends, inside the video.";
  assert.equal(messageFor(400, { error: said }), said);
});

test("a real non-video still reads as not a video", () => {
  assert.equal(messageFor(400, { error: NOT_VIDEO }), NOT_VIDEO);
});

test("a 400 with no reason falls back to not a video", () => {
  assert.equal(messageFor(400, null), NOT_VIDEO);
  assert.equal(messageFor(400, {}), NOT_VIDEO);
  assert.equal(messageFor(400, { error: 7 }), NOT_VIDEO);
});

test("other statuses keep their mapping", () => {
  assert.equal(messageFor(429, { error: "anything" }), "You have used today's analyses. Try again tomorrow.");
  assert.equal(messageFor(404, { error: "anything" }), "This movement is not in the catalog.");
});
