// Frame-stepped render hook (web/cinematic.js, web/flags.js isCinematic, TICKET-267 AC-1, AC-3). The camera path is
// tests/part7/fixtures/camera-path-sample.json, a stand-in in the simon.camera-path.v1 shape until lane/warm-paths lands.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { validatePath, cameraAt, takeTimeAt, frameCount, frameState, installCinematic } from "../../web/cinematic.js";
import { isCinematic, isDebug, profile } from "../../web/flags.js";

const here = path.dirname(fileURLToPath(import.meta.url));
const DOC = JSON.parse(fs.readFileSync(path.join(here, "fixtures/camera-path-sample.json"), "utf8"));

test("AC-1: the same frame index gives the same state, whatever came before", () => {
  const first = frameState(DOC, 4, 60, 6);
  for (const i of [0, 5, 2, 6, 1]) frameState(DOC, i, 60, 6);
  assert.deepEqual(frameState(DOC, 4, 60, 6), first);
});

test("frame time is index over fps and the count covers the last key", () => {
  assert.equal(frameCount(DOC, 60), 7); // keys end at 0.1 s: frames 0..6
  assert.equal(frameState(DOC, 3, 60, 6).t, 0.05);
  assert.deepEqual(cameraAt(DOC, 0.05).position, DOC.keys[1].position);
});

test("the camera holds before the first key and after the last, and eases between keys", () => {
  assert.deepEqual(cameraAt(DOC, -1).position, DOC.keys[0].position);
  assert.deepEqual(cameraAt(DOC, 9).position, DOC.keys[2].position);
  const mid = cameraAt(DOC, 0.025).position; // ease_in_out at k=0.5 is 0.5
  assert.ok(Math.abs(mid[0] - 1.2) < 1e-9);
  assert.equal(cameraAt(DOC, 0.075).fov, 33);
});

const K = (t, take_time) => ({ t, position: [0, 0, 3], target: [0, 0, 0], fov_deg: 36, ...(take_time === undefined ? {} : { take_time }) });

test("take time: absent on every key is real time from 0, clamped to the take", () => {
  const doc = { keys: [K(0), K(2)] };
  assert.equal(takeTimeAt(doc, 1.5, 6), 1.5);
  assert.equal(takeTimeAt(doc, 5, 6), 2); // holds at the last key's value
  assert.equal(takeTimeAt({ keys: [K(0, 5), K(2, 9)] }, 1, 6), 6); // clamped to the duration
});

test("take time: the first key's take_time is the start of real-time playback", () => {
  const doc = { keys: [K(0, 1), K(1), K(2)] };
  assert.equal(takeTimeAt(doc, 0.5, 9), 1.5); // start 1 + t
});

test("take time: slow motion advances the take slower than render time, eased like the camera", () => {
  const doc = { keys: [K(0, 1), K(2, 2)] }; // 2 s of render covers 1 s of take
  assert.equal(takeTimeAt(doc, 1, 9), 1.5);
  const eased = { keys: [{ ...K(0, 1), ease: "ease_in" }, K(2, 2)] };
  assert.equal(takeTimeAt(eased, 1, 9), 1.25); // ease_in at k=0.5 is 0.25
});

test("take time: bullet time holds the take while render time and camera advance", () => {
  const orbit = (t, x, take_time) => ({ ...K(t, take_time), position: [x, 0, 3] });
  const doc = { keys: [orbit(0, 0, 1), orbit(1, 1, 3), orbit(3, 5, 3), orbit(4, 6)] };
  for (const t of [1, 1.5, 2, 3]) assert.equal(takeTimeAt(doc, t, 9), 3);
  assert.equal(frameState(doc, 120, 60, 9).take_s, 3); // render second 2: the take is frozen
  assert.notDeepEqual(frameState(doc, 90, 60, 9).camera, frameState(doc, 150, 60, 9).camera); // while the camera moves
  assert.equal(takeTimeAt(doc, 3.5, 9), 4); // the last key has none: it is start + t = 5, and the take catches up from 3
});

test("a malformed path is refused with the first thing wrong", () => {
  assert.throws(() => validatePath({ ...DOC, schema: "x" }), /schema/);
  assert.throws(() => validatePath({ ...DOC, keys: [] }), /non-empty/);
  assert.throws(() => validatePath({ ...DOC, keys: [DOC.keys[1], DOC.keys[0]] }), /t must rise/);
  assert.throws(() => validatePath({ ...DOC, keys: [{ ...DOC.keys[0], fov_deg: 0 }] }), /fov_deg/);
  assert.throws(() => validatePath({ ...DOC, keys: [{ ...DOC.keys[0], ease: "wobble" }] }), /ease/);
  assert.throws(() => validatePath({ ...DOC, keys: [{ ...DOC.keys[0], take_time: -1 }] }), /take_time/);
  assert.throws(() => validatePath({ ...DOC, keys: [{ ...DOC.keys[0], position: [1, 2] }] }), /position/);
});

function fakeCompare() {
  const calls = [];
  const win = { document: { createElement: () => ({}), head: { append() {} } } };
  const compare = {
    el: { classList: { add() {} } }, duration: 6,
    pause: () => calls.push("pause"), seek: (s) => calls.push(["seek", s]),
    stage: { setFreeCamera: (c) => calls.push(["cam", c]), render: () => calls.push("render") },
  };
  return { calls, win, compare };
}

test("AC-1: step(i) pauses, seeks, sets the camera and draws, identically each time", () => {
  const { calls, win, compare } = fakeCompare();
  const api = installCinematic(compare, win);
  assert.equal(win.__cinematic, api);
  assert.equal(api.load(DOC, 60), 7);
  api.step(3);
  const once = calls.splice(0);
  api.step(6); api.step(3);
  assert.deepEqual(calls.splice(-4), once);
  assert.equal(once.at(-1), "render");
  assert.throws(() => installCinematic(fakeCompare().compare, fakeCompare().win).step(0), /load a camera path/);
});

test("AC-3: ?cinematic is read only by isCinematic; no other flag moves with it", () => {
  assert.equal(isCinematic("?cinematic=1"), true);
  assert.equal(isCinematic("?cinematic=0"), false);
  assert.equal(isCinematic(""), false);
  assert.equal(isDebug("?cinematic=1"), false);
  assert.equal(profile("?cinematic=1", { getItem: () => null, setItem() {}, removeItem() {} }), "default");
});

test("AC-3: only flags.js and result.js read the flag (viewer3d.js names the module in a comment) in the web code", () => {
  const web = path.join(here, "../../web");
  const hits = [];
  const walk = (d) => {
    for (const e of fs.readdirSync(d, { withFileTypes: true })) {
      if (e.name === "vendor" || e.name === "node_modules") continue;
      const p = path.join(d, e.name);
      if (e.isDirectory()) walk(p);
      else if (/\.(js|html)$/.test(e.name) && /cinematic/i.test(fs.readFileSync(p, "utf8"))) hits.push(path.relative(web, p));
    }
  };
  walk(web);
  assert.deepEqual(hits.sort(), ["cinematic.js", "flags.js", "result.js", "viewer3d.js"]);
});
