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
import { isLaneModule404, isPickerRequest404, isOptionalResult404 } from "./lane_modules.mjs";

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
  { id: "narration", model: "Muse Voice Transcribe", maker: "Meta", clip: "trainer", status: "not_run", seconds: null, facts: { reason: "no_narration" } },
  { id: "spark-opinion", model: "Muse Spark", maker: "Meta", clip: "you", status: "live", seconds: null, facts: { via: "meta_api", verdicts: 2, observations: 1 } },
  { id: "spark-history", model: "Muse Spark", maker: "Meta", clip: "account", status: "live", seconds: null, facts: { via: "meta_api", takes: 3, cached_tokens: 4000 } },
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
async function open(kase, { mesh = "both", stubs = true, models = MODELS, reduced = false, analysis = "", pid = "" } = {}) {
  const ctx = await browser.newContext({ viewport: { width: 412, height: 915 }, hasTouch: true, reducedMotion: reduced ? "reduce" : "no-preference" });
  // the stage's "Rep breakdown" (score over time, form per rep) opens for these checks, as a viewer who left it open
  await ctx.addInitScript(() => { try { localStorage.setItem("simon.stage.breakdown", "open"); localStorage.setItem("simon.result.more", "open"); } catch { /* blocked */ } });
  const page = await ctx.newPage();
  // the 404s a case asks for: missing modules (no stubs), broken mesh files, a missing models.json
  const expected = (url) => /\/api\/source\/take\//.test(url) /* the credit in the open More has no server in the harness */ || (!stubs && isLaneModule404(url)) || isPickerRequest404(url) || (/\/(take-ar\.json|muse-fix)$/.test(url) && isOptionalResult404(url)) || (mesh === "broken" && /\/mesh\/(you|trainer)\/mesh3d/.test(url))
    || (!models && url.endsWith("/models.json"));
  page.on("console", (m) => { if (m.type() === "error" && !expected(m.location().url)) errors.push(`${kase}: ${m.text()} ${m.location().url}`); });
  page.on("pageerror", (e) => errors.push(`${kase}: ${e.message}`));
  const json = (route, body, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
  // the video goes to the static server, which answers Range requests: a fulfilled body cannot be seeked
  await page.route(`**/api/results/${JOB}/video.mp4`, (r) => r.continue({ url: `http://127.0.0.1:${port}/tests/part7/fixtures/coach.webm` }));
  await page.route("**/api/auth/me", (r) => json(r, { available: false }, 200)); // sign-in off, as a server without mail answers (identity.md)
  if (pid) await page.route(`**/api/results/${JOB}/${pid}/video.mp4`, (r) => r.continue({ url: `http://127.0.0.1:${port}/tests/part7/fixtures/coach.webm` }));
  if (pid) await page.route(`**/api/results/${JOB}/${pid}/models.json`, (r) => { (page.asked ||= []).push(new URL(r.request().url()).pathname); return json(r, models || { error: "gone" }, models ? 200 : 404); });
  await page.route(`**/api/results/${JOB}/models.json`, (r) => json(r, models || { error: "gone" }, models ? 200 : 404));
  await page.route(`**/api/results/${JOB}/skeleton2d.json`, (r) => json(r, SKELETON));
  await page.route(`**/api/results/${JOB}/mesh.json`, (r) => json(r, mesh === "none" ? { trainer: null, you: null }
    : { trainer: `api/results/${JOB}/mesh/trainer/mesh3d.json`, you: `api/results/${JOB}/mesh/you/mesh3d.json` }));
  await page.route(`**/api/results/${JOB}/mesh/*/*`, (r) => {
    const [who, file] = new URL(r.request().url()).pathname.split("/").slice(-2);
    if (mesh === "broken") return r.fulfill({ status: 404, body: "" });
    const demo = path.join(web, "mesh-demo", who === "you" ? "follower" : "trainer", file);
    if (!fs.existsSync(demo)) return r.fulfill({ status: 404, body: "" }); // the demo has no rest.json, which the Person skin asks for
    return r.fulfill({ path: demo });
  });
  await page.route("**/catalog/api/entries/*", (r) => json(r, { id: "lateral-raise-0f13199f", name: "Lateral raise" }));
  if (stubs) for (const [file, body] of Object.entries(STUB)) await page.route(`**/web/${file}`, (r) => r.fulfill({ contentType: "text/javascript", body }));
  await page.goto(`http://127.0.0.1:${port}/tests/part7/harness/result-additions.html?case=${kase}${analysis ? `&analysis=${analysis}` : ""}${pid ? `&pid=${pid}` : ""}`);
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
  await tid(page, "stage-made").click();   // the card opens from the stage's "i" pill (client stage, ui-for-r20)
  await tid(page, "models-used").waitFor();
  assert.equal(await page.locator('[data-testid="models-used"] .hm-step').count(), 8);
  assert.equal(await tid(page, "model-spark-opinion-status").textContent(), "Ran live", "TICKET-262 the second opinion row");
  assert.equal(await tid(page, "model-narration-status").textContent(), "Not used", "negative: no narration file, no live narration row");
  assert.match(await tid(page, "model-spark-history-detail").textContent(), /4000 tokens reused/);
  assert.equal(await page.locator('[data-testid="models-used"] .hm-group[data-clip="account"] .hm-step').count(), 1);
  assert.equal(await tid(page, "model-sam3d-you").getAttribute("data-status"), "live");
  assert.equal(await tid(page, "model-sam3d-you-status").textContent(), "Ran live");
  assert.equal(await tid(page, "model-spark-sections-status").textContent(), "Saved run reused");
  assert.equal(await tid(page, "model-spark-phrasing-status").textContent(), "Fallback");
  assert.match(await tid(page, "model-spark-phrasing-detail").textContent(), /^Used template wording: the Meta budget was used up$/);
  assert.equal(await tid(page, "model-sam31-you-status").textContent(), "Not used");
  assert.equal(await tid(page, "models-made-with").textContent(), "Made with Meta's SAM 3.1, Muse Spark and SAM 3D Body.");
  assert.equal(await tid(page, "models-total").textContent(), "Your take, from upload to result: 2 min 43 s.");
  // it sits in the stage's "How this was made" panel, at the top of the result
  assert.equal(await tid(page, "models-used").evaluate((n) => !!n.closest('[data-testid="stage-made-panel"]') && !!n.closest('[data-testid="stage"]')), true);
  await tid(page, "models-used").screenshot({ path: path.join(SHOTS, "additions-models-used.png") });
  ok("AC-R1 how this was made: every row from models.json, fallback labelled, made-with names only models that ran");

  // ---- R4 the reveal ------------------------------------------------------------------------------------------
  // the repaint for the routine's name ("Lateral raise, rep ...") lands mid-count and carries it on to the end
  await page.waitForFunction(() => /Lateral raise/.test(document.querySelector(".rs-worst h3")?.textContent || ""));
  await page.waitForFunction(() => document.querySelector('[data-testid="summary-score"]').dataset.reveal === "done");
  assert.equal(await tid(page, "summary-score").locator(".rs-meter-value").textContent(), "77");
  assert.equal(await tid(page, "summary-grade").textContent(), "C");

  // ---- the lean result (team, 2026-11-02): no "how your score adds up" line and no stats tiles -----------------
  assert.equal(await page.getByTestId("score-sum").count(), 0, "negative: no score-sum line");
  assert.equal(await page.locator(".rs-stats").count(), 0, "negative: no stats tiles");
  ok("lean result: the score bar alone says the score (no sum line, no stats tiles)");

  // ---- result-intent.md AC-I4 the reveal's last beat: the trainer and you slide together, once seen --------------
  const cmp = tid(page, "compare");
  const gap = async () => {
    const [a, b] = await Promise.all(["trainer", "you"].map((w) => cmp.getAttribute(`data-pelvis-${w}`).then((s) => s.split(",").map(Number))));
    return Math.hypot(a[0] - b[0], a[1] - b[1]);
  };
  assert.equal(await cmp.getAttribute("data-reveal"), "waiting", "negative: off screen, the 3D view waits");
  assert.equal(await cmp.getAttribute("data-mode"), "side");
  await tid(page, "stage-view-3d").click();   // the 3D view is one of the stage's views (client stage, ui-for-r20)
  await cmp.evaluate((n) => n.scrollIntoView({ block: "center" }));
  await page.waitForTimeout(150);
  const gapStart = await gap();
  await page.waitForFunction(() => document.querySelector('[data-testid="compare"]').dataset.reveal === "done", null, { timeout: 5000 });
  await page.waitForTimeout(150);
  assert.equal(await cmp.getAttribute("data-mode"), "overlay");
  assert.equal(await tid(page, "mode-toggle").getAttribute("aria-pressed"), "true");
  const gapEnd = await gap();
  assert.ok(gapStart > 40 && gapEnd < 5, `the pelvises close in: ${gapStart.toFixed(1)} px to ${gapEnd.toFixed(1)} px`);
  ok(`AC-I4 once the ring has counted up and the 3D view is in sight, the figures slide together (${gapStart.toFixed(0)} px to ${gapEnd.toFixed(0)} px) and Overlay is on`);

  // ---- result-intent.md AC-I5 every heading on the result screen meets WCAG AA (axe color-contrast) ------------------
  await page.evaluate(fs.readFileSync(req.resolve("axe-core/axe.min.js"), "utf8"));
  const heads = await page.evaluate(async () => {
    const sel = ".simon-result h1, .simon-result h2, .simon-result h3, .simon-result h4, .simon-result [role=heading], .simon-result .rs-eyebrow, .simon-result .rs-note-title";
    const nodes = [...document.querySelectorAll(sel)].filter((n) => n.getClientRects().length && n.textContent.trim());
    const res = await axe.run(document.querySelectorAll(sel), { runOnly: ["color-contrast"] });
    const why = (n) => [...n.any, ...n.all].map((c) => (c.data && c.data.messageKey) || c.message).join("; ");
    const names = (list) => list.flatMap((v) => v.nodes.map((n) => `${n.target.join(" ")} (${why(n)})`));
    // axe leaves text on a gradient undecided; for those, the text colour is held against every stop of the gradient,
    // each laid over the card's own fill, and the lowest ratio must still be AA (4.5)
    const rgb = (s) => { const m = s.match(/[\d.]+/g).map(Number); return { r: m[0], g: m[1], b: m[2], a: m.length > 3 ? m[3] : 1 }; };
    const over = (top, base) => ({ r: top.r * top.a + base.r * (1 - top.a), g: top.g * top.a + base.g * (1 - top.a), b: top.b * top.a + base.b * (1 - top.a), a: 1 });
    const lum = (c) => [c.r, c.g, c.b].map((v) => { v /= 255; return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; })
      .reduce((s, v, i) => s + v * [0.2126, 0.7152, 0.0722][i], 0);
    const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };
    const gradientWorst = (sel) => {
      const node = document.querySelector(sel);
      let card = node;
      while (card && getComputedStyle(card).backgroundImage === "none") card = card.parentElement;
      if (!card) return null;
      const fill = rgb(getComputedStyle(card).backgroundColor);
      const stops = (getComputedStyle(card).backgroundImage.match(/rgba?\([^)]*\)/g) || []).map((s) => over(rgb(s), fill));
      const text = rgb(getComputedStyle(node).color);
      return Math.min(...[fill, ...stops].map((bg) => ratio(text, bg)));
    };
    const undecided = res.incomplete.flatMap((v) => v.nodes.map((n) => ({ target: n.target.join(" "), why: why(n),
      worst: why(n) === "bgGradient" ? gradientWorst(n.target.join(" ")) : null })));
    return { shown: nodes.map((n) => n.textContent.trim().slice(0, 30)), violations: names(res.violations), undecided, passes: names(res.passes) };
  });
  assert.deepEqual(heads.violations, [], `headings below AA: ${heads.violations.join(" | ")}`);
  for (const u of heads.undecided) {
    assert.equal(u.why, "bgGradient", `axe left ${u.target} undecided for a reason other than a gradient: ${u.why}`);
    assert.ok(u.worst >= 4.5, `${u.target} on its gradient: ${u.worst && u.worst.toFixed(2)} at the worst stop`);
  }
  assert.ok(heads.shown.length >= 8, `the result's headings are checked: ${heads.shown.join(" | ")}`);
  assert.equal(heads.passes.length + heads.undecided.length, heads.shown.length, `every shown heading checked: ${heads.passes.length} + ${heads.undecided.length} of ${heads.shown.length}`);
  ok(`AC-I5 color contrast holds on all ${heads.shown.length} headings of the result screen (axe; ${heads.undecided.length} on a gradient checked at its worst stop: `
    + `${heads.undecided.map((u) => u.worst.toFixed(2)).join(", ")})`);

  // the same result mounted again does not play it again
  await page.evaluate(async () => { window.__r.destroy(); window.__lane = []; window.__r = await window.__mount(); });
  await page.waitForFunction(() => /Lateral raise/.test(document.querySelector(".rs-worst h3")?.textContent || ""));
  await page.waitForFunction(() => document.querySelector('[data-testid="summary-score"]')?.dataset.reveal === "done");   // the bar fills every time (client, 2026-11-02)
  assert.equal(await tid(page, "summary-score").locator(".rs-meter-value").textContent(), "77");
  assert.equal(await tid(page, "compare").getAttribute("data-reveal"), "skipped", "AC-I4 no second slide");
  assert.equal(await tid(page, "compare").getAttribute("data-mode"), "side");
  await tid(page, "stage-made").click();
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

  // the lean result draws no fault list ("What to work on" holds the cues): the voice slots wait, hidden, in one box,
  // so the stage's voice switch still speaks each line at its moment; never inside a button
  const placement = await page.locator('[data-testid="voice-slot"]').evaluateAll((ns) => ns.map((n) => ({
    box: n.parentElement.matches('[data-testid="voice-lines"]'), hidden: !!n.closest("[hidden]"), inButton: !!n.closest("button") })));
  assert.deepEqual(placement, [0, 1].map(() => ({ box: true, hidden: true, inButton: false })));
  assert.equal(await page.getByTestId("fault-list").count(), 0, "negative: no fault list");
  ok("AC-R6 the voice slots wait hidden for the stage's voice switch; no fault list");


  // ---- R2 the skeleton over the video -------------------------------------------------------------------------
  await tid(page, "stage-view-annotated").click();   // the skeleton is the stage's Annotated view (the 3D pick above is saved)
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
  const fault = tid(page, "insight-2");   // a "What to work on" row (5.8 s), under the stage
  await fault.scrollIntoViewIfNeeded();
  // the client's stage (ui-for-r20) shows one view at a time: the tap brings the stage's top into sight on the view that moves
  const stageTop = () => tid(page, "stage").evaluate((n) => { const r = n.getBoundingClientRect(); return r.top >= -1 && r.top < innerHeight / 2; });
  assert.equal(await stageTop(), false, "negative: the stage is off screen before the tap");
  await fault.click();
  await page.waitForTimeout(1200);
  assert.equal(await stageTop(), true, "the stage in sight after the tap");
  assert.ok(["annotated", "3d"].includes(await tid(page, "stage").getAttribute("data-view")), "on a view that moves (video with the skeleton, or 3D)");
  const clock = Number(await tid(page, "coach-clock").getAttribute("data-t"));
  const cmpClock = Number(await tid(page, "clock").getAttribute("data-t"));
  assert.ok(Math.abs(clock - 5.8) < 0.2 && Math.abs(cmpClock - 5.8) < 0.2, `seeked to ${clock} and ${cmpClock}`);
  await page.screenshot({ path: path.join(SHOTS, "additions-after-tap.png") });
  ok("AC-R5 tapping a coaching line brings the stage into sight on a view that moves; the video and the 3D view are both at the line's time");

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
  assert.equal(await tid(calm, "summary-score").locator(".rs-meter-value").textContent(), "77");
  assert.equal(await tid(calm, "compare").getAttribute("data-reveal"), "skipped", "AC-I4 no slide under reduced motion");
  await tid(calm, "compare").evaluate((n) => n.scrollIntoView({ block: "center" }));
  await calm.waitForTimeout(1500);
  assert.equal(await tid(calm, "compare").getAttribute("data-mode"), "side", "negative: the figures stay side by side");
  await calm.context().close();
  ok("AC-R4 and AC-I4 prefers-reduced-motion shows the final score at once and does not slide the figures");

  // the score bar fills every time the result opens (team, 2026-11-02); the 3D slide stays once per result per session
  const again = await open("ok");
  await again.waitForFunction(() => document.querySelector('[data-testid="summary-score"]')?.dataset.reveal === "done");
  await again.reload();
  await again.waitForFunction(() => window.__ready === true);
  await again.waitForFunction(() => document.querySelector('[data-testid="summary-score"]')?.dataset.reveal === "done");   // it fills again
  assert.equal(await tid(again, "summary-score").locator(".rs-meter-value").textContent(), "77");
  assert.equal(await tid(again, "compare").getAttribute("data-reveal"), "skipped", "no slide after a reload");
  await again.context().close();
  ok("AC-I4 the reveal plays once per result per session: a reload shows the end state at once");

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

  // ---- group-results.md R2: one person of a group result has its own "How this was made" card ---------------------
  const PERSON = { job: JOB, person: "p2", job_seconds: 180, models: [
    { id: "sam31-you", model: "SAM 3.1", maker: "Meta", clip: "you", status: "live", seconds: 30, facts: { via: "meta_api" } },
    { id: "sam3d-you", model: "SAM 3D Body", maker: "Meta", clip: "you", status: "live", seconds: 70, facts: { via: "local_gpu" } },
    { id: "spark-phrasing", model: "Muse Spark", maker: "Meta", clip: "you", status: "live", seconds: null, facts: { via: "meta_api", lines: 3 } },
  ] };
  const grp = await open("ok", { pid: "p2", models: PERSON });
  await tid(grp, "stage-made").click();
  await tid(grp, "models-used").waitFor();
  assert.deepEqual(grp.asked, [`/tests/part7/harness/api/results/${JOB}/p2/models.json`], "the card is asked for this person only");
  assert.equal(await grp.locator('[data-testid="models-used"] .hm-step').count(), 3);
  assert.equal(await tid(grp, "model-sam3d-you-status").textContent(), "Ran live");
  assert.equal(await grp.locator('[data-testid="models-used"] .hm-group[data-clip="trainer"]').count(), 0, "negative: no trainer rows on a person's card");
  await grp.context().close();
  const grpGone = await open("ok", { pid: "p2", models: null });
  await grpGone.waitForTimeout(500);
  assert.equal(await tid(grpGone, "models-used").count(), 0, "a 404 for the person shows no card");
  await grpGone.context().close();
  ok("group-results R2: a group person's result shows the card from its own models.json; a 404 shows none");

  // ---- TICKET-120 the fault cap (synthetic simon.score.v3 fixtures): the sum line that explained it is not drawn on
  // the lean result; the score bar shows the score as given
  const two = await open("ok", { analysis: "synthetic-v3-two-fault" });
  assert.equal(await two.getByTestId("score-sum").count(), 0, "negative: no sum line");
  await two.context().close();
  ok("TICKET-120 the two-fault v3 result draws no sum line on the lean result");

  assert.deepEqual(errors, [], errors.join("\n"));
  ok("no console errors");
} finally {
  await browser.close();
  server.close();
}
console.log(`${passed} passed`);
