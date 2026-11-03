// docs/specs/any-body.md: which bodies show, how they page on a phone, which frame every figure draws, and the copy.
// No DOM and no three: node --test tests/part7/any-body.unit.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { bodiesFor, perView, pagesOf, poseAt, slotError, TEXT, MAX_FIGURES } from "../../web/model/any-body.js";

const lib = (id, name) => ({ id, name, kind: "library", status: "ready" });
const mine = (id, name, status = "ready") => ({ id, name, kind: "upload", status });
const LIBRARY = [lib("ual2-mannequin-f", "Mannequin (female)"), lib("ual1-mannequin", "Mannequin"), lib("rigged-figure", "Rigged Figure")];

test("Person first, then the three built-in bodies: four figures", () => {
  const b = bodiesFor(LIBRARY);
  assert.deepEqual(b.map((x) => x.choice), ["person", "lib:ual2-mannequin-f", "lib:ual1-mannequin", "lib:rigged-figure"]);
  assert.deepEqual(b.map((x) => x.name), ["Person", "Mannequin (female)", "Mannequin", "Rigged Figure"]);
  assert.equal(b[0].entry, null);
});

test("the caller's own models are never left out, and the row never passes four", () => {
  const b = bodiesFor([...LIBRARY, mine("a".repeat(32), "My model")]);
  assert.equal(b.length, MAX_FIGURES);
  assert.deepEqual(b.map((x) => x.name), ["Person", "Mannequin (female)", "Mannequin", "My model"]);
  const many = bodiesFor([...LIBRARY, mine("a", "One"), mine("b", "Two"), mine("c", "Three")]);
  assert.equal(many.length, MAX_FIGURES);
  assert.equal(many[1].name, "Mannequin (female)");
  assert.deepEqual(many.slice(2).map((x) => x.choice), ["up:a", "up:b"]);
});

test("a model still converting, a generated avatar and a record without a name are not shown", () => {
  const b = bodiesFor([...LIBRARY.slice(0, 1), mine("a", "Busy", "queued"), { id: "g", name: "Mine", kind: "generated", status: "ready" }, { id: "x" }, null]);
  assert.deepEqual(b.map((x) => x.choice), ["person", "lib:ual2-mannequin-f"]);
  assert.deepEqual(bodiesFor([]).map((x) => x.choice), ["person"]);
  assert.deepEqual(bodiesFor(undefined).map((x) => x.choice), ["person"]);
});

test("a phone shows two figures, a desktop four, never more than there are", () => {
  assert.equal(perView(412), 2);
  assert.equal(perView(600), 2);
  assert.equal(perView(1280), 4);
  assert.equal(perView(1280, 3), 3);
  assert.equal(perView(412, 1), 1);
});

test("pages of figures", () => {
  assert.deepEqual(pagesOf(4, 2), [[0, 1], [2, 3]]);
  assert.deepEqual(pagesOf(3, 2), [[0, 1], [2]]);
  assert.deepEqual(pagesOf(4, 4), [[0, 1, 2, 3]]);
  assert.deepEqual(pagesOf(0, 2), []);
});

const model = (n = 10) => ({
  fps: 10, duration: (n - 1) / 10,
  follower: Array.from({ length: n }, (_, i) => [[i, 0, 0]]),
  followerUnseen: Array.from({ length: n }, (_, i) => (i === 3 ? [0] : [])),
});

test("every figure draws the same frame at the same clock time", () => {
  const m = model();
  for (const t of [0, 0.04, 0.26, 0.9, 5]) {
    const a = poseAt(m, t);
    const b = poseAt(m, t);
    assert.equal(a.frame, b.frame);
    assert.equal(a.pose, b.pose);
  }
  assert.equal(poseAt(m, 0.26).frame, 3);
  assert.deepEqual(poseAt(m, 0.3).dim, [0]);
  assert.equal(poseAt(m, 99).frame, 9);   // past the end holds the last frame
  assert.equal(poseAt(m, -1).frame, 0);
});

test("the copy: one honest line, the name in the error, and no health or weight claim", () => {
  assert.match(TEXT.honest, /normalized skeleton/);
  assert.match(TEXT.honest, /does not depend on the body model/);
  assert.match(slotError("Rigged Figure"), /^Rigged Figure could not be shown/);
  const all = Object.values(TEXT).join(" ") + slotError("X");
  assert.doesNotMatch(all, /weight|health|calorie|fat|diet|fitness|lose|burn/i);
  const dashes = [0x2014, 0x2013].map((c) => String.fromCharCode(c));
  assert.ok(![...dashes, " - "].some((d) => all.includes(d)), "no em dash, en dash or spaced hyphen");
});
