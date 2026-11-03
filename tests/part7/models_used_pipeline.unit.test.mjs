// The TICKET-300 rows in web/model/models-used.js.   node --test tests/part7/models_used_pipeline.unit.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { modelsPanel, rowDetail, clipOrder } from "../../web/model/models-used.js";

const here = path.dirname(fileURLToPath(import.meta.url));
const row = (id, model, status, facts = {}, clip = "you") => ({ id, model, maker: "Meta", clip, status, seconds: null, facts });
const STORY = {
  job: "bbbbbbbbbbb1", job_seconds: 100,
  models: [
    row("image3d", "SAM 3D Objects", "live", { via: "local_gpu", pictures: 1 }, "account"),
    row("avatar", "SAM 3D Body", "live", { via: "local_gpu", avatars: 1, from_picture: 1 }, "account"),
    row("sam31-trainer", "SAM 3.1", "live", { via: "meta_api" }, "trainer"),
    row("sam3d-you", "SAM 3D Body", "live", { via: "local_gpu", frames: 9 }),
    row("mhr-you", "MHR", "live", { via: "local_gpu", frames: 9 }),
    row("glimmer-phrasing", "Muse Glimmer", "live", { via: "local_weights", model_id: "muse-glimmer:30b", lines: 2, lines_live: 2 }),
    row("muse-image", "Muse Image", "live", { via: "meta_api", pictures: 2, shown: 1 }),
    row("mms-tts", "MMS-TTS", "live", { via: "local_weights", spoken: 3, languages: ["eng"] }),
    row("spark-history", "Muse Spark", "not_run", { reason: "no_history_report" }, "account"),
  ],
};

test("new rows: plain names, task lines and details", () => {
  const panel = modelsPanel(STORY);
  const by = Object.fromEntries(panel.items.map((i) => [i.id, i]));
  assert.equal(by.image3d.task, "Turned your picture into a 3D model");
  assert.equal(by.image3d.detail, "open weights on this machine's GPU, 1 picture");
  assert.match(by["mhr-you"].task, /MHR body rig/);
  assert.equal(by["glimmer-phrasing"].detail, "open weights on this machine, 2 of 2 lines");
  assert.equal(by["muse-image"].detail, "Meta Model API, 1 of 2 pictures shown");
  assert.equal(by["mms-tts"].detail, "open weights on this machine, 3 spoken lines");
  assert.ok(Object.values(by).every((i) => i.maker === "Meta"));
  assert.equal(panel.madeWith,
    "Made with Meta's SAM 3D Objects, SAM 3D Body, SAM 3.1, MHR, Muse Glimmer, Muse Image and MMS-TTS.");
});

test("groups follow the pipeline: the account group leads when the picture model is first", () => {
  assert.deepEqual(modelsPanel(STORY).clips, ["account", "trainer", "you"]);
  const stranger = { models: STORY.models.filter((m) => m.clip !== "account") };
  assert.deepEqual(modelsPanel(stranger).clips, ["trainer", "you"]);
  assert.deepEqual(clipOrder(null), []);
});

test("negative: absent evidence reads as not used or a fallback, never as made with", () => {
  const doc = { models: [
    row("image3d", "SAM 3D Objects", "not_run", { reason: "no_picture_model" }, "account"),
    row("mhr-you", "MHR", "not_run", { reason: "no_body_model" }),
    row("glimmer-phrasing", "Muse Glimmer", "not_run", { reason: "private_mode_off" }),
    row("muse-image", "Muse Image", "fallback", { ran: "measured_faults", reason: "image_call_failed" }),
    row("mms-tts", "MMS-TTS", "fallback", { ran: "browser_voice", reason: "speech_failed" }),
  ] };
  const panel = modelsPanel(doc);
  assert.equal(panel.madeWith, "");
  const by = Object.fromEntries(panel.items.map((i) => [i.id, i.detail]));
  assert.equal(by.image3d, "You have not made a model from a picture");
  assert.equal(by["glimmer-phrasing"], "Private mode was off for this take");
  assert.equal(by["muse-image"], "Used the measured faults alone: the image call failed");
  assert.equal(by["mms-tts"], "Used your browser's own voice: the voice model failed on this machine");
  assert.equal(rowDetail(row("image3d", "SAM 3D Objects", "fallback", { ran: "trellis", reason: "sam3do_unavailable" }, "account")),
    "Used TRELLIS: SAM 3D Objects could not run on this machine");
});

test("no dash in the copy", () => {
  const dash = new RegExp(`[${String.fromCharCode(0x2013, 0x2014)}]`);
  for (const file of ["../../web/model/models-used.js", "../../web/views/models-used.js"]) {
    assert.ok(!dash.test(fs.readFileSync(path.join(here, file), "utf8")), file);
  }
});
