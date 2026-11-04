// TICKET-493 (docs/specs/image3d-intake.md AC-I34): in the Import dialog the answer "It shows no real person" is shown whole
// in the closed select at 320 and 412 px wide, and its example sits in the line under the question. The real app
// (tests/part7/real_app.py) answers api/policy with person_check false, as prod does, so the question is asked up front.
// Negative: a person photo never offers the answer.
//   PLAYWRIGHT_DIR=<node_modules> scripts/with-browser-slot.sh node tests/part7/picture-select.browser.mjs
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const req = createRequire(path.join(process.env.PLAYWRIGHT_DIR || path.resolve(here, "../../node_modules"), "x.js"));
const { chromium } = req("playwright");
const SHOTS = process.env.SHOTS_DIR || fs.mkdtempSync(path.join(os.tmpdir(), "picture-select-"));
fs.mkdirSync(SHOTS, { recursive: true });

const PORT = 7800 + Math.floor(Math.random() * 90);
const BASE = `http://127.0.0.1:${PORT}/simon-part-7`;
const app = spawn("python3", [path.join(here, "real_app.py"), String(PORT), String(PORT + 100)], { stdio: "inherit" });
for (let i = 0; i < 100; i++) {
  try { if ((await fetch(`${BASE}/api/models`)).ok) break; } catch { /* starting */ }
  await new Promise((r) => setTimeout(r, 100));
}
const browser = await chromium.launch();
const PNG = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==", "base64");
const errors = [];
let passed = 0;

async function atWidth(width) {
  const ctx = await browser.newContext({ viewport: { width, height: 900 } });
  const page = await ctx.newPage();
  page.on("pageerror", (e) => errors.push(e.message));
  await page.route(/api\/policy$/, async (route) => {
    const res = await route.fetch();
    await route.fulfill({ response: res, json: { ...(await res.json()), person_check: false } });
  });
  await page.goto(`${BASE}/#/me`);
  await page.getByTestId("my-model-upload").click();
  await page.getByTestId("model-import-dialog").waitFor();
  await page.getByTestId("model-import-file").setInputFiles({ name: "x.png", mimeType: "image/png", buffer: PNG });
  await page.getByTestId("model-import-picture-object").check();
  const select = page.getByTestId("model-import-consent");
  await select.waitFor({ state: "visible" });
  await select.selectOption("fiction");
  const m = await page.evaluate(() => {
    const s = document.querySelector('[data-testid="model-import-consent"]');
    const cs = getComputedStyle(s);
    const c = document.createElement("canvas").getContext("2d");
    c.font = `${cs.fontWeight} ${cs.fontSize} ${cs.fontFamily}`;
    const text = s.options[s.selectedIndex].text;
    const room = s.getBoundingClientRect().width - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight) - 30; // 30: the arrow
    const note = s.parentElement.querySelector("small");
    const dlg = document.querySelector('[data-testid="model-import-dialog"]').getBoundingClientRect();
    return { text, need: c.measureText(text).width, room, note: note.textContent, noteRight: note.getBoundingClientRect().right, dialogRight: dlg.right, vw: innerWidth };
  });
  await page.screenshot({ path: path.join(SHOTS, `no-real-person-${width}.png`) });
  assert.equal(m.text, "It shows no real person");
  assert.ok(m.need <= m.room, `${width}px: the answer needs ${m.need.toFixed(0)}px and the select has ${m.room.toFixed(0)}px`);
  assert.match(m.note, /No real person means a drawing, toy or statue\./);
  assert.ok(m.dialogRight <= m.vw && m.noteRight <= m.dialogRight, `${width}px: the dialog and the line under the question fit the screen`);
  await page.getByTestId("model-import-picture-person").check();
  const offered = await page.evaluate(() => [...document.querySelector('[data-testid="model-import-consent"]').options].map((o) => o.value));
  assert.equal(offered.includes("fiction"), false, `${width}px: a person photo is not offered the answer`);
  await ctx.close();
  passed++;
  console.log(`ok - ${width}px: the answer fits its select, the example is under the question, a person photo does not get it`);
}

try {
  for (const w of [320, 412]) await atWidth(w);
} finally {
  await browser.close();
  app.kill();
}
assert.deepEqual(errors, []);
console.log(`${passed} passed; shots in ${SHOTS}`);
