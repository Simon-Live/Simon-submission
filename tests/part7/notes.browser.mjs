// Browser drive at 412x915 of "ask the trainer for a note" with THREE real accounts against the REAL routes
// (serve_notes.py: the app at base path "/" with the staging test mailbox and two SEEDED finished takes of one movement).
// The follower keeps a take, asks the trainer with the clip off; the trainer opens the request from the Me page, sees the
// score and the noticed fault but no clip, answers at the fault time; the follower reads the note on the result page, the
// Me page and the history page. Negative: a third account and a signed-out visitor get 404 and 401 and see nothing; the
// trainer never sees the follower's other take, email or a job id; a withdrawn request closes the trainer's page.
//   SIMON7_MODULES_DIR=<checkout>/modules PLAYWRIGHT_DIR=<node_modules> /home/gingy/claude-template/scripts/with-browser-slot.sh node tests/part7/notes.browser.mjs
// Screenshots (not committed): SHOTS_DIR or demos/rubric/TICKET-237/.
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const { chromium } = createRequire(path.join(process.env.PLAYWRIGHT_DIR || path.resolve(here, "../../node_modules"), "x.js"))("playwright");
const SHOTS = process.env.SHOTS_DIR || path.resolve(here, "../../demos/rubric/TICKET-237");
fs.mkdirSync(SHOTS, { recursive: true });
const port = 7900 + Math.floor(Math.random() * 40) * 2;
const base = `http://127.0.0.1:${port}/`;
const helper = `http://127.0.0.1:${port + 1}`;
const idFile = path.join(fs.mkdtempSync(path.join(os.tmpdir(), "notes-")), "ids.json");
const server = spawn("python3", [path.join(here, "serve_notes.py"), String(port), idFile], { stdio: "inherit" });
for (let i = 0; i < 200; i++) {
  try { if ((await fetch(`${base}api/auth/me`)).ok && fs.existsSync(idFile)) break; } catch { /* not up yet */ }
  await new Promise((r) => setTimeout(r, 150));
}
const { first, second, entry } = JSON.parse(fs.readFileSync(idFile, "utf8")); // seeded takes, not real recordings
const FOLLOWER = "fred.follower@example.com";
const TRAINER = "tina.trainer@example.com";
const THIRD = "theo.third@example.com";
const NOTE = "Keep the left elbow close to your side.";
const browser = await chromium.launch();
const errors = [];
let passed = 0;
const ok = (name) => { passed++; console.log(`ok - ${name}`); };
const t = (p, id) => p.getByTestId(id);
const EXPECTED = /status of (401|404|429)/; // refused calls are the normal answers this test provokes
const shot = (page, name) => page.screenshot({ path: path.join(SHOTS, name), fullPage: true });

async function person(email) {
  const ctx = await browser.newContext({ viewport: { width: 412, height: 915 }, deviceScaleFactor: 2, hasTouch: true });
  await ctx.addInitScript(() => { try { localStorage.setItem("simon.result.more", "open"); } catch { /* blocked */ } });   // the lean result keeps "Ask the trainer" in "More"
  const page = await ctx.newPage();
  page.on("console", (m) => { if (m.type() === "error" && !EXPECTED.test(m.text())) errors.push(`${email}: ${m.text()}`); });
  page.on("pageerror", (e) => errors.push(`${email}: ${e.message}`));
  await page.goto(`${base}#/signin`);
  await t(page, "auth-email").fill(email);
  await t(page, "auth-send").tap();
  await t(page, "auth-code").waitFor();
  const code = await page.evaluate(async (e) => (await (await fetch(`api/auth/outbox?email=${encodeURIComponent(e)}`)).json()).messages[0].code, email);
  await t(page, "auth-code").fill(code);
  await t(page, "auth-verify").tap();
  await t(page, "me-email").waitFor();
  return page;
}
const api = (page, url, init) => page.evaluate(async ([u, i]) => {
  const r = await fetch(u, i);
  const body = await r.text();
  return { status: r.status, body };
}, [url, init]);
const postJson = (page, url, doc) => api(page, url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(doc) });
const bodyText = async (page) => (await page.content()) + (await page.evaluate(() => document.body.innerText));

try {
  const follower = await person(FOLLOWER);
  const trainer = await person(TRAINER);
  const third = await person(THIRD);
  assert.equal((await fetch(`${helper}/own?email=${TRAINER}`)).status, 200);
  ok("three accounts signed in; the trainer owns the movement");

  // the follower keeps history, then keeps both takes through the Me page like a person would
  await follower.goto(`${base}#/me`);
  await t(follower, "me-retention").check();
  await follower.waitForFunction(() => document.querySelector('[data-testid="me-consent-note"]')?.textContent);
  for (const job of [first, second]) {
    await t(follower, "me-claim-input").fill(job);
    await t(follower, "me-claim-button").tap();
    await follower.waitForFunction((j) => document.querySelector(`[data-job="${j}"]`), job);
  }
  ok("the follower kept both seeded takes");

  // 1. the follower asks, clip off
  await follower.goto(`${base}#/result/${first}`);
  await t(follower, "ask-open").tap();
  await t(follower, "ask-dialog").waitFor();
  assert.equal(await t(follower, "ask-include-score").isChecked(), true);
  assert.equal(await t(follower, "ask-include-faults").isChecked(), true);
  assert.equal(await t(follower, "ask-include-clip").isChecked(), false, "the clip starts off");
  assert.match(await t(follower, "ask-shown-as").innerText(), /will see you as A Simon user/);
  assert.match(await t(follower, "ask-dialog").innerText(), /does not see your email, your other takes or any link to your account/);
  await shot(follower, "1-dialog.png");
  await t(follower, "ask-send").tap();
  await t(follower, "ask-asked").waitFor();
  assert.match(await t(follower, "ask-asked").innerText(), /You asked the trainer on .*There is no note yet\./);
  await shot(follower, "2-asked.png");
  ok("follower asked with the clip off and sees the asked state");

  // 2. the trainer finds it on the Me page and opens it
  await trainer.goto(`${base}#/me`);
  await trainer.reload(); // the trainer has been on this page since signing in: look again, as a person would
  await t(trainer, "notes-waiting").waitFor();
  assert.equal(await t(trainer, "notes-waiting").innerText(), "1 request waiting for your note");
  await shot(trainer, "3-trainer-card.png");
  await t(trainer, "notes-waiting-list-0").tap();
  await t(trainer, "request-page").waitFor();
  assert.match(await t(trainer, "request-who").innerText(), /^A Simon user asked about lateral-raise on /);
  assert.equal(await t(trainer, "request-score").innerText(), "Score 100, grade A");
  assert.match(await t(trainer, "request-fault-0").innerText(), /At 2\.4 s: Your left elbow drifts out at 2\.4 s/);
  assert.equal(await t(trainer, "request-clip").count(), 0, "negative: no video element for the trainer");
  assert.equal(await t(trainer, "request-clip-off").innerText(), "The video was not included.");
  assert.match(await t(trainer, "request-meta-notice").innerText(), /When they press Run, the note is sent to Meta\./);
  const seen = await bodyText(trainer);
  for (const secret of [FOLLOWER, "example.com", first, second]) assert.equal(seen.includes(secret), false, `negative: the trainer's page holds no "${secret}"`);
  assert.equal(/\bu-[0-9a-f]{24}\b/.test(seen), false, "negative: no user id");
  const requestId = new URL(trainer.url()).hash.split("/").pop();
  const detail = JSON.parse((await api(trainer, `api/me/note-requests/${requestId}`)).body);
  assert.equal(detail.clip, null);
  assert.deepEqual(Object.keys(detail).filter((k) => /job|user|email|follower/.test(k)), [], "negative: no id field in the answer");
  const list = JSON.parse((await api(trainer, "api/me/note-requests")).body);
  assert.equal(list.requests.length, 1, "the trainer sees one request, not the follower's other take");
  await shot(trainer, "4-trainer-request.png");
  ok("trainer sees score and fault, no clip, no id or email, only the one take");

  // 3. the trainer answers at the fault time
  await t(trainer, "request-at").selectOption("2.4");
  await t(trainer, "request-note").fill(NOTE);
  assert.equal(await t(trainer, "request-count").innerText(), `${NOTE.length} of 600`);
  await t(trainer, "request-send").tap();
  await t(trainer, "request-closed").waitFor();
  assert.equal(await t(trainer, "request-closed").innerText(), "Note sent.");
  assert.equal(await t(trainer, "request-answer").innerText(), NOTE);
  assert.equal(await t(trainer, "request-sent").count(), 0, "negative: once answered the take is no longer shown");
  ok("trainer answered with a note at 2.4 s");

  // 4. the follower reads it: result page, Me page, history page
  await follower.reload();
  await t(follower, "note-received").waitFor();
  assert.equal(await t(follower, "note-received-text").innerText(), NOTE);
  assert.equal(await t(follower, "note-received-moment").innerText(), "At 2.4 s");
  assert.match(await t(follower, "note-received").innerText(), /Note from A Simon trainer/);
  assert.equal(await t(follower, "ask-open").count(), 0, "negative: no second request button on an answered take");
  await shot(follower, "5-note-on-result.png");
  await follower.goto(`${base}#/me`);
  await t(follower, "notes-received").waitFor();
  assert.equal(await t(follower, "notes-received").innerText(), "1 new note from trainers");
  await follower.goto(`${base}#/me/${entry}`);
  await t(follower, "history-notes").waitFor();
  assert.match(await t(follower, "history-note-0").innerText(), /Take \d/);
  assert.equal(await t(follower, "history-note-card-0-text").innerText(), NOTE);
  await shot(follower, "6-note-on-history.png");
  await follower.goto(`${base}#/me`);
  await t(follower, "me-email").waitFor();
  await follower.waitForTimeout(600);
  assert.equal(await t(follower, "notes-received").count(), 0, "negative: the notice counts since the last visit, so it is gone now");
  ok("follower reads the note on the result, Me and history pages; the notice shows once");

  // 5. the third account and a signed-out visitor see nothing
  for (const url of [`api/me/note-requests/${requestId}`, `api/me/note-requests/${requestId}/clip.mp4`]) {
    assert.equal((await api(third, url)).status, 404, `third account: ${url}`);
  }
  assert.equal((await postJson(third, `api/me/note-requests/${requestId}/answer`, { note: "Hi" })).status, 404);
  assert.equal((await api(third, `api/me/takes/${first}/ask-trainer`)).status, 404, "another account's take cannot be sent");
  assert.equal((await api(follower, `api/me/note-requests/${requestId}`)).status, 404, "not even the asker opens the trainer's page");
  await third.goto(`${base}#/me/notes/${requestId}`);
  await t(third, "request-gone").waitFor();
  assert.equal((await bodyText(third)).includes(NOTE), false, "negative: the third account never sees the note");
  await third.goto(`${base}#/me`);
  await t(third, "me-email").waitFor();
  await third.waitForTimeout(600);
  assert.equal(await t(third, "notes-card").count() === 0 || await t(third, "notes-card").isHidden(), true, "no card for an account with nothing");
  const clean = await browser.newContext({ viewport: { width: 412, height: 915 } });
  const anon = await clean.newPage();
  await anon.goto(base);
  for (const url of [`api/me/note-requests/${requestId}`, "api/me/note-requests", `api/me/takes/${first}/ask-trainer`]) {
    assert.equal((await api(anon, url)).status, 401, `signed out: ${url}`);
  }
  await anon.goto(`${base}#/result/${first}`);
  await anon.waitForTimeout(800);
  assert.equal(await t(anon, "ask-open").count(), 0, "negative: a signed-out visitor sees no button");
  ok("third account and signed-out visitor get 404 and 401 and see nothing");

  // 6. withdraw closes the trainer's page
  await follower.goto(`${base}#/result/${second}`);
  await t(follower, "ask-open").tap();
  await t(follower, "ask-send").tap();
  await t(follower, "ask-withdraw").waitFor();
  const open = JSON.parse((await api(trainer, "api/me/note-requests")).body).requests.find((r) => r.state === "asked");
  assert.ok(open, "the trainer sees the new request");
  await t(follower, "ask-withdraw").tap();
  await t(follower, "ask-open").waitFor();
  assert.equal((await api(trainer, `api/me/note-requests/${open.id}`)).status, 404, "the trainer's access ends on the next request");
  await trainer.goto(`${base}#/me/notes/${open.id}`);
  await t(trainer, "request-gone").waitFor();
  ok("a withdrawn request closes the trainer's page");

  assert.deepEqual(errors, [], "no console errors or page errors");
  console.log(`${passed} steps passed`);
} finally {
  await browser.close();
  server.kill();
}
