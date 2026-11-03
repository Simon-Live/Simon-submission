// Browser check for the trainer's own recording at the fault (TICKET-270 AC-2, AC-3) with the real web/narration.js.
//   node tests/part7/narration_voice.browser.mjs
// Playwright comes from `npm i` in this repo, or from PLAYWRIGHT_DIR. The narration routes are answered here.
import assert from "node:assert/strict";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { serveRoot } from "./serve_static.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const req = createRequire(path.join(process.env.PLAYWRIGHT_DIR || path.resolve(here, "../../node_modules"), "x.js"));
const { chromium } = req("playwright");

const SECTIONS = [{ index: 1, count: 2, start_ms: 0, end_ms: 5000 }, { index: 2, count: 2, start_ms: 5000, end_ms: 10000 }];
const DOC = {
  format: "simon.narration.v1", sections: SECTIONS,
  cues: [
    { index: 0, start_s: 1.2, end_s: 2.2, text: "Knees out and chest up.", section: SECTIONS[0], also_sections: [], clip: { file: "cue-0.wav", ms: 500 } },
    { index: 1, start_s: 7.6, end_s: 8.6, text: "Slowly back down.", section: SECTIONS[1], also_sections: [] },
  ],
};

/** A 0.5 s mono 16 kHz silent WAV. */
function wav() {
  const n = 8000, buf = Buffer.alloc(44 + n * 2);
  buf.write("RIFF", 0); buf.writeUInt32LE(36 + n * 2, 4); buf.write("WAVEfmt ", 8); buf.writeUInt32LE(16, 16);
  buf.writeUInt16LE(1, 20); buf.writeUInt16LE(1, 22); buf.writeUInt32LE(16000, 24); buf.writeUInt32LE(32000, 28);
  buf.writeUInt16LE(2, 32); buf.writeUInt16LE(16, 34); buf.write("data", 36); buf.writeUInt32LE(n * 2, 40);
  return buf;
}

const { server, port } = await serveRoot();
const browser = await chromium.launch({ args: ["--autoplay-policy=no-user-gesture-required"] });
const errors = [];
try {
  const page = await browser.newPage();
  page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
  page.on("pageerror", (e) => errors.push(e.message));
  const fetched = [];
  await page.route("**/api/narration/squat", (r) => r.fulfill({ contentType: "application/json", body: JSON.stringify(DOC) }));
  await page.route("**/api/narration/squat/*.wav", (r) => { fetched.push(new URL(r.request().url()).pathname); r.fulfill({ contentType: "audio/wav", body: wav() }); });
  await page.goto(`http://127.0.0.1:${port}/web/theme/narration.css`);
  await page.evaluate(async () => {
    const root = document.createElement("div");
    root.innerHTML = '<ol><li><button data-testid="fault-0" data-at-s="1.9"></button></li><li><button data-testid="fault-1" data-at-s="8"></button></li></ol>';
    document.body.append(root);
    const m = await import("/web/narration.js");
    window.__mounted = await m.mountNarration(root, { entryId: "squat", trainer: "Dana" });
  });
  const tid = (id) => page.getByTestId(id);
  assert.equal(await tid("narration-play").count(), 1, "only the fault whose section has a clip gets a button");
  assert.equal(await tid("narration-who").textContent(), "Dana, in their own voice");
  assert.equal(await page.locator('[data-testid="fault-1-narration"] [data-testid="narration-play"]').count(), 0, "AC-3 the other section plays nothing");
  assert.equal(await tid("narration-cue").count(), 2, "the second cue still shows its words");
  assert.deepEqual(fetched, [], "nothing is fetched before the click");
  await tid("narration-play").click();
  await page.waitForTimeout(500);
  assert.deepEqual(fetched, ["/web/theme/api/narration/squat/cue-0.wav"], "the click fetches the cue's wav");
  assert.deepEqual(errors, [], errors.join("\n"));
  console.log("ok - TICKET-270 the fault replay fetches the trainer's own wav and names who spoke; another section has none");
} finally {
  await browser.close();
  server.close();
}
