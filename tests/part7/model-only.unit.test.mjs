// "Use my 3D model instead of video" (docs/specs/model-only-take.md AC-MO-11, AC-MO-12).
//   node --test tests/part7/model-only.unit.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { installDom, find } from "./fake-dom.mjs";

installDom();
const { mountModelOnlyChoice, TEXT } = await import("../../web/model-only.js");
const { extraOf, requestOf, buildSubmit } = await import("../../web/take-request.js");

const root = () => globalThis.document.createElement("div");

test("the choice is one unchecked box with the agreed words (AC-MO-11)", () => {
  const box = root();
  const choice = mountModelOnlyChoice(box);
  const input = find(box, "model-only-toggle");
  assert.equal(input.getAttribute("type"), "checkbox");
  assert.equal(choice.value(), false);
  assert.equal(TEXT.label, "Use my 3D model instead of video");
  assert.equal(find(box, "model-only").textContent.includes(TEXT.label), true);
  assert.equal(input.getAttribute("aria-describedby"), find(box, "model-only-hint").getAttribute("id"));
  assert.ok(!/[\u2013\u2014]| - /.test(TEXT.label + TEXT.hint), "no dash in the user text");
  input.checked = true;
  assert.equal(choice.value(), true);
});

test("a saved take carries the choice into the follow request (AC-MO-11)", () => {
  const rec = { role: "follow", entry_id: "squat", upload_id: "u1", trim: null, people_job: "p1", choice: { person_id: "0" }, model_only: true };
  assert.equal(extraOf(rec).model_only, true);
  const { kind, args } = requestOf(rec);
  assert.equal(kind, "follow");
  assert.equal(args[args.length - 1].model_only, true); // the last argument is the extra object api.createFollowJob spreads in
});

test("without the choice nothing is added (AC-MO-11)", () => {
  assert.equal("model_only" in extraOf({ mode: "dance" }), false);
  assert.equal("model_only" in extraOf({ model_only: false }), false);
  const { args } = buildSubmit({ role: "follower", upload: "u", entryId: "e", choice: { person_id: "0" }, peopleJob: "p", extra: {} });
  assert.equal(args.length, 5);
});

test("a model-only result is given no video address (AC-MO-12)", () => {
  const src = readFileSync(new URL("../../web/result.js", import.meta.url), "utf8");
  const hook = src.indexOf("record.video_kept === false) videoUrl = null");
  const use = src.indexOf("videoUrl === undefined ? videoUrlFor(job, pid) : videoUrl");
  assert.ok(hook > 0 && use > hook, "the hook runs before the video address is read");
});

test("a model-only result mounts no export button, a normal one does (AC-MO-10)", async () => {
  const { El } = await import("./fake-dom.mjs");
  const { mountExport } = await import("../../web/views/result-slots.js");
  const slotIn = (modelOnly) => {
    const slot = new El("div");
    slot.closest = (sel) => (modelOnly && sel === '[data-model-only="true"]' ? {} : null);
    return slot;
  };
  const only = slotIn(true), normal = slotIn(false);
  mountExport(only, "job-a");
  mountExport(normal, "job-b");
  await new Promise((r) => setTimeout(r, 40));
  assert.equal(find(only, "export-clip"), null, "negative: no export button on a model-only result");
  assert.ok(find(normal, "export-clip"), "witness: the same call still mounts it for a normal take");
  const src = readFileSync(new URL("../../web/result.js", import.meta.url), "utf8");
  assert.ok(src.includes('root.setAttribute("data-model-only", "true")'), "result.js marks the root from video_kept");
});
