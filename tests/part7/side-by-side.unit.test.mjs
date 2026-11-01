// Side by side on the results screen (web/model/side-by-side.js): clock, drift and sound. Run: node --test tests/part7/
import test from "node:test";
import assert from "node:assert/strict";
import { DRIFT_S, SOUND, clockOf, span, targetTime, correction, hasSound, mutes, clockLabel } from "../../web/model/side-by-side.js";

test("the longer video is the clock; the trainer on a tie or an unknown length", () => {
  assert.equal(clockOf(10, 12), SOUND.you);
  assert.equal(clockOf(12, 10), SOUND.trainer);
  assert.equal(clockOf(10, 10), SOUND.trainer);
  assert.equal(clockOf(NaN, NaN), SOUND.trainer);
  assert.equal(span(10, 12.5), 12.5);
  assert.equal(span(NaN, 3), 3);
});

test("a shorter video holds its last frame once the clock passes its end", () => {
  assert.equal(targetTime(4, 10), 4);
  assert.ok(Math.abs(targetTime(11, 10) - 9.95) < 1e-9);
  assert.equal(targetTime(-1, 10), 0);
});

test("a drift past DRIFT_S is corrected, a small one is left alone", () => {
  assert.equal(correction(5, 5 + DRIFT_S / 2, 10), null);
  assert.equal(correction(5, 5.6, 10), 5);
  assert.ok(Math.abs(correction(12, 3, 10) - 9.95) < 1e-9);
});

test("exactly one video plays sound, and the trainer when the follower has none", () => {
  assert.deepEqual(mutes(SOUND.trainer, true), { trainer: false, you: true });
  assert.deepEqual(mutes(SOUND.you, true), { trainer: true, you: false });
  assert.deepEqual(mutes(SOUND.you, false), { trainer: false, you: true });
});

test("a sound track is read from any one browser field", () => {
  assert.equal(hasSound({}), false);
  assert.equal(hasSound({ mozHasAudio: true }), true);
  assert.equal(hasSound({ audioTracks: 1 }), true);
  assert.equal(hasSound({ decodedBytes: 2048 }), true);
  assert.equal(hasSound({ mozHasAudio: false, audioTracks: 0, decodedBytes: 0 }), false);
});

test("the clock label reads minutes and seconds", () => {
  assert.equal(clockLabel(7.9, 72), "0:07 / 1:12");
  assert.equal(clockLabel(NaN, 0), "0:00 / 0:00");
});
