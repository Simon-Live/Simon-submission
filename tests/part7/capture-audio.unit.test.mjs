// Trainer capture asks for sound, follower capture does not; a refused microphone falls back to video only.
import test from "node:test";
import assert from "node:assert/strict";
import { requestStream, pickMimeType, MIME_ORDER_AUDIO, AUDIO_OFF_HINT } from "../../web/capture.js";

const track = (kind) => ({ kind });
const streamOf = (audio) => ({ getAudioTracks: () => (audio ? [track("audio")] : []) });
function devices({ refuseAudio = false, refuseAll = false } = {}) {
  const calls = [];
  return {
    calls,
    async getUserMedia(c) {
      calls.push(c);
      if (refuseAll) throw Object.assign(new Error("no"), { name: "NotAllowedError" });
      if (c.audio && refuseAudio) throw Object.assign(new Error("no mic"), { name: "NotAllowedError" });
      return streamOf(Boolean(c.audio));
    },
  };
}

test("trainer capture asks for audio", async () => {
  const md = devices();
  const got = await requestStream(md, true);
  assert.equal(md.calls.length, 1);
  assert.equal(md.calls[0].audio, true);
  assert.equal(got.audioOff, false);
});

test("follow capture asks for no audio", async () => {
  const md = devices();
  const got = await requestStream(md, false);
  assert.equal(md.calls.length, 1);
  assert.equal(md.calls[0].audio, false);
  assert.equal(got.audioOff, false);
});

test("a refused microphone falls back to video only and says so", async () => {
  const md = devices({ refuseAudio: true });
  const got = await requestStream(md, true);
  assert.deepEqual(md.calls.map((c) => c.audio), [true, false]);
  assert.equal(got.audioOff, true);
  assert.equal(got.audioError.name, "NotAllowedError");
  assert.match(AUDIO_OFF_HINT, /microphone is off/);
});

test("a refused camera still fails", async () => {
  await assert.rejects(requestStream(devices({ refuseAll: true }), true), /no/);
});

test("the mime list with audio names opus and honours isTypeSupported", () => {
  assert.ok(MIME_ORDER_AUDIO.slice(0, 3).every((t) => t.includes("opus")));
  const MR = { isTypeSupported: (t) => t === "video/webm;codecs=vp8,opus" };
  assert.equal(pickMimeType(MR, true), "video/webm;codecs=vp8,opus");
  assert.equal(pickMimeType({ isTypeSupported: (t) => t === "video/webm" }, true), "video/webm");
  assert.equal(pickMimeType({ isTypeSupported: (t) => t === "video/webm;codecs=vp9" }, false), "video/webm;codecs=vp9");
  assert.equal(pickMimeType({ isTypeSupported: () => false }, true), "");
});
