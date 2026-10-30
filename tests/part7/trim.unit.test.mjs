// Pure-function checks for the trim editor, labels and catalog search (recorder.md AC-R2, AC-R5, AC-R6).
//   node --test tests/part7/trim.unit.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { lengthLabel, selectionError, defaultRange, TEXT, MAX_BYTES } from "../../web/trim.js";
import { parseTag, TAG_TEXT } from "../../web/labels.js";
import { matches } from "../../web/catalog.js";

test("length label is end minus start to 0.1 s", () => {
  assert.equal(lengthLabel(2100, 9400), "2.1 s to 9.4 s, 7.3 s");
  assert.equal(lengthLabel(0, 12000), "0.0 s to 12.0 s, 12.0 s");
});

test("selection rules: 1 s to 60 s, plain words", () => {
  assert.equal(selectionError(0, 999, 12000), TEXT.short);
  assert.equal(selectionError(0, 1000, 12000), "");
  assert.equal(selectionError(0, 60000, 90000), "");
  assert.equal(selectionError(0, 60001, 90000), TEXT.long);
  assert.equal(selectionError(0, 800, 800), TEXT.tooShort);
  assert.equal(selectionError(0, 5000, 10000, MAX_BYTES + 1), TEXT.bytes);
  assert.equal(selectionError(0, 5000, 10000, MAX_BYTES), "");
});

test("defaults: whole clip; Manual trims the last 1.0 s", () => {
  assert.deepEqual(defaultRange(12345, false), { start_ms: 0, end_ms: 12345 });
  assert.deepEqual(defaultRange(12345, true), { start_ms: 0, end_ms: 11345 });
  assert.deepEqual(defaultRange(1500, true), { start_ms: 0, end_ms: 1500 }, "too short to drop a second");
});

test("tags: lower case, letters digits hyphen, 1 to 24", () => {
  assert.deepEqual(parseTag("  Leg-Day "), { tag: "leg-day" });
  assert.deepEqual(parseTag(""), { tag: "" });
  assert.equal(parseTag("a b").error, TAG_TEXT.chars);
  assert.equal(parseTag("under_score").error, TAG_TEXT.chars);
  assert.equal(parseTag("a".repeat(24)).tag, "a".repeat(24));
  assert.equal(parseTag("a".repeat(25)).error, TAG_TEXT.long);
});

test("catalog search matches name, category, id and tags", () => {
  const e = { id: "e1", name: "Plank", category: "core" };
  const labels = { e1: { tags: ["isometric"], notes: "" } };
  assert.equal(matches(e, "plank", labels), true);
  assert.equal(matches(e, "ISOMETRIC", labels), true);
  assert.equal(matches(e, "isometric"), false, "no labels loaded yet");
  assert.equal(matches(e, "squat", labels), false);
  assert.equal(matches(e, "", labels), true);
});
