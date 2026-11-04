// Continue when the server refuses a take (offline-takes.md AC-OT10, AC-OT15), driven through the real UI at 412x915
// with Chromium's fake camera and tests/part7/fake_api.py. The prod refusals are answered at the network layer.
//   PLAYWRIGHT_DIR=/path/to/node_modules scripts/with-browser-slot.sh node tests/part7/take-continue.browser.mjs
// Screenshots: SHOTS_DIR (not committed).
import assert from "node:assert/strict";
import path from "node:path";
import { spawn } from "node:child_process";
import { answerConsentStep } from "./consent-step.mjs";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const req = createRequire(path.join(process.env.PLAYWRIGHT_DIR || path.resolve(here, "../../node_modules"), "x.js"));
const { chromium } = req("playwright");
const PORT = 8700 + Math.floor(Math.random() * 300);
const BASE = `http://127.0.0.1:${PORT}`;
const SHOTS = process.env.SHOTS_DIR || "";
const server = spawn("python3", [path.join(here, "fake_api.py"), String(PORT)], { stdio: "inherit" });
process.on("exit", () => server.kill());
for (let i = 0; i < 50; i++) {
  try { if ((await fetch(`${BASE}/api/health`)).ok) break; } catch { await new Promise((r) => setTimeout(r, 100)); }
}
const GENERIC = /could not finish/;
const RESTARTED = { id: "job1", kind: "trainer", status: "failed", stage: "pose", entry_id: null, result: null,
  note: "", reason: "the app restarted before this take finished; record it again", queue_position: null };
const SIGN_IN_BODY = JSON.stringify({ ok: false, error: "Sign in to upload a video.", message: "Sign in to upload a video." });

const browser = await chromium.launch({
  args: ["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream", "--autoplay-policy=no-user-gesture-required"],
});

async function open(signedInAtStart = false) {
  await fetch(`${BASE}/__test/reset`, { method: "POST", body: "{}" });
  const ctx = await browser.newContext({ viewport: { width: 412, height: 915 }, permissions: ["camera"] });
  const page = await ctx.newPage();
  page.on("pageerror", (e) => console.error(`pageerror: ${e.message}`));
  page.on("console", (m) => { if (m.type() === "error") console.error(`console: ${m.text().slice(0, 200)}`); });
  page.on("response", (r) => { if (r.status() >= 400) console.error(`http ${r.status()} ${r.url().replace(BASE, "")}`); });
  const seen = { signedIn: signedInAtStart, refused: 0, accepted: 0, jobs: 0 };
  const json = (r, status, body) => r.fulfill({ status, contentType: "application/json", body: typeof body === "string" ? body : JSON.stringify(body) });
  await page.route("**/api/auth/me", (r) => json(r, 200, { available: true, signed_in: seen.signedIn, email: seen.signedIn ? "a@example.com" : "" }));
  await page.route("**/api/auth/start", (r) => json(r, 202, { ok: true }));
  await page.route("**/api/auth/verify", (r) => { seen.signedIn = true; return json(r, 200, { ok: true }); });
  await page.route("**/api/uploads", (r) => {
    if (r.request().method() !== "POST") return r.fallback();
    if (!seen.signedIn) { seen.refused++; return json(r, 401, SIGN_IN_BODY); }
    seen.accepted++;
    return r.fallback();
  });
  await page.route("**/api/trainer", (r) => { seen.jobs++; return r.fallback(); });
  return { ctx, page, seen, tid: (id) => page.locator(`[data-testid="${id}"]:visible`).first() };
}
const outbox = (page) => page.evaluate(() => new Promise((resolve) => {
  const o = indexedDB.open("simon-local");
  o.onsuccess = () => {
    if (!o.result.objectStoreNames.contains("pending-takes")) { resolve([]); return; }
    const q = o.result.transaction("pending-takes").objectStore("pending-takes").getAll();
    q.onsuccess = () => resolve(q.result.map(({ blob, ...r }) => ({ ...r, blobSize: blob ? blob.size : 0 })));
  };
  o.onerror = () => resolve(null);
}));
async function continueTake(page, tid) {
  await page.goto(`${BASE}/#/record`);
  await answerConsentStep(page); // fake_api.py answers a non-prod policy now; the helper answers the step only if it shows
  await tid("countdown-select").selectOption("0");
  await tid("duration-select").selectOption("5");
  await tid("framing-hint").waitFor();
  await tid("cam-start").click();
  await tid("trim-continue").waitFor({ timeout: 20000 });
  await tid("trim-continue").click();
}
const shot = async (page, name) => { if (SHOTS) await page.screenshot({ path: path.join(SHOTS, `${name}.png`) }); };

try {
  // 1) signed out: told to sign in, the take kept, signed in on the spot, and the same take goes on to the job
  {
    const { ctx, page, seen, tid } = await open();
    await continueTake(page, tid);
    await tid("take-signin-needed").waitFor({ timeout: 20000 });
    assert.equal(await tid("take-signin-needed").innerText(), "Your take is saved on this device. Sign in to send it.");
    assert.doesNotMatch(await page.locator("body").innerText(), GENERIC, "the generic line must be absent");
    const [saved] = await outbox(page);
    assert.ok(saved && saved.blobSize > 0, "the recording is in the outbox");
    assert.equal(saved.last_error.kind, "signin");
    assert.equal(seen.refused, 1);
    await shot(page, "1-signin-prompt");

    await tid("auth-email").fill("a@example.com");
    await tid("auth-send").click();
    await tid("auth-code").fill("123456");
    await shot(page, "2-signin-code");
    await tid("auth-verify").click();
    await tid("save").waitFor({ timeout: 20000 });
    await tid("name").fill("Arm move");
    assert.match(page.url(), /#\/record/, "signing in did not leave the take");
    assert.equal(seen.accepted, 1, "the same take was uploaded after sign-in");
    await tid("save").click();
    await page.waitForURL(/#\/job\/job1/);
    assert.equal(seen.jobs, 1);
    await ctx.close();
  }
  // 2) signed out, then a reload: the take is still there and the banner links to sign-in, with no upload in a loop
  {
    const { ctx, page, seen, tid } = await open();
    await continueTake(page, tid);
    await tid("take-signin-needed").waitFor({ timeout: 20000 });
    await page.goto(`${BASE}/#/`);
    await page.reload();
    await tid("pending-signin").waitFor({ timeout: 20000 });
    assert.equal(await tid("pending-failed").innerText(), "Your take is saved on this device. Sign in to send it.");
    assert.equal(await page.locator('[data-testid="pending-retry"]').count(), 0);
    const [saved] = await outbox(page);
    assert.ok(saved && saved.blobSize > 0, "the recording survives the reload");
    assert.equal(seen.refused, 1, "nothing was sent again while signed out");
    await shot(page, "3-banner-signin");
    await ctx.close();
  }
  // 3) a job cut by a restart: the banner says so, offers Send it again, and that sends a new job
  {
    const { ctx, page, seen, tid } = await open(true);
    await page.route("**/api/jobs/job1", (r) => r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(RESTARTED) }));
    await continueTake(page, tid);
    await tid("save").waitFor({ timeout: 20000 });
    await tid("name").fill("Arm move");
    await tid("save").click();
    await page.waitForURL(/#\/job\/job1/);
    await page.goto(`${BASE}/#/`);
    await tid("pending-stuck").waitFor({ timeout: 45000 });
    const line = await tid("pending-stuck").innerText();
    assert.equal(line, "The app restarted before this take finished. Your recording is still on this device.");
    assert.doesNotMatch(line, /could not be sent/);
    await shot(page, "4-banner-restart");
    await tid("pending-stuck-again").click();
    for (let i = 0; i < 100 && seen.jobs < 2; i++) await new Promise((r) => setTimeout(r, 100));
    assert.equal(seen.jobs, 2, "Send it again asked for a new job");
    await ctx.close();
  }
  console.log("take-continue.browser: all cases passed");
} finally {
  await browser.close();
}
process.exit(0); // the fake server is a child: the driver would otherwise never end
