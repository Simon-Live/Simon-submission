// Browser checks for the result screen's additions on the redesign at 412x915 (docs/specs/result-redesign-additions.md
// AC-R1 to AC-R6). Run:
//   node tests/part7/result_additions.browser.mjs
// Playwright comes from `npm i` in this repo, or from PLAYWRIGHT_DIR (a node_modules folder). The job's routes are
// answered here with page.route; the mesh files are the real Part 2 output in web/mesh-demo/.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { serveRoot } from "./serve_static.mjs";
import { isLaneModule404 } from "./lane_modules.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const req = createRequire(path.join(process.env.PLAYWRIGHT_DIR || path.resolve(here, "../../node_modules"), "x.js"));
const { chromium } = req("playwright");
const SHOTS = process.env.SHOTS_DIR || path.join(here, "screens");
fs.mkdirSync(SHOTS, { recursive: true });
const web = path.resolve(here, "../../web");
const JOB = "abcdef123456";

const COCO = ["nose", "left_eye", "right_eye", "left_ear", "right_ear", "left_shoulder", "right_shoulder", "left_elbow",
  "right_elbow", "left_wrist", "right_wrist", "left_hip", "right_hip", "left_knee", "right_knee", "left_ankle", "right_ankle"];
const BONES = [[0, 1], [0, 2], [1, 3], [2, 4], [0, 5], [0, 6], [5, 6], [11, 12], [5, 11], [6, 12], [5, 7], [7, 9], [6, 8],
  [8, 10], [11, 13], [13, 15], [12, 14], [14, 16]];
const pose = COCO.map((_, i) => [0.3 + (i % 5) * 0.1, 0.1 + Math.floor(i / 5) * 0.2]);
const SKELETON = { format: "simon.skeleton2d.v1", image_size: [160, 120], joints: COCO, bones: BONES,
  frames: Array.from({ length: 121 }, (_, k) => ({ t: +(k * 0.1).toFixed(1), pts: pose })) };
const MODELS = { job: JOB, job_seconds: 163, models: [
  { id: "sam31-trainer", model: "SAM 3.1", maker: "Meta", clip: "trainer", status: "live", seconds: 41.2, facts: { via: "meta_api", frames: 200 } },
  { id: "spark-sections", model: "Muse Spark", maker: "Meta", clip: "trainer", status: "cached", seconds: 41.2, facts: { via: "meta_api", repetitions: 4 } },
  { id: "sam31-you", model: "SAM 3.1", maker: "Meta", clip: "you", status: "not_run", seconds: null, facts: { reason: "one_person" } },
  { id: "sam3d-you", model: "SAM 3D Body", maker: "Meta", clip: "you", status: "live", seconds: 52.1, facts: { via: "local_gpu", frames: 121 } },
  { id: "spark-phrasing", model: "Muse Spark", maker: "Meta", clip: "you", status: "fallback", seconds: 3.0, facts: { ran: "template", reason: "budget", lines: 2 } },
] };
// stand-ins for the other session's modules: each records its call so the contract can be checked
const STUB = {
  "voice.js": "export function mountVoiceSlots(root, ctx) { root.querySelectorAll('[data-testid=voice-slot]').forEach((s) => { const b = document.createElement('button'); b.type = 'button'; b.className = 'sr-btn'; b.textContent = 'Hear this line'; s.append(b); }); (window.__lane ||= []).push({ fn: 'voice', slots: root.querySelectorAll('[data-testid=voice-slot]').length, ctx }); }",
  "second-opinion.js": "export function mountSecondOpinion(section, ctx) { section.textContent = 'second'; (window.__lane ||= []).push({ fn: 'second', ctx }); }",
  "export.js": "export function mountExportButton(slot, jobId) { slot.textContent = 'export ' + jobId; (window.__lane ||= []).push({ fn: 'export', jobId }); }",
  "narration.js": "export function mountNarration(root, ctx) { (window.__lane ||= []).push({ fn: 'narration', ctx, rows: root.querySelectorAll('[data-at-s]').length }); }",
};

const { server, port } = await serveRoot();
const browser = await chromium.launch({ args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"] });
const errors = [];
let passed = 0;
const ok = (name) => { passed++; console.log(`ok - ${name}`); };

/** Open the harness with the job's routes answered. `mesh`: "both" (real meshes), "none" (index nulls), "broken" (404 files). */
async function open(kase, { mesh = "both", stubs = true, models = MODELS, reduced = false } = {}) {
  const ctx = await browser.newContext({ viewport: { width: 412, height: 915 }, hasTouch: true, reducedMotion: reduced ? "reduce" : "no-preference" });
  const page = await ctx.newPage();
  // the 404s a case asks for: missing modules (no stubs), broken mesh files, a missing models.json
  const expected = (url) => (!stubs && isLaneModule404(url)) || (mesh === "broken" && /\/mesh\/(you|trainer)\/mesh3d/.test(url))
    || (!models && url.endsWith("/models.json"));
  page.on("console", (m) => { if (m.type() === "error" && !expected(m.location().url)) errors.push(`${kase}: ${m.text()} ${m.location().url}`); });
  page.on("pageerror", (e) => errors.push(`${kase}: ${e.message}`));
  const json = (route, body, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
  // the video goes to the static server, which answers Range requests: a fulfilled body cannot be seeked
  await page.route(`**/api/results/${JOB}/video.mp4`, (r) => r.continue({ url: `http://127.0.0.1:${port}/tests/part7/fixtures/coach.webm` }));
  await page.route("**/api/auth/me", (r) => json(r, { available: false }, 200)); // sign-in off, as a server without mail answers (identity.md)
  await page.route(`**/api/results/${JOB}/models.json`, (r) => json(r, models || { error: "gone" }, models ? 200 : 404));
  await page.route(`**/api/results/${JOB}/skeleton2d.json`, (r) => json(r, SKELETON));
  await page.route(`**/api/results/${JOB}/mesh.json`, (r) => json(r, mesh === "none" ? { trainer: null, you: null }
    : { trainer: `api/results/${JOB}/mesh/trainer/mesh3d.json`, you: `api/results/${JOB}/mesh/you/mesh3d.json` }));
  await page.route(`**/api/results/${JOB}/mesh/*/*`, (r) => {
    const [who, file] = new URL(r.request().url()).pathname.split("/").slice(-2);
    if (mesh === "broken") return r.fulfill({ status: 404, body: "" });
    return r.fulfill({ path: path.join(web, "mesh-demo", who === "you" ? "follower" : "trainer", file) });
  });
  await page.route("**/catalog/api/entries/*", (r) => json(r, { id: "lateral-raise-0f13199f", name: "Lateral raise" }));
  if (stubs) for (const [file, body] of Object.entries(STUB)) await page.route(`**/web/${file}`, (r) => r.fulfill({ contentType: "text/javascript", body }));
  await page.goto(`http://127.0.0.1:${port}/tests/part7/harness/result-additions.html?case=${kase}`);
  await page.waitForFunction(() => window.__ready === true);
  await page.waitForTimeout(600);
  return page;
}
const tid = (page, id) => page.getByTestId(id);
const inView = (page, id) => tid(page, id).first().evaluate((n) => {
  const r = n.getBoundingClientRect();
  return r.height > 0 && r.top >= 0 && r.bottom <= innerHeight + 1;
});

try {
  // ---- R1 how this was made -----------------------------------------------------------------------------------
  const page = await open("ok");
  await tid(page, "models-used").waitFor();
  assert.equal(await page.locator('[data-testid="models-used"] .hm-step').count(), 5);
  assert.equal(await tid(page, "model-sam3d-you").getAttribute("data-status"), "live");
  assert.equal(await tid(page, "model-sam3d-you-status").textContent(), "Ran live");
  assert.equal(await tid(page, "model-spark-sections-status").textContent(), "Saved run reused");
  assert.equal(await tid(page, "model-spark-phrasing-status").textContent(), "Fallback");
  assert.match(await tid(page, "model-spark-phrasing-detail").textContent(), /^Used template wording: the Meta budget was used up$/);
  assert.equal(await tid(page, "model-sam31-you-status").textContent(), "Not used");
  assert.equal(await tid(page, "models-made-with").textContent(), "Made with Meta's SAM 3.1, Muse Spark and SAM 3D Body.");
  assert.equal(await tid(page, "models-total").textContent(), "Your take, from upload to result: 2 min 43 s.");
  // it sits right under the summary, before the other panels
  const order = await page.evaluate(() => [...document.querySelectorAll('[data-testid="result-summary"], [data-testid="models-used"], [data-testid="stage"]')].map((n) => n.dataset.testid));
  assert.deepEqual(order, ["result-summary", "models-used", "stage"]);
  await tid(page, "models-used").screenshot({ path: path.join(SHOTS, "additions-models-used.png") });
  ok("AC-R1 how this was made: every row from models.json, fallback labelled, made-with names only models that ran");

  // ---- R4 the reveal ------------------------------------------------------------------------------------------
  // the repaint for the routine's name ("Lateral raise, rep ...") lands mid-count and carries it on to the end
  await page.waitForFunction(() => /Lateral raise/.test(document.querySelector(".rs-worst h3")?.textContent || ""));
  await page.waitForFunction(() => document.querySelector('[data-testid="summary-score"]').dataset.reveal === "done");
  assert.equal(await tid(page, "summary-score").locator(".rs-ring-value").textContent(), "77");
  assert.equal(await tid(page, "summary-grade").textContent(), "C");
  // the same result mounted again does not play it again
  await page.evaluate(async () => { window.__r.destroy(); window.__lane = []; window.__r = await window.__mount(); });
  await page.waitForFunction(() => /Lateral raise/.test(document.querySelector(".rs-worst h3")?.textContent || ""));
  assert.equal(await tid(page, "summary-score").getAttribute("data-reveal"), null);
  assert.equal(await tid(page, "summary-score").locator(".rs-ring-value").textContent(), "77");
  await tid(page, "models-used").waitFor();
  ok("AC-R4 the ring counts up to Part 5's score once per result, the grade lands, a mid-count repaint carries it on");

  // ---- R6 the other session's mount points --------------------------------------------------------------------
  assert.equal(await tid(page, "voice-slot").count(), 2);
  assert.deepEqual(await page.locator('[data-testid="voice-slot"]').evaluateAll((ns) => ns.map((n) => [n.dataset.faultIndex, n.dataset.atS])), [["0", "6.2"], ["1", "9.1"]]);
  assert.equal(await tid(page, "second-opinion-slot").count(), 1);
  assert.equal(await page.locator('.rs-actions [data-testid="export-slot"]').textContent(), `export ${JOB}`);
  const lane = await page.evaluate(() => (window.__lane || []).map((x) => ({ fn: x.fn, jobId: x.jobId || (x.ctx && x.ctx.jobId) || null,
    entryId: x.ctx && x.ctx.entryId, video: !!(x.ctx && x.ctx.video instanceof HTMLVideoElement), seek: typeof (x.ctx && x.ctx.seek),
    analysis: !!(x.ctx && x.ctx.analysis && x.ctx.analysis.faults), slots: x.slots, rows: x.rows })));
  const by = Object.fromEntries(lane.map((x) => [x.fn, x]));
  assert.equal(by.voice.jobId, JOB); assert.equal(by.voice.video, true); assert.equal(by.voice.seek, "function");
  assert.equal(by.voice.analysis, true); assert.equal(by.voice.slots, 2);
  assert.equal(by.second.jobId, JOB); assert.equal(by.second.video, true); assert.equal(by.second.seek, "function");
  assert.equal(by.narration.entryId, "lateral-raise-0f13199f");
  assert.ok(by.narration.rows >= 2, "fault rows carry data-at-s for the narration");
  assert.equal(lane.filter((x) => x.fn === "export").length, 2, "the export button is mounted again in the repainted slot");
  // the seek the modules get moves the video and the 3D view
  await page.evaluate(() => window.__laneSeek = window.__lane.find((x) => x.fn === "voice").ctx.seek(9.1));
  await page.waitForFunction(() => Math.abs(Number(document.querySelector('[data-testid="coach-clock"]').dataset.t) - 9.1) < 0.15, null, { timeout: 5000 });
  ok("AC-R6 voice, second-opinion, export and narration mount with the documented context");

  // the voice slot sits inside the fault card, after the row and its chips; never inside the button
  const placement = await page.locator('[data-testid="voice-slot"]').evaluateAll((ns) => ns.map((n) => ({
    card: n.parentElement.matches("li.sr-fault-item"), afterRow: !!(n.previousElementSibling && n.previousElementSibling.matches("button.sr-fault")),
    inButton: !!n.closest("button"), inside: (() => { const c = n.parentElement.getBoundingClientRect(), s = n.getBoundingClientRect(); return s.top >= c.top && s.bottom <= c.bottom + 0.5; })(),
  })));
  assert.deepEqual(placement, [0, 1].map(() => ({ card: true, afterRow: true, inButton: false, inside: true })));
  // "Low confidence" passes WCAG AA, checked by axe on the fault list
  await page.evaluate(fs.readFileSync(req.resolve("axe-core/axe.min.js"), "utf8"));
  const contrast = await page.evaluate(() => axe.run(document.querySelector('[data-testid="fault-list"]'), { runOnly: ["color-contrast"] }));
  assert.deepEqual(contrast.violations.flatMap((v) => v.nodes.map((n) => n.target.join(" "))), []);
  assert.equal(await tid(page, "fault-1-low").evaluate((n) => getComputedStyle(n).color), await page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue("--palette-coral").trim()).then((hex) => {
    const v = parseInt(hex.slice(1), 16); return `rgb(${v >> 16}, ${(v >> 8) & 255}, ${v & 255})`;
  }));
  // a scroll to a card stops below the sticky header
  assert.equal(await page.locator(".sr-fault-item").first().evaluate((n) => getComputedStyle(n).scrollMarginTop),
    await page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue("--header-height").trim()));
  await page.locator('[data-testid="fault-list"]').evaluate((n) => n.closest("section").scrollIntoView({ block: "start" }));
  await page.waitForTimeout(300);
  await page.screenshot({ path: path.join(SHOTS, "additions-fault-list.png") });
  ok("AC-R6 the voice slot sits inside its fault card; Low confidence passes AA; scrolls stop below the header");

  // ---- R2 the skeleton over the video -------------------------------------------------------------------------
  const skel = tid(page, "skeleton-overlay");
  await skel.waitFor({ state: "attached" });
  // at 9.1 s (the knee fault, after the seek above) the knee is lit
  await page.waitForFunction(() => (document.querySelector('[data-testid="skeleton-overlay"]').dataset.hot || "").split(",").includes("left_knee"));
  assert.equal(await skel.getAttribute("data-bones"), String(BONES.length));
  const vbox = await tid(page, "result-video").boundingBox(), sbox = await skel.boundingBox();
  assert.ok(Math.abs(vbox.width - sbox.width) < 2 && Math.abs(vbox.height - sbox.height) < 2, `canvas ${JSON.stringify(sbox)} over video ${JSON.stringify(vbox)}`);
  await tid(page, "coach-stage").screenshot({ path: path.join(SHOTS, "additions-skeleton-fault.png") });
  // negative: away from every mistake nothing is lit
  await page.evaluate(() => window.__r.seek(1.6));
  await page.waitForFunction(() => Math.abs(Number(document.querySelector('[data-testid="skeleton-overlay"]').dataset.t) - 1.6) < 0.06);
  assert.equal(await skel.getAttribute("data-hot"), "", "no joint lit 1.6 s, where no mistake is near");
  await tid(page, "skeleton-toggle").click();
  assert.equal(await skel.isHidden(), true);
  await tid(page, "skeleton-toggle").click();
  ok("AC-R2 the skeleton follows the video clock and lights the fault joint near its time only");

  // ---- R5 a tapped row keeps the video and the 3D view in sight -----------------------------------------------
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.waitForTimeout(200);
  const fault = tid(page, "fault-1");
  await fault.scrollIntoViewIfNeeded();
  assert.equal(await inView(page, "compare"), false, "negative: the 3D view is off screen before the tap");
  await fault.click();
  await page.waitForTimeout(1200);
  assert.equal(await inView(page, "result-video"), true, "video in sight after the tap");
  assert.equal(await inView(page, "compare"), true, "3D view in sight after the tap");
  const clock = Number(await tid(page, "coach-clock").getAttribute("data-t"));
  const cmpClock = Number(await tid(page, "clock").getAttribute("data-t"));
  assert.ok(Math.abs(clock - 9.1) < 0.2 && Math.abs(cmpClock - 9.1) < 0.2, `seeked to ${clock} and ${cmpClock}`);
  await page.screenshot({ path: path.join(SHOTS, "additions-after-tap.png") });
  ok("AC-R5 tapping a coaching line brings the video and the 3D view into sight, both at the line's time");

  // ---- R3 the 3D bodies in the worst moment's card ------------------------------------------------------------
  await tid(page, "summary-mesh").locator("canvas").waitFor({ timeout: 15000 });
  assert.equal(await page.locator(".rs-worst .rs-figs").count(), 0, "the stick figures gave way to the 3D bodies");
  assert.equal(await tid(page, "summary-mesh").isVisible(), true);
  await tid(page, "summary-worst").scrollIntoViewIfNeeded();
  await page.waitForTimeout(400);
  await tid(page, "summary-worst").screenshot({ path: path.join(SHOTS, "additions-mesh.png") });
  ok("AC-R3 both meshes mount in the Reference vs You card on the stage clock");
  await page.context().close();

  for (const mesh of ["none", "broken"]) {
    const p = await open("ok", { mesh });
    await p.waitForTimeout(1500);
    assert.equal(await p.locator(".rs-worst .rs-figs").count(), 1, `${mesh}: stick figures stay`);
    assert.equal(await tid(p, "summary-mesh").count(), 0, `${mesh}: no empty 3D box`);
    await p.context().close();
  }
  ok("AC-R3 no mesh, or a mesh file that fails, keeps the stick figures");

  // ---- reduced motion, the example result, missing modules -----------------------------------------------------
  const calm = await open("ok", { reduced: true });
  assert.equal(await tid(calm, "summary-score").getAttribute("data-reveal"), "skipped");
  assert.equal(await tid(calm, "summary-score").locator(".rs-ring-value").textContent(), "77");
  await calm.context().close();
  ok("AC-R4 prefers-reduced-motion shows the final score at once");

  const fx = await open("fixture", { stubs: false });
  assert.equal(await tid(fx, "models-used").count(), 0, "the example result has no job files: no panel");
  assert.equal(await tid(fx, "skeleton-overlay").count(), 0);
  assert.equal(await tid(fx, "summary-mesh").count(), 0, "no mesh box on the example result");
  assert.equal(await tid(fx, "second-opinion-slot").textContent(), "", "a missing module leaves its slot empty");
  assert.equal(await tid(fx, "export-slot").textContent(), "", "the example result has no job files: no export button (nothing to render)");
  assert.equal(await tid(fx, "export-start").count(), 0);
  await fx.context().close();
  const noModels = await open("ok", { models: null });
  await noModels.waitForTimeout(500);
  assert.equal(await tid(noModels, "models-used").count(), 0, "models.json 404: no panel, no error");
  await noModels.context().close();
  ok("the example result, a 404 models.json and missing modules leave the screen as it was");

  assert.deepEqual(errors, [], errors.join("\n"));
  ok("no console errors");
} finally {
  await browser.close();
  server.close();
}
console.log(`${passed} passed`);
