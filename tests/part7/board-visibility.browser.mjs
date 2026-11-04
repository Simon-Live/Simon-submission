// Browser drive at 412x915 of "who can see a board" against the REAL routes and the FILE mail transport
// (serve_board_visibility.py: every mail is an .eml under <state>/outbox, nothing is sent). The owner makes a board for
// People I choose through the panel, the invite is mailed, an invited person opens the link signed out, signs in with the
// same address and lands on the board; a wrong account gets a plain line; a removed person loses access.
//   PLAYWRIGHT_DIR=<dir with node_modules> scripts/with-browser-slot.sh node tests/part7/board-visibility.browser.mjs
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const { chromium } = createRequire(path.join(process.env.PLAYWRIGHT_DIR || path.resolve(here, "../../node_modules"), "x.js"))("playwright");
const SHOTS = process.env.SHOTS_DIR || fs.mkdtempSync(path.join(os.tmpdir(), "board-vis-shots-"));
fs.mkdirSync(SHOTS, { recursive: true });

const port = 7700 + Math.floor(Math.random() * 200);
const base = `http://127.0.0.1:${port}/`;
const state = fs.mkdtempSync(path.join(os.tmpdir(), "board-vis-state-"));
const server = spawn("python3", [path.join(here, "serve_board_visibility.py"), String(port), state], { stdio: "inherit" });
for (let i = 0; i < 100; i++) {
  try { if ((await fetch(`${base}api/auth/me`)).ok) break; } catch { await new Promise((r) => setTimeout(r, 150)); }
}

const mails = () => {
  const dir = path.join(state, "outbox");
  return fs.existsSync(dir) ? fs.readdirSync(dir).sort().map((f) => fs.readFileSync(path.join(dir, f), "latin1")) : [];
};
const decoded = (raw) => raw.replace(/=\r?\n/g, "").replace(/=([0-9A-F]{2})/g, (_, h) => String.fromCharCode(parseInt(h, 16)));
async function waitMail(pred) {
  for (let i = 0; i < 80; i++) {
    const found = mails().map(decoded).filter(pred).pop();
    if (found) return found;
    await new Promise((r) => setTimeout(r, 150));
  }
  throw new Error("expected mail did not arrive");
}

async function signIn(page, email) {
  await page.goto(`${base}#/signin`);
  await page.getByTestId("auth-email").fill(email);
  const before = mails().length;
  await page.getByTestId("auth-send").tap();
  await page.getByTestId("auth-code").waitFor();
  const mail = await waitMail((m) => m.includes(`To: ${email}`) && /Your code: \d{6}/.test(m) && mails().length > before);
  await page.getByTestId("auth-code").fill(/Your code: (\d{6})/.exec(mail)[1]);
  await page.getByTestId("auth-verify").tap();
  await page.getByTestId("me-email").waitFor();
}
async function signInOnBoard(page, email) {
  await page.getByTestId("auth-email").fill(email);
  const before = mails().length;
  await page.getByTestId("auth-send").tap();
  await page.getByTestId("auth-code").waitFor();
  const mail = await waitMail((m) => m.includes(`To: ${email}`) && /Your code: \d{6}/.test(m) && mails().length > before);
  await page.getByTestId("auth-code").fill(/Your code: (\d{6})/.exec(mail)[1]);
  await page.getByTestId("auth-verify").tap();
}

const browser = await chromium.launch();
const errors = [];
let passed = 0;
const ok = (name) => { passed++; console.log(`ok - ${name}`); };
const newPage = async () => {
  const ctx = await browser.newContext({ viewport: { width: 412, height: 915 }, deviceScaleFactor: 2, hasTouch: true });
  const page = await ctx.newPage();
  page.on("pageerror", (e) => errors.push(e.message));
  return page;
};
try {
  const owner = await newPage();
  await signIn(owner, "owner@example.com");
  const made = await owner.evaluate(async () => (await fetch("api/challenges", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ entry_id: "lateral-raise", title: "Beat my raises", creator_name: "Sam", kind: "friend" }),
  })).json());
  assert.ok(made.id, "a public board is made first");
  await owner.goto(`${base}#/challenge/${made.id}`);
  await owner.getByTestId("access-panel").waitFor();
  await owner.getByTestId("access-invited").check();
  await owner.getByTestId("access-emails").fill("Ann@Example.com");
  await owner.getByTestId("access-save").tap();
  await owner.getByTestId("mail-result-1").waitFor();
  assert.match(await owner.getByTestId("mail-result-1").textContent(), /Invite sent to ann@example\.com\./);
  assert.match(await owner.getByTestId("access-results").textContent(), /does not promise the mail arrived/);
  await owner.screenshot({ path: path.join(SHOTS, "bv-01-owner-sent.png") });
  ok("the owner chooses People I choose, the invite is mailed and shown as sent only after the transport accepted it");

  const invite = await waitMail((m) => m.includes("To: ann@example.com") && m.includes("invited you"));
  const link = /http:\/\/127\.0\.0\.1:\d+\/#\/challenge\/[\w-]+/.exec(invite)[0];
  assert.ok(link.endsWith(made.id));
  assert.match(invite, /api\/invites\/stop\/[0-9a-f]{32}/);
  assert.match(invite, /Example Address, Test City/);
  ok("the mail carries a plain link, a stop link and the postal address");

  const ann = await newPage();
  await ann.goto(link);
  await ann.getByTestId("invite-signin").waitFor();
  assert.match(await ann.getByTestId("invite-denied").textContent(), /Sign in with the email address the invite was sent to/);
  assert.equal(await ann.getByTestId("challenge-title").count(), 0, "negative: the board is not shown signed out");
  await ann.screenshot({ path: path.join(SHOTS, "bv-02-guest-signed-out.png") });
  await signInOnBoard(ann, "ann@example.com");
  await ann.getByTestId("challenge-title").waitFor();
  assert.equal(await ann.getByTestId("challenge-title").textContent(), "Beat my raises");
  await ann.getByTestId("take-challenge").waitFor();
  await ann.screenshot({ path: path.join(SHOTS, "bv-03-guest-on-board.png") });
  ok("an invited person signs in with the same address and lands on the board with a way to take part");

  await owner.reload();
  await owner.getByTestId("access-list").waitFor();
  assert.match(await owner.getByTestId("access-list").textContent(), /ann@example\.com: Joined/);
  ok("the owner sees that the person joined");

  const bob = await newPage();
  await signIn(bob, "bob@example.com");
  await bob.goto(link);
  await bob.getByTestId("wrong-account").waitFor();
  const said = await bob.getByTestId("wrong-account").textContent();
  await bob.getByTestId("remove-my-score").click(); // two presses; holding no row, the gate answers as before and names nobody
  await bob.getByTestId("remove-my-score").click();
  await bob.waitForFunction(() => /different address/.test(document.querySelector('[data-testid="remove-my-score-note"]').textContent));
  await bob.route("**/api/challenges/*/remove-my-score", (route) => route.fulfill({ status: 200, contentType: "application/json", body: '{"removed": 1}' }));
  await bob.getByTestId("remove-my-score").click(); // the same screen for one who holds a row (the server side: test_release11_fixes.py)
  await bob.getByTestId("remove-my-score").click();
  await bob.waitForFunction(() => document.querySelector('[data-testid="remove-my-score-note"]').textContent === "Your score is off this board.");
  await bob.unroute("**/api/challenges/*/remove-my-score");
  assert.match(said, /signed in with a different address/);
  assert.ok(!/ann@|owner@|Sam/.test(said), "negative: it names nobody and confirms nothing");
  await bob.screenshot({ path: path.join(SHOTS, "bv-04-wrong-account.png") });
  ok("a wrong account gets a plain line that names nobody");

  await owner.route("**/api/challenges/*/access", async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
      visibility: "invited", invites: [{ email: "ann@example.com", joined: true, mail: "failed", failure_id: "inv_0badf00d" }],
      link, mail: [{ email: "cat@example.com", state: "failed", failure_id: "inv_0badf00d" }], movement_private: false, warning: null }) });
  });
  await owner.getByTestId("access-emails").fill("cat@example.com");
  await owner.getByTestId("access-save").tap();
  await owner.getByTestId("mail-retry").waitFor();
  assert.match(await owner.getByTestId("mail-result-1").textContent(), /Could not send to cat@example\.com\. Reference inv_0badf00d/);
  assert.ok(!/Invite sent/.test(await owner.getByTestId("access-results").textContent()), "negative: a failed send never says sent");
  assert.match(await owner.getByTestId("mail-mailto").getAttribute("href"), /^mailto:cat@example\.com\?subject=/);
  await owner.getByTestId("mail-copy").waitFor();
  await owner.screenshot({ path: path.join(SHOTS, "bv-05-failed-send.png") });
  await owner.unroute("**/api/challenges/*/access");
  ok("a failed send shows the reference, Try again, Copy link and a mailto link, never 'sent'");

  await owner.reload();
  await owner.getByTestId("access-remove-1").tap();
  await owner.getByTestId("access-panel").waitFor();
  await ann.reload();
  await ann.getByTestId("wrong-account").waitFor();
  ok("a removed person loses access at once");
  assert.deepEqual(errors, [], `page errors: ${errors.join("; ")}`);
  console.log(`${passed} checks passed; screenshots in ${SHOTS}`);
} finally {
  await browser.close();
  server.kill();
}
