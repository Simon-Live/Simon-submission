// Browser drive at 412x915 of the Part 7 UI halves of TICKET-266 (language reach) and TICKET-269 (Ask this take) on the result page.
// The sentences in other languages and every model answer are SEEDED in this file and the harness, not a model's output; the
// languages are not reviewed by a native reader. Run:
//   PLAYWRIGHT_DIR=<node_modules> /home/gingy/claude-template/scripts/with-browser-slot.sh node tests/part7/lang_take_ask.browser.mjs
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { serveRoot } from "./serve_static.mjs";
import { isLaneModule404, isPickerRequest404 } from "./lane_modules.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const { chromium } = createRequire(path.join(process.env.PLAYWRIGHT_DIR || path.resolve(here, "../../node_modules"), "x.js"))("playwright");
const SHOTS = process.env.SHOTS_DIR || path.join(here, "screens");
fs.mkdirSync(SHOTS, { recursive: true });
const JOB = "abcdef123456";
const STUB = {  // the other lanes' modules, as in result_additions.browser.mjs
  "voice.js": "export function mountVoiceSlots() {}",
  "second-opinion.js": "export function mountSecondOpinion() {}",
  "export.js": "export function mountExportButton() {}",
  "narration.js": "export function mountNarration() {}",
};
const ASK_URL = `api/me/history/ask-take/${JOB}`;
const ANSWER = {  // the route's view of a SEEDED Part 5 simon.ask.v1 document
  status: "ok", text: "Your right elbow sits further out than the example at 6.2 s.", source: "model", validated: true, live: true, model: "muse-wonder-1.0",
  message: "", remaining: 19, replaced: 0, tool_calls: [{ name: "get_faults", ok: true }, { name: "seek", ok: true }],
  actions: [{ tool: "seek", t: 6.2, limb: null, joints: [] }, { tool: "spotlight", t: 6.2, limb: "right_arm", joints: ["right_shoulder", "right_elbow", "right_wrist"] }],
  sent: { model: "muse-wonder-1.0" }, usage: { input_tokens: 2100, cached_tokens: 0, output_tokens: 190, usd: 0.0123, calls: 2 },
};

const { server, port } = await serveRoot();
const browser = await chromium.launch({ args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"] });
const errors = [];
let passed = 0;
const ok = (name) => { passed++; console.log(`ok - ${name}`); };
const tid = (page, id) => page.getByTestId(id);

async function open(query, { signedIn = false, canAsk = true, asks = [] } = {}) {
  const ctx = await browser.newContext({ viewport: { width: 412, height: 915 }, hasTouch: true, reducedMotion: "reduce", deviceScaleFactor: 2 });
  await ctx.addInitScript(() => { try { localStorage.setItem("simon.result.more", "open"); } catch { /* blocked */ } });   // "More" holds Ask this take
  const page = await ctx.newPage();
  // The harness answers few routes; an unrouted API path is a 404 the page handles (the browser logs it as a console error).
  // Anything else on the console, and every uncaught error, fails the run.
  const expected = (m) => /status of 404/.test(m.text()) || isLaneModule404(m.location().url) || isPickerRequest404(m.location().url);
  page.on("console", (m) => { if (m.type() === "error" && !expected(m)) errors.push(`${query}: ${m.text()} ${m.location().url}`); });
  page.on("pageerror", (e) => errors.push(`${query}: ${e.message}`));
  const json = (route, body, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
  await page.route(`**/api/results/${JOB}/video.mp4`, (r) => r.continue({ url: `http://127.0.0.1:${port}/tests/part7/fixtures/coach.webm` }));
  await page.route("**/api/auth/me", (r) => json(r, signedIn ? { available: true, signed_in: true, email: "a@b.co", user_id: "u-1" } : { available: false }));
  await page.route(`**/api/results/${JOB}/*.json`, (r) => json(r, { error: "gone" }, 404));
  await page.route("**/catalog/api/entries/*", (r) => json(r, { id: "lateral-raise-0f13199f", name: "Lateral raise" }));
  for (const [file, body] of Object.entries(STUB)) await page.route(`**/web/${file}`, (r) => r.fulfill({ contentType: "text/javascript", body }));
  await page.route(`**/${ASK_URL}`, (r) => {
    if (r.request().method() === "GET") {
      return canAsk ? json(r, { retention: true, can_ask: true, suggestions: ["When does my elbow in show up in this take?"], limit: 20, remaining: 20, max_chars: 200 })
        : json(r, { code: "not_found", message: "That take was not found." }, 404);
    }
    asks.push(JSON.parse(r.request().postData()));
    return json(r, ANSWER);
  });
  await page.goto(`http://127.0.0.1:${port}/tests/part7/harness/result-additions.html?case=ok${query}`);
  await page.waitForFunction(() => window.__ready === true, null, { timeout: 150000 }).catch((e) => { throw new Error(`${query}: the harness never became ready; page errors: ${errors.join(" | ")}; ${e.message}`); });
  await page.waitForTimeout(500);
  return page;
}

try {
  // ---- TICKET-266 AC-4, AC-5: Arabic at 412 px ----------------------------------------------------------------
  // The lean result (team, 2026-11-02) draws no fault list: "What to work on" shows Part 5's insights, which are
  // not translated, and the Arabic fault lines are spoken by the stage's voice switch. The language notes sit in "More".
  const ar = await open("&lang=ar");
  assert.equal(await tid(ar, "fault-list").count(), 0, "negative: no fault list");
  assert.equal(await tid(ar, "insight-list").getAttribute("dir"), null, "the insights are not mirrored");
  assert.deepEqual(await ar.evaluate(() => ({ inner: innerWidth, scroll: document.documentElement.scrollWidth })), { inner: 412, scroll: 412 }, "no sideways scroll at 412 px");
  assert.match(await tid(ar, "lang-note-0").textContent(), /not been reviewed by a native reader/);
  assert.match(await tid(ar, "lang-note-1").textContent(), /CC-BY-NC 4\.0/);
  assert.ok(await tid(ar, "lang-note-0").isVisible(), "in More");
  await ar.context().close();
  const en = await open("");
  assert.equal(await en.locator('[data-testid^="lang-note-"]').count(), 0, "negative: English shows no language notes");
  await en.context().close();
  const hi = await open("&lang=hi");
  assert.match(await tid(hi, "lang-note-0").textContent(), /not been reviewed/);
  await hi.context().close();
  ok("TICKET-266 AC-4, AC-5: no sideways scroll at 412 px; Hindi and Arabic say not reviewed and the voice licence (in More); English shows neither");

  // ---- TICKET-266 AC-3: the browser language reaches the request, in a real page ------------------------------
  {
    const ctx = await browser.newContext({ viewport: { width: 412, height: 915 }, locale: "es-MX" });
    const page = await ctx.newPage();
    assert.equal(await page.evaluate(() => navigator.language), "es-MX");
    await page.goto(`http://127.0.0.1:${port}/tests/part7/harness/result-additions.html?case=fixture`);
    const picked = await page.evaluate(async () => {
      const m = await import("../../../web/follow-lang.js");
      return { cur: m.currentLang(localStorage), extra: m.langExtra({ part5: { lang: true } }, localStorage), stored: localStorage.getItem("simon.lang") };
    });
    assert.deepEqual(picked, { cur: "es", extra: { lang: "es" }, stored: null });
    await ctx.close();
    ok("TICKET-266 AC-3: navigator.language es-MX with empty storage sends lang es and stores nothing");
  }

  // ---- TICKET-269: Ask this take moves the player -------------------------------------------------------------
  {
    const asks = [];
    const page = await open("", { signedIn: true, asks });
    await tid(page, "take-ask").waitFor();
    assert.equal(await page.locator("#take-ask-question").evaluate((n) => n.labels.length), 1, "the question box has a label");
    await tid(page, "take-ask-suggestion-0").click();
    await tid(page, "take-ask-lead").waitFor();
    assert.deepEqual(asks, [{ question: "When does my elbow in show up in this take?" }]);
    await page.waitForFunction(() => Math.abs(window.__r.coach.video.currentTime - 6.2) < 0.3, null, { timeout: 15000 });
    const clock = await page.evaluate(() => window.__r.coach.video.currentTime);
    await page.waitForFunction(() => (document.querySelector("[data-highlighted-joints]")?.getAttribute("data-highlighted-joints") || "").split(",").includes("right_elbow"));
    assert.equal(await page.locator('[data-testid^="take-ask-step-"]').count(), 2, "both steps are listed");
    assert.equal(await tid(page, "take-ask-source").getAttribute("data-validated"), "true");
    assert.match(await tid(page, "take-ask-source").textContent(), /^The model's answer/);
    assert.match(await tid(page, "take-ask-receipt").textContent(), /muse-wonder-1\.0 through Part 5/);
    assert.match(await tid(page, "take-ask-step-0").textContent(), /^Moved the player to 6\.2 s\.$/);
    assert.equal(await tid(page, "take-ask-answer").getAttribute("aria-live"), "polite");
    await tid(page, "take-ask").screenshot({ path: path.join(SHOTS, "take-ask-412.png") });
    assert.deepEqual(await page.evaluate(() => ({ inner: innerWidth, scroll: document.documentElement.scrollWidth })), { inner: 412, scroll: 412 });
    // a cited second is a button that moves the player again
    await page.evaluate(() => window.__r.seek(1));
    await tid(page, "take-ask-cite-0").click();
    await page.waitForFunction(() => Math.abs(window.__r.coach.video.currentTime - 6.2) < 0.3, null, { timeout: 15000 });
    assert.ok(Math.abs(clock - 6.2) < 0.3);
    await page.context().close();
    ok("TICKET-269: a question moves the player to the cited second (video clock), lists the steps, and a cite moves it again");
  }
  {
    const asks = [];
    const page = await open("", { signedIn: true, canAsk: false, asks });
    await page.waitForTimeout(500);
    assert.equal(await page.locator('[data-testid="take-ask"]').count(), 0, "negative: a take that is not the caller's shows no box");
    assert.deepEqual(asks, [], "and sends no question");
    await page.context().close();
    const out = await open("", { signedIn: false });
    assert.equal(await out.locator('[data-testid="take-ask"]').count(), 0, "negative: signed out shows no box");
    await out.context().close();
    ok("TICKET-269: not the owner or signed out leaves no box and no question");
  }

  assert.deepEqual(errors, [], errors.join("\n"));
  ok("no console errors");
} finally {
  await browser.close();
  server.close();
}
console.log(`${passed} passed`);
