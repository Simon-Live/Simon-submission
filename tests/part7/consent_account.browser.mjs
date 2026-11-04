// B2 on the real server (no mocked auth or policy): account A ticks everything, including Meta, signs out; account B signs in on the same
// browser and is asked again, and nothing of A's answers or tick reaches B's job requests. docs/specs/consent-and-age.md AC-CA20.
//   scripts/with-browser-slot.sh node tests/part7/consent_account.browser.mjs      (PLAYWRIGHT_DIR=/path/to/node_modules)
import assert from "node:assert/strict";
import path from "node:path";
import { spawn } from "node:child_process";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const req = createRequire(path.join(process.env.PLAYWRIGHT_DIR || path.resolve(here, "../../node_modules"), "x.js"));
const { chromium } = req("playwright");
const PORT = 8200 + Math.floor(Math.random() * 300);
const BASE = `http://127.0.0.1:${PORT}`;
const server = spawn("python3", [path.join(here, "serve_consent_real.py"), String(PORT)], { stdio: "inherit" });
process.on("exit", () => server.kill());
for (let i = 0; i < 100; i++) {
  try { if ((await fetch(`${BASE}/api/health`)).ok) break; } catch { await new Promise((r) => setTimeout(r, 150)); }
}
const tid = (page, id) => page.locator(`[data-testid="${id}"]:visible`).first();
const policy = await (await fetch(`${BASE}/api/policy`)).json();
assert.equal(policy.consent.required, true, "the real policy requires consent");
assert.equal(policy.consent.meta_item, "meta", "the real policy offers the Meta tick");

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 412, height: 915 } });
const page = await ctx.newPage();
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));

async function signIn(email) {
  await page.goto(`${BASE}/#/signin`);
  await tid(page, "auth-email").fill(email);
  await tid(page, "auth-send").click();
  await tid(page, "auth-code").waitFor();
  let code = "";
  for (let i = 0; i < 40 && !code; i++) {
    const out = await (await fetch(`${BASE}/api/auth/outbox?email=${encodeURIComponent(email)}`)).json();
    code = out.messages?.[0]?.code || "";
    if (!code) await new Promise((r) => setTimeout(r, 150));
  }
  assert.ok(code, "the test mailbox holds the code");
  await tid(page, "auth-code").fill(code);
  await tid(page, "auth-verify").click();
  await tid(page, "me-signout").waitFor();
  return (await (await page.request.get(`${BASE}/api/auth/me`)).json()).user_id;
}
// Through the real routes: upload a clip with the stored consent header, then POST api/people with the stored fields (or `body` as given).
const people = (body) => page.evaluate(async (given) => {
  const { consentFields, consentHeader } = await import("/model/consent-store.js");
  const clip = await (await fetch("media/landing-loop.mp4")).blob();
  const up = await fetch("api/uploads", { method: "POST", headers: { "Content-Type": "video/mp4", ...(given ? { "X-Simon-Consent": given.consent.version } : consentHeader()) }, body: clip });
  const upBody = await up.json().catch(() => ({}));
  if (!up.ok) return { step: "upload", status: up.status, body: upBody };
  const res = await fetch("api/people", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...(given || consentFields()), upload_id: upBody.upload_id || upBody.id }) });
  return { step: "people", status: res.status, body: await res.json().catch(() => ({})) };
}, body || null);
const stored = () => page.evaluate(() => JSON.parse(localStorage.getItem("simon.consent") || "null"));
const fields = () => page.evaluate(async () => (await import("/model/consent-store.js")).consentFields());

// A signs in, answers the age question, ticks every point and the Meta tick with its 18 statement.
const idA = await signIn("a@example.com");
await page.goto(`${BASE}/#/record`);
await tid(page, "age-month").selectOption("1");
await tid(page, "age-year").selectOption(String(new Date().getUTCFullYear() - 30));
await tid(page, "age-next").click();
await tid(page, "consent-step").waitFor();
for (const k of ["analysis", "biometric", "processors", "people_in_frame", "meta", "meta-adults"]) await tid(page, `consent-item-${k}`).check();
await tid(page, "consent-agree").click();
await tid(page, "consent-done").waitFor();
let doc = await stored();
assert.equal(doc.account, idA, "the answer is stamped with account A");
assert.equal(doc.items.meta, true);
assert.equal(doc.items.meta_adults, true);
console.log(JSON.stringify(doc), JSON.stringify(await fields()));
assert.equal((await fields()).consent.items.meta, true, "A's job request carries A's tick");
const bodyA = await fields();
const sentA = await people();
console.log("A posts", sentA.step, sentA.status, JSON.stringify(sentA.body).slice(0, 120));
assert.equal(sentA.step, "people", "A's upload passed the consent header");
assert.ok(sentA.status < 400, "A's own job request is accepted");
console.log("ok - A answers and ticks Meta; the stamp is A's; A's job request is accepted");

// A signs out through the Me page: the whole answer is gone.
await page.goto(`${BASE}/#/me`);
await tid(page, "me-signout").click();
await page.waitForFunction(() => localStorage.getItem("simon.consent") === null);
console.log("ok - sign-out drops the stored answer");

// B signs in on the same browser: asked again, nothing of A's is sent.
const idB = await signIn("b@example.com");
assert.notEqual(idA, idB);
await page.goto(`${BASE}/#/record`);
await tid(page, "age-step").waitFor();
assert.equal(await page.locator('[data-testid="consent-done"]').count(), 0, "B is not shown A's agreement");
assert.equal(await stored(), null, "B starts with no stored answer");
assert.deepEqual(await fields(), {}, "B's job request carries no consent of A's");
// A's whole request body, replayed by B's session: every point is A's, so the server refuses it like a missing answer.
const replay = await people(bodyA);
assert.equal(replay.step, "people", "the upload itself went through");
assert.equal(replay.status, 400, `B's session cannot replay A's points: ${JSON.stringify(replay)}`);
assert.match(replay.body.error || "", /Agree to each point/);
// B answers for B (no Meta) and posts a job through the real routes.
await tid(page, "age-month").selectOption("1");
await tid(page, "age-year").selectOption(String(new Date().getUTCFullYear() - 30));
await tid(page, "age-next").click();
for (const k of ["analysis", "biometric", "processors", "people_in_frame"]) await tid(page, `consent-item-${k}`).check();
await tid(page, "consent-agree").click();
const sentB = await people();
assert.ok(sentB.step === "people" && sentB.status < 400, `B's own job request: ${JSON.stringify(sentB)}`);
console.log("ok - B is asked again, inherits nothing, and A's body replayed by B is refused");

// Account change with no sign-out in between (A's answer left in storage, B's session cookie): dropped on the first api/auth/me.
await page.evaluate((a) => localStorage.setItem("simon.consent", JSON.stringify({ age_band: "adult", version: "x", items: { meta: true }, at: "2026-11-04T00:00:00Z", account: a })), idA);
await page.reload();
await tid(page, "age-step").waitFor();
assert.equal(await stored(), null, "an answer stamped for another account is dropped on load");
console.log("ok - a leftover answer of another account is dropped");

// Signed out first, then someone signs in: the answer waits for that person. Nothing is sent or stamped until they confirm.
const answerSignedOut = async (year) => {
  await page.goto(`${BASE}/#/me`);
  await tid(page, "me-signout").click();
  await page.waitForFunction(() => location.hash === "#/");
  assert.equal((await (await page.request.get(`${BASE}/api/auth/me`)).json()).signed_in, false);
  await page.goto(`${BASE}/#/record`);
  await tid(page, "age-month").selectOption("1");
  await tid(page, "age-year").selectOption(String(new Date().getUTCFullYear() - year));
  await tid(page, "age-next").click();
  for (const k of ["analysis", "biometric", "processors", "people_in_frame", "meta", "meta-adults"]) await tid(page, `consent-item-${k}`).check();
  await tid(page, "consent-agree").click();
  await tid(page, "consent-done").waitFor();
  assert.equal((await stored()).account, "");
};

// Path 1: the same person signs in and confirms.
await answerSignedOut(30);
const idC = await signIn("c@example.com");
await page.goto(`${BASE}/#/record`);
await tid(page, "consent-confirm").waitFor();
assert.match(await tid(page, "consent-confirm-age").innerText(), /18 or older/);
assert.equal(await page.locator('[data-testid="consent-confirm-points"] li:visible').count(), 4, "the four points are shown");
assert.equal((await stored()).account, "", "not stamped before the confirm");
assert.deepEqual(await fields(), {}, "no consent goes before the confirm");
const early = await people();
assert.ok(early.status >= 400, `nothing is accepted before the confirm: ${JSON.stringify(early)}`);
await tid(page, "consent-confirm-yes").click();
await tid(page, "consent-done").waitFor();
doc = await stored();
assert.equal(doc.account, idC, "stamped for C once C confirms");
assert.equal(doc.items.meta, undefined, "the signed-out Meta tick stays dropped");
const sentC = await people();
assert.ok(sentC.step === "people" && sentC.status < 400, `C reaches a job after confirming: ${JSON.stringify(sentC)}`);
console.log("ok - signed out, sign in, confirm once: the job is accepted and the tick is gone");

// Path 2: a different person (a teenager) signs in after someone answered signed out: they answer again and their answers count.
await answerSignedOut(30);
await signIn("d@example.com");
await page.goto(`${BASE}/#/record`);
await tid(page, "consent-confirm").waitFor();
await tid(page, "consent-confirm-redo").click();
await tid(page, "age-step").waitFor();
assert.equal(await stored(), null, "the other person's answer is gone");
await tid(page, "age-month").selectOption("1");
await tid(page, "age-year").selectOption(String(new Date().getUTCFullYear() - 15));
await tid(page, "age-next").click();
for (const k of ["analysis", "biometric", "processors", "people_in_frame"]) await tid(page, `consent-item-${k}`).check();
await tid(page, "consent-agree").click();
doc = await stored();
assert.equal(doc.age_band, "minor", "D's own age counts, not the adult answer");
const sentD = await people();
assert.ok(sentD.step === "people" && sentD.status < 400, `D's own answer reaches a job: ${JSON.stringify(sentD)}`);
console.log("ok - a different person answers again and their answer counts");

// Pending api/auth/me (the real answer held back 1.5 s): the confirm waits for it, nothing is sent meanwhile, then it asks once.
await answerSignedOut(30);
await signIn("e@example.com");
await page.goto(`${BASE}/#/record`);
await tid(page, "consent-confirm").waitFor();
await page.evaluate(() => { localStorage.setItem("simon.consent", JSON.stringify({ ...JSON.parse(localStorage.getItem("simon.consent")), account: "" })); });
await page.route("**/api/auth/me", async (route) => { await new Promise((r) => setTimeout(r, 1500)); await route.continue(); });
const waited = await page.evaluate(async () => {
  const { ensureConsent } = await import("/consent-gate.js");
  const { fetchMe } = await import("/auth.js");
  const box = document.createElement("div");
  document.body.append(box);
  let went = 0;
  const t0 = Date.now();
  ensureConsent(box, () => { went += 1; }, { refresh: fetchMe });
  const early = { went, confirm: Boolean(box.querySelector('[data-testid="consent-confirm"]')) };
  await new Promise((r) => setTimeout(r, 2200));
  return { early, late: { went, confirm: Boolean(box.querySelector('[data-testid="consent-confirm"]')) }, ms: Date.now() - t0 };
});
await page.unroute("**/api/auth/me");
assert.deepEqual(waited.early, { went: 0, confirm: false }, "pending: nothing goes on, no confirm yet");
assert.deepEqual(waited.late, { went: 0, confirm: true }, "after the real answer: one confirm, still nothing sent");
console.log("ok - a pending api/auth/me holds the take; the confirm appears once the account is known");

// Offline: api/auth/me cannot be reached. The stamped answer stays, no age step replaces the saved path, and the caller is told "unreachable".
await page.goto(`${BASE}/#/me`);
await tid(page, "me-signout").click();
await page.waitForFunction(() => location.hash === "#/");
const idF = await signIn("f@example.com");
await page.goto(`${BASE}/#/record`);
await tid(page, "age-step").waitFor();
await tid(page, "age-month").selectOption("1");
await tid(page, "age-year").selectOption(String(new Date().getUTCFullYear() - 30));
await tid(page, "age-next").click();
for (const k of ["analysis", "biometric", "processors", "people_in_frame"]) await tid(page, `consent-item-${k}`).check();
await tid(page, "consent-agree").click();
assert.equal((await stored()).account, idF);
await ctx.setOffline(true);
const off = await page.evaluate(async () => {
  const { ensureConsent } = await import("/consent-gate.js");
  const { fetchMe } = await import("/auth.js");
  const box = document.createElement("div");
  let went = 0, unreachable = 0;
  ensureConsent(box, () => { went += 1; }, { refresh: fetchMe, onUnreachable: () => { unreachable += 1; } });
  await new Promise((r) => setTimeout(r, 500));
  return { went, unreachable, ageStep: Boolean(box.querySelector('[data-testid="age-step"]')) };
});
await ctx.setOffline(false);
assert.deepEqual(off, { went: 0, unreachable: 1, ageStep: false }, "offline: the take takes the saved path, not the age step");
assert.equal((await stored()).account, idF, "and the stamped answer is still there");
console.log("ok - offline: an unreachable api/auth/me drops nothing and asks nothing");

await browser.close();
assert.deepEqual(errors, [], `page errors: ${errors.join("; ")}`);
console.log("8 passed");
server.kill();
