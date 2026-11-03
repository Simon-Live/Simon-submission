// Unit checks for the result screen's additions (docs/specs/result-redesign-additions.md R2, R3, R6).
// Run: node --test tests/part7/result_additions.unit.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { trainerClock, meshFaults } from "../../web/model/mesh-clock.js";
import { containRect } from "../../web/views/skeleton-overlay.js";
import { LANE_MODULES, isLaneModule404 } from "./lane_modules.mjs";

const web = path.join(path.dirname(fileURLToPath(import.meta.url)), "../../web");
const read = (f) => fs.readFileSync(path.join(web, f), "utf8");

test("trainerClock: the trainer time Part 5 aligned at or before the follower frame", () => {
  // follower at 10 fps; trainer frames 0..3 aligned to follower frames 0, 2, 2, 5
  const clock = trainerClock({ fps: 10, exp_to_fol: [0, 2, 2, 5], expected_t: [0, 0.1, 0.2, 0.3] });
  assert.equal(clock(0), 0);
  assert.equal(clock(0.1), 0, "follower frame 1: only trainer frame 0 is aligned at or before it");
  assert.equal(clock(0.2), 0.2, "two trainer frames on follower frame 2: the later one");
  assert.equal(clock(0.4), 0.2);
  assert.equal(clock(0.5), 0.3);
  assert.equal(clock(9), 0.3, "past the end: the last trainer frame");
  assert.equal(clock(-1), 0, "before the start: the first");
});

test("trainerClock: no alignment, no clock (both bodies then share the time)", () => {
  for (const bad of [null, {}, { fps: 0, exp_to_fol: [0], expected_t: [0] }, { fps: 30, exp_to_fol: [0, 1], expected_t: [0] },
    { fps: 30, exp_to_fol: [0, Number.NaN], expected_t: [0, 1] }, { fps: 30, exp_to_fol: [], expected_t: [] }]) {
    assert.equal(trainerClock(bad), null, JSON.stringify(bad));
  }
});

test("meshFaults: the analysis' timed mistakes in the mesh view's shape, copied", () => {
  const src = [{ at: 1.5, joints: ["left_knee"] }];
  const out = meshFaults(src);
  assert.deepEqual(out, [{ at_s: 1.5, joints: ["left_knee"] }]);
  out[0].joints.push("x");
  assert.deepEqual(src[0].joints, ["left_knee"]);
});

test("containRect: where a contained picture lands in its box", () => {
  assert.deepEqual(containRect(400, 300, 160, 120), { x: 0, y: 0, w: 400, h: 300 });
  assert.deepEqual(containRect(400, 400, 160, 120), { x: 0, y: 50, w: 400, h: 300 }, "letterboxed top and bottom");
  const w = 160 * (100 / 120);
  assert.deepEqual(containRect(400, 100, 160, 120), { x: (400 - w) / 2, y: 0, w, h: 100 }, "pillarboxed");
  assert.deepEqual(containRect(400, 300, 0, 0), { x: 0, y: 0, w: 400, h: 300 }, "no picture size yet: the whole box");
});

test("contract C2/C2b: the other session's glue modules load from the web/ root, relative to views/, and stay optional", () => {
  const slots = read("views/result-slots.js");
  for (const [file, fn] of [["voice.js", "mountVoiceSlots"], ["second-opinion.js", "mountSecondOpinion"], ["export.js", "mountExportButton"],
    ["narration.js", "mountNarration"]]) {
    assert.match(slots, new RegExp(`import\\("\\.\\./${file.replace(".", "\\.")}"\\)\\.then\\(\\(m\\) => m\\.${fn}\\(`), `${file} ${fn}`);
  }
  assert.doesNotMatch(slots, /import\("\.\/(voice|second-opinion|export|narration)\.js"\)/, "negative: not from web/views/");
  assert.equal((slots.match(/quiet\(import\(/g) || []).length, 7, "every load is wrapped so a missing module is silent");
  assert.match(slots, /corrected && owns && jobId !== "fixture"[\s\S]{0,60}import\("\.\.\/corrected-card\.js"\)/, "the corrected-pose card mounts for the owner only (TICKET-280)");
  assert.match(slots, /import\("\.\.\/history\.js"\)\.then\(\(m\) => m\.mountHistory\(history, \{ jobId: owns \? jobId : null, entryId, analysis, seek \}\)/); // no since-last-time for a non-owner
  assert.match(slots, /import\("\.\.\/auth\.js"\)\.then\(\(m\) => m\.mountKeepTake\(keep, jobId\)/);
  assert.match(slots, /"data-testid": "history-slot"/);
  for (const id of ["voice-slot", "second-opinion-slot", "export-slot"]) assert.match(slots, new RegExp(`"data-testid": "${id}"`));
  assert.match(slots, /"data-fault-index": index, "data-at-s": atS/);
  // the result screen calls them; the summary holds the export slot
  assert.match(read("result.js"), /mountLaneModules\(root, \{ jobId: job \|\| "fixture", analysis, video:/);
  assert.match(read("views/result-summary.js"), /exportSlot\(\)/);
  // TICKET-111: the export button mounts only for a real single-person job, and the result's destroy stops it
  assert.match(read("result.js"), /if \(hasJobFiles\(job, pid\)\) cleanups\.push\(mountExport\(summary\.exportSlot, job\)\)/);
  assert.doesNotMatch(read("result.js"), /job \|\| "fixture"\)\);\s*\/\/ C2b/, "negative: no fixture export mount");
  assert.deepEqual(LANE_MODULES, ["voice.js", "second-opinion.js", "export.js", "narration.js"]);
  assert.equal(isLaneModule404("http://h/web/voice.js"), true);
  assert.equal(isLaneModule404("http://h/web/result-slots.js"), false);
  assert.equal(isLaneModule404("http://h/web/views/voice.js"), false);
});

test("tokens: the mesh and skeleton colours live in tokens.css", () => {
  const tokens = read("theme/tokens.css");
  for (const name of ["--mesh-trainer", "--mesh-you", "--mesh-fault", "--mesh-bg", "--mesh-light", "--mesh-ground",
    "--skeleton-line", "--skeleton-joint", "--skeleton-hot"]) assert.match(tokens, new RegExp(`${name}:`), name);
});
