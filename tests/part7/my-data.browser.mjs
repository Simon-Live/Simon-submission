// Browser drive at 412x915 of "Download my data" on the Me page against the REAL routes (serve_export_seed.py: the app at
// base path "/" with the staging test mailbox and two SEEDED accounts, ada keeps 3 takes, grace 2 of another movement).
//   /home/gingy/claude-template/scripts/with-browser-slot.sh node tests/part7/my-data.browser.mjs
// Screenshots (not committed): SHOTS_DIR or demos/rubric/TICKET-236/.
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const { chromium } = createRequire(path.join(process.env.PLAYWRIGHT_DIR || path.resolve(here, "../../node_modules"), "x.js"))("playwright");
const SHOTS = process.env.SHOTS_DIR || path.resolve(here, "../../demos/rubric/TICKET-236");
fs.mkdirSync(SHOTS, { recursive: true });

const port = 7900 + Math.floor(Math.random() * 90);
const base = `http://127.0.0.1:${port}/`;
const server = spawn("python3", [path.join(here, "serve_export_seed.py"), String(port)], { stdio: "inherit" });
for (let i = 0; i < 100; i++) {
  try { if ((await fetch(`${base}api/auth/me`)).ok) break; } catch { await new Promise((r) => setTimeout(r, 150)); }
}
const jobId = (tag, n) => crypto.createHash("sha256").update(`${tag}:${n}`).digest("hex").slice(0, 12);
const adaJobs = [0, 1, 2].map((n) => jobId("ada", n));
const graceJobs = [0, 1].map((n) => jobId("grace", n));

const browser = await chromium.launch();
const errors = [];
let passed = 0;
const ok = (name) => { passed++; console.log(`ok - ${name}`); };
const EXPECTED = /status of (401|404)/; // 404: the history page asks for a report nobody has made yet (a normal answer)

async function signIn(page, email) {
  await page.goto(`${base}#/signin`);
  await page.getByTestId("auth-email").fill(email);
  await page.getByTestId("auth-send").tap();
  await page.getByTestId("auth-code").waitFor();
  const { messages } = await (await fetch(`${base}api/auth/outbox?email=${encodeURIComponent(email)}`)).json();
  await page.getByTestId("auth-code").fill(messages[0].code);
  await page.getByTestId("auth-verify").tap();
  await page.getByTestId("me-email").waitFor();
}

async function newPage() {
  const ctx = await browser.newContext({ viewport: { width: 412, height: 915 }, deviceScaleFactor: 2, hasTouch: true, acceptDownloads: true });
  const page = await ctx.newPage();
  page.on("console", (m) => { if (m.type() === "error" && !EXPECTED.test(m.text())) errors.push(m.text()); });
  page.on("pageerror", (e) => errors.push(e.message));
  return page;
}

async function downloadFile(page) {
  const [dl] = await Promise.all([page.waitForEvent("download"), page.getByTestId("me-export").tap()]);
  const file = await dl.path();
  return { name: dl.suggestedFilename(), text: fs.readFileSync(file, "utf8") };
}

try {
  // signed out: no trace on the page, and the route answers 401 with no file
  const out = await newPage();
  await out.goto(`${base}#/me`);
  await out.getByTestId("me-signed-out").waitFor();
  assert.equal(await out.getByTestId("me-export").count(), 0, "negative: no Download my data button when signed out");
  assert.doesNotMatch(await out.locator("#app").innerText(), /Download my data/);
  const refused = await out.request.get(`${base}api/me/export`);
  assert.equal(refused.status(), 401);
  assert.equal(refused.headers()["content-disposition"], undefined, "negative: no attachment when signed out");
  ok("signed out: no button on the Me page, the route answers 401 and no file");

  // ada downloads
  const page = await newPage();
  await signIn(page, "ada@example.com");
  await page.getByTestId("me-export").waitFor();
  const card = await page.getByTestId("me-export-card").innerText();
  assert.match(card, /Download my data/);
  assert.match(card, /shows your email address/);
  const order = await page.getByTestId("me-export-card").evaluate((el) => el.nextElementSibling?.getAttribute("data-testid"));
  assert.equal(order, "me-delete-card", "the card sits right above Delete my data");
  await page.screenshot({ path: path.join(SHOTS, "1-me-with-download.png"), fullPage: true });
  const file = await downloadFile(page);
  assert.match(file.name, /^simon-my-data-\d{4}-\d{2}-\d{2}\.json$/);
  await page.getByTestId("me-export-note").filter({ hasText: "Your file was downloaded." }).waitFor();
  const doc = JSON.parse(file.text);
  assert.equal(doc.format, "simon.export.v1");
  assert.equal(doc.account.email, "ada@example.com");
  assert.equal(doc.takes.length, 3, "witness 1: three takes in the file");
  assert.equal(doc.history[0].takes.length, 3);
  ok(`ada: the file downloads as ${file.name}, ${file.text.length} bytes, 3 takes`);

  // witness 2: the history page for the same movement shows the same count and score
  const entry = doc.history[0].entry_id;
  await page.goto(`${base}#/me/${entry}`);
  await page.waitForFunction(() => /100/.test(document.querySelector("#app")?.innerText || ""));
  const shown = await page.locator("#app").innerText();
  assert.equal((shown.match(/^Take \d+$/gm) || []).length, 3, "witness 2: the history page lists 3 takes");
  assert.ok(shown.includes(String(doc.history[0].takes[0].meta.score)), "witness 2: the score in the file is on the history page");
  await page.screenshot({ path: path.join(SHOTS, "2-history-page.png"), fullPage: true });
  ok("the history page shows the same take count and score as the file");

  // negative: nothing of grace in ada's file
  for (const other of ["grace@example.com", "Grace Secret", "side-lunge", ...graceJobs]) {
    assert.equal(file.text.includes(other), false, `negative: ada's file has no ${other}`);
  }
  for (const own of adaJobs) assert.ok(file.text.includes(own));
  assert.equal(/seeded clip bytes|sid_hash|token_hash|pepper/.test(file.text), false, "negative: no clip bytes, hashes or pepper");
  ok("ada's file holds none of grace's email, name, movement or job ids, and no secrets or video bytes");

  // no limit: a sixth download in the hour still saves the whole file
  await page.goto(`${base}#/me`);
  await page.getByTestId("me-export").waitFor();
  for (let i = 0; i < 4; i++) await downloadFile(page);
  const sixth = await downloadFile(page);
  assert.equal(JSON.parse(sixth.text).account.email, "ada@example.com", "witness 1: the sixth file is ada's");
  assert.equal(sixth.text.includes(adaJobs[0]), true, "witness 2: the sixth file holds her takes");
  assert.doesNotMatch(await page.locator("#app").innerText(), /in the last hour/, "negative: no limit words");
  await page.screenshot({ path: path.join(SHOTS, "3-sixth.png"), fullPage: true });
  ok("a sixth download in an hour still saves the whole file");

  // grace has her own file
  const g = await newPage();
  await signIn(g, "grace@example.com");
  await g.getByTestId("me-export").waitFor();
  const gfile = await downloadFile(g);
  assert.equal(JSON.parse(gfile.text).takes.length, 2);
  for (const other of ["ada@example.com", "Ada L", ...adaJobs]) assert.equal(gfile.text.includes(other), false, `negative: grace's file has no ${other}`);
  ok("grace's file holds only her own data");

  assert.deepEqual(errors, []);
} finally {
  await browser.close();
  server.kill();
}
console.log(`${passed} passed`);
