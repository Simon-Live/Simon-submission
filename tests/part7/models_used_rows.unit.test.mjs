// The rows of TICKET-262 in web/model/models-used.js.   node --test tests/part7/models_used_rows.unit.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { modelsPanel, rowDetail } from "../../web/model/models-used.js";

const here = path.dirname(fileURLToPath(import.meta.url));
const row = (id, model, status, facts = {}, clip = "you") => ({ id, model, maker: "Meta", clip, status, seconds: null, facts });
const MORE = {
  job: "bbbbbbbbbbb1", job_seconds: 100,
  models: [
    row("narration", "Muse Voice Transcribe", "live", { via: "meta_api", cues: 2, clips: 1 }, "trainer"),
    row("spark-opinion", "Muse Spark", "live", { via: "meta_api", verdicts: 1, observations: 2, cached_tokens: 50 }),
    row("spark-history", "Muse Spark", "live", { via: "meta_api", takes: 3, videos: 2, cached_tokens: 4000 }, "account"),
    row("avatar", "SAM 3D Body", "not_run", { reason: "no_avatar" }, "account"),
  ],
};

test("new rows: task lines, details and the account group", () => {
  const panel = modelsPanel(MORE);
  const by = Object.fromEntries(panel.items.map((i) => [i.id, i]));
  assert.match(by.narration.task, /spoken cues/);
  assert.equal(by.narration.detail, "Meta Model API, 2 spoken cues, 1 clip cut from the recording");
  assert.equal(by["spark-opinion"].detail, "Meta Model API, 1 verdict, 50 tokens reused");
  assert.equal(by["spark-history"].detail, "Meta Model API, 3 takes, 2 videos, 4000 tokens reused");
  assert.equal(by.avatar.detail, "You have not made an avatar");
  assert.equal(panel.madeWith, "Made with Meta's Muse Voice Transcribe and Muse Spark.");
});

test("negative: a not-run row is never counted as made with", () => {
  const doc = { models: [row("narration", "Muse Voice Transcribe", "not_run", { reason: "no_narration" }, "trainer")] };
  assert.equal(modelsPanel(doc).madeWith, "");
  assert.equal(modelsPanel(doc).items[0].detail, "The trainer left no spoken cues");
});

test("fallback wording and no dash in the copy", () => {
  assert.equal(rowDetail(row("spark-opinion", "Muse Spark", "fallback", { ran: "measured_faults", reason: "unreadable answer" })),
    "Used the measured faults alone: unreadable answer");
  const dash = new RegExp(`[${String.fromCharCode(0x2013, 0x2014)}]`);
  for (const file of ["../../web/model/models-used.js", "../../web/views/narration.js"]) {
    assert.ok(!dash.test(fs.readFileSync(path.join(here, file), "utf8")), file);
  }
});
