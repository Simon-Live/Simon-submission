// The "Simon remembers" segment (TICKET-185): the script refuses to record with empty facts, and the copy is clean.
import test from "node:test";
import assert from "node:assert/strict";
import { execFileSync, spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { emptySlots, fill, srt } from "../../demo/remembers/capture.mjs";

const rel = (f) => fileURLToPath(new URL(`../../demo/remembers/${f}`, import.meta.url));
const facts = JSON.parse(readFileSync(rel("facts.json"), "utf8"));

test("facts.json ships empty: every slot is null until TICKET-184's report fills it", () => {
  assert.equal(facts.status, "pending-live");
  assert.ok(emptySlots(facts).length > 10);
  assert.ok(Object.values(facts.slots).every((v) => v === null), "negative: no number is typed in by hand");
});

test("capture.mjs records nothing while facts are empty and says why", () => {
  const run = spawnSync(process.execPath, [rel("capture.mjs"), "/nonexistent-out", "https://example.invalid/"], { encoding: "utf8" });
  assert.equal(run.status, 2);
  assert.match(run.stderr, /facts\.json is not filled/);
});

test("fill and srt read slots, and refuse an empty one", () => {
  assert.equal(fill("Take {cite_take}, {cite_s} s", { cite_take: 1, cite_s: 2.1 }), "Take 1, 2.1 s");
  assert.throws(() => fill("{takes} takes", { takes: null }), /slot takes is empty/);
  assert.throws(() => srt(facts.slots), /is empty/);
  const filled = Object.fromEntries(Object.keys(facts.slots).map((k, i) => [k, i + 1]));
  assert.match(srt(filled, "squat"), /^1\n00:00:00,000 --> 00:00:06,000\n/);
});

test("the segment copy has no banned word and no dash character", () => {
  for (const file of ["shotlist.md", "capture.mjs"]) {
    const text = readFileSync(rel(file), "utf8");
    assert.doesNotMatch(text.replace(/the words coach, coaching, medical and injury/, ""), /\b(coach|coaching|medical|injury)\b/i, file);
    assert.doesNotMatch(text, new RegExp("[\\u2013\\u2014]"), file);
  }
});

test("capture.mjs parses", () => {
  execFileSync(process.execPath, ["--check", rel("capture.mjs")]);
});
