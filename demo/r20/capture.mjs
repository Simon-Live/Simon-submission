// demo/r20/capture.mjs: record the release 20 cut's UI segments on live staging, read only except the one follow take.
// Run inside `firm/staging/staging.sh exec simon-part-7` (gateway login in the environment, never printed) and inside
// `scripts/with-browser-slot.sh` (one driver). Usage:
//   DEMO_ONLY=watch,result node demo/r20/capture.mjs <out-dir>
// Env: DEMO_HERO (job id; default: the featured take from api/judge/hero), DEMO_SESSION (a Playwright storage state of
// the demo account that owns the demo models; optional), DEMO_CAMERA_Y4M (the follower clip as y4m for the fake
// camera), DEMO_IDLE (script that exits 0 when staging has no take queued or running), DEMO_TAKE=1 (send the follow
// take: one real GPU upload; without it the follow segment stops before the take is sent).
// Writes <out-dir>/ui-<segment>.mp4, <out-dir>/marks.json and <out-dir>/facts.json (ids and texts read on screen).
import fs from "node:fs";
import path from "node:path";
import os from "node:os";
import { createRequire } from "node:module";
import { spawnSync } from "node:child_process";
import { record } from "./rec.mjs";

const OUT = path.resolve(process.argv[2] || path.join(os.tmpdir(), "simon-demo-r20", "capture"));
const BASE = (process.env.STAGING_BASE_URL || "").replace(/\/?$/, "/");
const ONLY = (process.env.DEMO_ONLY || "watch,follow,result,opinion,models,picker,anybody,privacy").split(",");
const req = createRequire(process.env.PLAYWRIGHT_ROOT || path.join(os.homedir(), "simon-part-7", "package.json"));
const { chromium } = req("playwright");
fs.mkdirSync(OUT, { recursive: true });
const SECRETS = [process.env.STAGING_USER, process.env.STAGING_PASSWORD].filter((s) => s && s.length > 3);
const mask = (s) => { let t = String(s); for (const x of SECRETS) t = t.split(x).join("[masked]"); return BASE ? t.split(BASE).join("<staging>/") : t; };
const log = (...a) => console.log(mask(a.map((x) => (typeof x === "string" ? x : JSON.stringify(x))).join(" ")));
const jread = (f, d) => (fs.existsSync(f) ? JSON.parse(fs.readFileSync(f, "utf8")) : d);
const marks = jread(path.join(OUT, "marks.json"), {});
const facts = jread(path.join(OUT, "facts.json"), {});
const save = () => {
  fs.writeFileSync(path.join(OUT, "marks.json"), JSON.stringify(marks, null, 1));
  fs.writeFileSync(path.join(OUT, "facts.json"), mask(JSON.stringify(facts, null, 1)));
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const sel = (id) => `[data-testid="${id}"]`;

const PHONE = { viewport: { width: 412, height: 915 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true };
const DESK = { viewport: { width: 1600, height: 900 }, deviceScaleFactor: 1.2 };
const ARGS = ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"];
// The build line carries a commit id and a time; the staging gateway's feedback tab overlaps the right edge. Both are
// chrome, not app content.
const HIDE = '[data-testid="build-line"],[data-testid="build-details"],[data-firm-feedback]{display:none!important}';

// Headless screencast frames come in CSS pixels unless the device scale is forced on the browser as well.
async function browserFor(extraArgs = [], kind = "phone") {
  const dsf = (kind === "desk" ? DESK : PHONE).deviceScaleFactor;
  return chromium.launch({ headless: true, args: [...ARGS, `--force-device-scale-factor=${dsf}`, ...extraArgs] });
}

async function ctxFor(browser, kind, { session, camera } = {}) {
  const ctx = await browser.newContext({
    ...(kind === "desk" ? DESK : PHONE),
    httpCredentials: { username: process.env.STAGING_USER, password: process.env.STAGING_PASSWORD },
    ...(session && fs.existsSync(session) ? { storageState: session } : {}),
    ...(camera ? { permissions: ["camera", "microphone"] } : {}),
    reducedMotion: "no-preference",
  });
  ctx.setDefaultTimeout(45_000);
  await ctx.addInitScript((css) => {
    document.addEventListener("DOMContentLoaded", () => { const s = document.createElement("style"); s.textContent = css; document.head.append(s); });
  }, HIDE);
  return ctx;
}

async function segment(name, kind, fn, opts = {}) {
  if (!ONLY.includes(name)) return;
  log("segment", name);
  const browser = await browserFor(opts.args || [], kind);
  const ctx = await ctxFor(browser, kind, opts);
  const page = await ctx.newPage();
  page.on("pageerror", (e) => log("pageerror", name, e.message));
  const vp = kind === "desk" ? DESK : PHONE;
  const W = Math.round(vp.viewport.width * vp.deviceScaleFactor), H = Math.round(vp.viewport.height * vp.deviceScaleFactor);
  let rec = null;
  const m = {
    start: async () => { rec = await record(page, OUT, name, { width: W, height: H }); },
    at: (label) => rec && rec.mark(label),
  };
  try {
    await fn(page, m);
  } finally {
    if (rec) {
      const r = await rec.stop();
      marks[name] = r.marks;
      save();
      log("wrote", path.basename(r.file), JSON.stringify(r.marks));
    }
    await browser.close();
  }
}

async function glide(page, px, ms = 1400) {
  const steps = Math.max(6, Math.round(ms / 40));
  for (let i = 0; i < steps; i++) { await page.evaluate((d) => window.scrollBy(0, d), px / steps); await sleep(ms / steps); }
}

async function scrollTo(page, target, ms = 1500, offset = 80) {
  const y = await page.evaluate(([t, off]) => {
    const el = t.startsWith("[") || t.startsWith(".") ? document.querySelector(t) : document.querySelector(`[data-testid="${t}"]`);
    return el ? el.getBoundingClientRect().top + window.scrollY - off : null;
  }, [target, offset]);
  if (y == null) { log("scroll target missing", target); return false; }
  const cur = await page.evaluate(() => window.scrollY);
  await glide(page, y - cur, ms);
  return true;
}

async function drag(page, locator, dx, dy = 0, ms = 2200) {
  const box = await locator.boundingBox();
  if (!box) return false;
  const cx = box.x + box.width / 2, cy = box.y + box.height / 2;
  await page.mouse.move(cx, cy); await page.mouse.down();
  const steps = 50;
  for (let i = 1; i <= steps; i++) { await page.mouse.move(cx + (dx * i) / steps, cy + (dy * i) / steps); await sleep(ms / steps); }
  await page.mouse.up();
  return true;
}

const api = (page, p) => page.evaluate(async (u) => { const r = await fetch(u); return { status: r.status, body: await r.json().catch(() => null) }; }, p);

// ---- facts read once: build sha, the featured take, its entry
async function readFacts() {
  const browser = await browserFor();
  const ctx = await ctxFor(browser, "phone");
  const page = await ctx.newPage();
  await page.goto(BASE, { waitUntil: "domcontentloaded" });
  facts.version = (await api(page, "api/version")).body;
  facts.hero_api = (await api(page, "api/judge/hero")).body;
  facts.hero = process.env.DEMO_HERO || facts.hero_api?.job_id;
  const job = (await api(page, `api/jobs/${facts.hero}`)).body;
  facts.hero_job = { id: job?.id, entry_id: job?.entry_id, status: job?.status, mode: job?.mode, result: job?.result && { score: job.result.score, grade: job.result.grade, faults: job.result.faults } };
  facts.entry = job?.entry_id;
  facts.models_used = (await api(page, `api/results/${facts.hero}/models.json`)).body;
  save();
  log("facts", JSON.stringify({ sha: facts.version?.sha, hero: facts.hero, entry: facts.entry, result: facts.hero_job.result }));
  await browser.close();
}

await readFacts();
const HERO = facts.hero, ENTRY = facts.entry;
const SESSION = process.env.DEMO_SESSION || "";

// ---- watch: the teacher's recording becomes a 3D reference, turned by hand
await segment("watch", "phone", async (page, m) => {
  await page.goto(`${BASE}#/watch/${ENTRY}`, { waitUntil: "domcontentloaded" });
  await page.locator(sel("compare-canvas")).first().waitFor({ state: "visible" });
  await sleep(3500);
  await m.start(); await sleep(1500); m.at("top");
  await scrollTo(page, "viewer", 1500, 70); m.at("viewer");
  const play = page.locator(sel("play")).first();
  if (await play.isVisible().catch(() => false)) { await play.click(); m.at("play"); }
  await sleep(1500);
  // the trainer figure in a CC0 body (Quaternius Mannequin, female) instead of the bare skeleton
  const pick = page.locator(sel("model-select-0")).first();
  if (await pick.isVisible().catch(() => false)) {
    const opts = await pick.locator("option").allInnerTexts();
    const o = opts.find((t) => t.startsWith("Mannequin (female)"));
    if (o) { await pick.selectOption({ label: o }); m.at("body"); await sleep(3000); }
  }
  await drag(page, page.locator(sel("compare-canvas")).first(), 160, 0, 2600); m.at("rot1");
  await sleep(800);
  for (const v of ["view-side", "view-top", "view-front"]) {
    const b = page.locator(sel(v)).first();
    if (await b.isVisible().catch(() => false)) { await b.click(); m.at(v); await sleep(1600); }
  }
  await drag(page, page.locator(sel("compare-canvas")).first(), -140, 0, 2400); m.at("rot2");
  await sleep(1200);
});

// ---- follow: side by side with the trainer, live check on, the camera fed the follower clip; optionally sent
await segment("follow", "phone", async (page, m) => {
  await page.goto(`${BASE}#/follow/${ENTRY}`, { waitUntil: "domcontentloaded" });
  await page.locator(sel("consent-line")).first().waitFor({ state: "visible" });
  await sleep(2500);
  facts.consent_line = await page.locator(sel("consent-line")).first().innerText().catch(() => null);
  await m.start(); await sleep(1200); m.at("top");
  await scrollTo(page, "consent-line", 1200, 160); m.at("consent"); await sleep(2200);
  await scrollTo(page, "reference", 1200, 70);
  const camOpen = page.locator(sel("cam-open")).first();
  if (await camOpen.isVisible().catch(() => false)) await camOpen.click();
  m.at("cam");
  await sleep(2500);
  const live = page.locator(sel("live-toggle")).first();
  if (await live.isVisible().catch(() => false)) { await live.click(); m.at("live"); }
  await page.locator(sel("live-status")).first().waitFor({ state: "visible", timeout: 30_000 }).catch(() => log("live-status not shown"));
  await sleep(4000); m.at("live_on");
  facts.live_status = await page.locator(sel("live-status")).first().innerText().catch(() => null);
  await scrollTo(page, "reference", 800, 70);
  await page.locator(sel("cam-start")).first().click(); m.at("rec_click");
  await page.locator(sel("capture-recording")).first().waitFor({ state: "visible", timeout: 20_000 }).catch(() => log("no recording marker"));
  m.at("recording");
  facts.live_cue_seen = [];
  for (let i = 0; i < 12; i++) {
    await sleep(700);
    const c = await page.locator(sel("live-cue")).first().innerText().catch(() => "");
    if (c && !facts.live_cue_seen.includes(c)) facts.live_cue_seen.push(c);
  }
  await page.locator(sel("trim")).first().waitFor({ state: "visible", timeout: 30_000 }).catch(() => log("no trim screen"));
  m.at("trim"); await sleep(1500);
  if (process.env.DEMO_TAKE !== "1") { log("DEMO_TAKE not set: the take is not sent"); return; }
  const idle = spawnSync(process.env.DEMO_IDLE || "false");
  if (idle.status !== 0) { log("staging busy: the take is not sent"); facts.take_sent = false; return; }
  await page.locator(sel("trim-continue")).first().click(); m.at("upload");
  // the people step: SAM 3.1 finds who is in the take; pick the first person when asked, then continue
  const t1 = Date.now();
  while (!/#\/(job|result)\//.test(page.url()) && Date.now() - t1 < 600_000) {
    const person = page.locator('[data-testid^="person-"]:not([data-testid^="person-label"]):not([data-testid^="person-quality"]):not([data-testid^="person-trainer"])').first();
    if (await person.isVisible().catch(() => false) && !facts.person_picked) { await person.click().catch(() => null); facts.person_picked = true; m.at("person"); }
    const cont = page.locator(sel("people-continue")).first();
    if (await cont.isVisible().catch(() => false) && await cont.isEnabled().catch(() => false)) { await cont.click().catch(() => null); m.at("people_continue"); }
    const go = page.locator(sel("analyse")).first();
    if (await go.isVisible().catch(() => false) && await go.isEnabled().catch(() => false)) {
      m.at("notes"); await sleep(1500);
      await go.scrollIntoViewIfNeeded().catch(() => null); await sleep(800);
      await go.click().catch(() => null); m.at("analyse"); await sleep(2000);
    }
    await sleep(1000);
  }
  facts.take_job = page.url().match(/#\/(?:job|result)\/([0-9a-f]+)/)?.[1] || null;
  log("take job", facts.take_job);
  save();
  m.at("job");
  await page.waitForURL(/#\/result\//, { timeout: 900_000 });
  m.at("result"); await sleep(5000);
}, { camera: true, args: process.env.DEMO_CAMERA_Y4M ? ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream", `--use-file-for-fake-video-capture=${process.env.DEMO_CAMERA_Y4M}`] : [] });

// ---- result: score, the cue, the 3D overlay turned by hand
await segment("result", "phone", async (page, m) => {
  await page.goto(BASE, { waitUntil: "domcontentloaded" });
  await sleep(1500);
  await m.start();
  await page.goto(`${BASE}#/result/${HERO}`, { waitUntil: "domcontentloaded" }); m.at("load");
  await page.locator(sel("score")).first().waitFor({ state: "visible" }).catch(() => null);
  await sleep(4500); m.at("score");
  facts.result_top = await page.evaluate(() => document.body.innerText.slice(0, 1600));
  await scrollTo(page, "stage", 1200, 70); m.at("stage");
  const worst = page.getByRole("button", { name: /Replay worst moment/ }).first();
  if (await worst.isVisible().catch(() => false)) { await worst.click(); m.at("worst"); await sleep(5000); }
  facts.stage_caption = await page.locator(sel("stage-caption")).first().innerText().catch(() => null);
  const tab3d = page.locator(sel("stage-view-3d")).first();
  if (await tab3d.isVisible().catch(() => false)) { await tab3d.click(); m.at("tab3d"); await sleep(3500); }
  const canvas = page.locator(`${sel("stage-host-3d")} canvas`).first();
  await drag(page, canvas, 120, 0, 2600); m.at("rot1"); await sleep(2000);
  await drag(page, canvas, -200, 0, 3200); m.at("rot2"); await sleep(2000);
  await scrollTo(page, "fault-list", 1500, 120); m.at("cue"); await sleep(3000);
});

// ---- opinion: Muse Spark's badge and observations, then Fix it for me
await segment("opinion", "phone", async (page, m) => {
  await page.goto(`${BASE}#/result/${HERO}`, { waitUntil: "domcontentloaded" });
  await page.locator(sel("verdict-badge")).first().waitFor({ state: "attached" }).catch(() => log("no referee verdict"));
  await sleep(4000);
  facts.opinion = await page.evaluate(() => [...document.querySelectorAll('[data-testid="verdict-badge"], [data-testid^="second-opinion-"]')].map((e) => `${e.dataset.testid}: ${e.innerText}`).slice(0, 8));
  await scrollTo(page, "verdict-badge", 10, 330);
  await sleep(800);
  await m.start(); await sleep(2500); m.at("badge");
  await scrollTo(page, "fix-it-button", 1400, 330); m.at("fix"); await sleep(1500);
  await page.locator(sel("fix-it-button")).first().click(); m.at("fix_open");
  await sleep(2500);
  await scrollTo(page, "fix-it-button", 1000, 90);
  const playBtn = page.locator('[data-testid^="fix-it-play"]').first();
  if (await playBtn.isVisible().catch(() => false)) { await playBtn.click(); m.at("fix_play"); }
  await sleep(7000);
  const after = page.locator(sel("fix-it-after")).first();
  if (await after.isVisible().catch(() => false)) { await after.click(); m.at("fix_after"); await sleep(4000); }
  facts.fix_label = await page.locator(sel("fix-it-label")).first().innerText().catch(() => null);
  await scrollTo(page, "second-opinion-list", 1400, 200).catch(() => null); m.at("also"); await sleep(3000);
});

// ---- models: the "How this was made" card of the featured take
await segment("models", "phone", async (page, m) => {
  await page.goto(`${BASE}#/result/${HERO}`, { waitUntil: "domcontentloaded" });
  await page.locator(sel("models-used")).first().waitFor({ state: "attached", timeout: 60_000 }).catch(() => log("no models card"));
  await sleep(3000);
  facts.models_card = await page.locator(sel("models-used")).first().innerText().catch(() => null);
  await scrollTo(page, "stage", 10, 75); await sleep(800);
  await m.start(); await sleep(1200);
  await page.locator(sel("stage-made")).first().click(); m.at("open"); await sleep(1500);
  await scrollTo(page, "models-used", 1200, 90); m.at("card"); await sleep(3500);
  await scrollTo(page, "model-sam3d-you", 2200, 260); m.at("rows"); await sleep(4000);
  await glide(page, 360, 2000); m.at("rows2"); await sleep(2500);
});

// ---- picker: the demo account's model on Me (made from one picture), then worn by "you" on the 3D view
await segment("picker", "phone", async (page, m) => {
  const want = process.env.DEMO_MODEL_NAME || "Sintel (demo)";
  await page.goto(`${BASE}#/me`, { waitUntil: "domcontentloaded" });
  await page.locator(sel("my-model-select")).first().waitFor({ state: "visible", timeout: 60_000 });
  const mine = page.locator(sel("my-model-select")).first();
  const labels = await mine.locator("option").allInnerTexts();
  const lab = labels.find((t) => t.includes(want));
  if (lab) await mine.selectOption({ label: lab });
  await sleep(3000);
  facts.me_model = await page.locator(sel("my-model")).first().innerText().catch(() => null);
  await scrollTo(page, "my-model", 10, 75); await sleep(800);
  await m.start(); await sleep(1500); m.at("me");
  await scrollTo(page, "my-model-preview", 1600, 140); m.at("preview");
  const play = page.locator(sel("my-model-play")).first();
  if (await play.isVisible().catch(() => false)) { await play.click(); m.at("play"); }
  await sleep(2500);
  await drag(page, page.locator(sel("my-model-preview")).first(), 150, 0, 2600); m.at("turn"); await sleep(3000);
  await page.goto(`${BASE}#/result/${HERO}`, { waitUntil: "domcontentloaded" }); m.at("result");
  await page.locator(sel("stage-view-3d")).first().waitFor({ state: "visible" });
  await scrollTo(page, "stage", 10, 75); await sleep(1500);
  await page.locator(sel("stage-view-3d")).first().click(); await sleep(3000); m.at("tab3d");
  const you = page.locator(sel("model-select-1")).first();
  await you.waitFor({ state: "visible", timeout: 30_000 });
  const opts = await you.locator("option").allInnerTexts();
  facts.picker_options = opts;
  const o = opts.find((t) => t.includes(want));
  if (o) { await you.selectOption({ label: o }); m.at("picked"); }
  // Side mode: in Overlay the textured model and the trainer tangle
  const mode = page.locator(`${sel("stage-host-3d")} ${sel("mode-toggle")}`).first();
  if ((await mode.getAttribute("aria-pressed").catch(() => null)) === "true") { await mode.click(); m.at("side"); }
  facts.picker_mode = await mode.getAttribute("aria-pressed").catch(() => null);
  const play3d = page.locator(`${sel("stage-host-3d")} ${sel("play")}`).first();
  if ((await play3d.getAttribute("data-playing").catch(() => null)) !== "true") { await play3d.click().catch(() => null); m.at("play3d"); }
  await sleep(8000);
  await drag(page, page.locator(`${sel("stage-host-3d")} canvas`).first(), 160, 0, 2600); m.at("rot"); await sleep(4000);
}, { session: SESSION });

// ---- anybody: one take on four bodies at once, desktop frame
await segment("anybody", "desk", async (page, m) => {
  await page.goto(`${BASE}#/any-body/${HERO}`, { waitUntil: "domcontentloaded" });
  await page.locator(sel("any-body-fig-0")).waitFor({ state: "visible" });
  await sleep(8000);
  facts.anybody = await page.evaluate(() => [...document.querySelectorAll('[data-testid^="any-body-name-"]')].map((e) => e.innerText));
  facts.anybody_credit = await page.locator(sel("any-body-credit")).first().innerText().catch(() => null);
  await m.start(); await sleep(1200);
  await page.locator(sel("any-body-play")).click(); m.at("play");
  await sleep(10000); m.at("end_play");
}, { session: SESSION });

// ---- privacy: the model-only option on Follow, and Delete this take on a result (the dialog is cancelled)
await segment("privacy", "phone", async (page, m) => {
  await page.goto(`${BASE}#/follow/${ENTRY}`, { waitUntil: "domcontentloaded" });
  await page.locator(sel("model-only")).first().waitFor({ state: "attached" });
  await sleep(2500);
  await scrollTo(page, "model-only", 10, 520); await sleep(600);
  await m.start(); await sleep(1500); m.at("modelonly");
  await page.locator(sel("model-only-toggle")).first().click().catch(() => log("model-only toggle not clickable"));
  m.at("ticked"); await sleep(3500);
  facts.model_only = await page.locator(sel("model-only")).first().innerText().catch(() => null);
  await page.goto(`${BASE}#/result/${HERO}`, { waitUntil: "domcontentloaded" });
  await sleep(4000);
  await scrollTo(page, "delete-take", 10, 700); await sleep(400);
  await scrollTo(page, "delete-take", 1400, 520); m.at("delete"); await sleep(1200);
  await page.locator(sel("delete-take-btn")).first().click(); m.at("ask"); await sleep(3000);
  facts.delete_ask = await page.locator(sel("delete-ask")).first().innerText().catch(() => null);
  // nothing is deleted: the confirm button is never pressed
});

// ---- footer: a still of the version footer for the end card (no video)
if (ONLY.includes("footer")) {
  const browser = await browserFor([], "phone");
  const ctx = await ctxFor(browser, "phone");
  await ctx.addInitScript(() => document.addEventListener("DOMContentLoaded", () => {
    const s = document.createElement("style"); s.textContent = '[data-testid="footer-version"],[data-testid="footer-build"]{display:revert!important}'; document.head.append(s);
  }));
  const page = await ctx.newPage();
  await page.goto(`${BASE}#/result/${HERO}`, { waitUntil: "domcontentloaded" });
  const fv = page.locator(sel("footer-version")).first();
  await fv.waitFor({ state: "visible", timeout: 60_000 });
  await sleep(2500);
  const foot = fv.locator("xpath=ancestor::footer[1]");
  const target = (await foot.count()) ? foot : fv;
  await target.scrollIntoViewIfNeeded();
  await sleep(800);
  await target.screenshot({ path: path.join(OUT, "footer.png") });
  facts.footer_text = await target.innerText().catch(() => null);
  log("footer", facts.footer_text);
  await browser.close();
}

save();
log("done", ONLY.join(","));
