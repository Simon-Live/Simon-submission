// Unit tests for model/capture-chrome.js: the labels of the follow screen's chrome. `node --test`.
import test from "node:test";
import assert from "node:assert/strict";
import { captureChromeOf, CAPTURE_TEXT } from "../../web/model/capture-chrome.js";

test("following a movement: its title, length, and Watch with Pause for playing it in place", () => {
  const m = captureChromeOf({ kind: "exercise", entry: { id: "high knees", name: "High knees class", duration_ms: 16000 } });
  assert.equal(m.title, "High knees class");
  assert.equal(m.watchLabel, CAPTURE_TEXT.watch);
  assert.equal(m.pauseLabel, CAPTURE_TEXT.pause);
  assert.equal(m.watchHref, "#/watch/high%20knees", "the link stays for a reference with no video");
});

test("recording a new movement: no title and no Watch", () => {
  const m = captureChromeOf({ kind: "dance", entry: null });
  assert.equal(m.title, null);
  assert.equal(m.watchHref, null);
});
