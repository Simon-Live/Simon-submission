// Browser checks for the coaching moments at 412x915 (coaching-moments.md AC-M1 to AC-M12): the follower video kept in
// step with the 3D clock, moment taps, "Replay worst moment", the marks and the slots.
//   node tests/part7/coach.browser.mjs
// Playwright comes from `npm i` in this repo, or from PLAYWRIGHT_DIR (a node_modules folder).
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { serveRoot } from "./serve_static.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const req = createRequire(path.join(process.env.PLAYWRIGHT_DIR || path.resolve(here, "../../node_modules"), "x.js"));
const { chromium } = req("playwright");
const SHOTS = process.env.SHOTS_DIR || path.join(here, "screens");
fs.mkdirSync(SHOTS, { recursive: true });
const ins = JSON.parse(fs.readFileSync(path.join(here, "../../fixtures/input/analysis-insights.json")));

const { server, port } = await serveRoot();
const browser = await chromium.launch({ args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist", "--autoplay-policy=no-user-gesture-required"] });
const errors = [];
let passed = 0;
const ok = (name) => { passed++; console.log(`ok - ${name}`); };
// only the deliberately missing video (case novideo) and a module a case blocks on purpose may 404
const EXPECTED_404 = /missing\.webm/;

async function open(kase, { noWebgl = false, hangVideo = false, lateVideoMs = 0, block = null } = {}) {
  const ctx = await browser.newContext({ viewport: { width: 412, height: 915 }, hasTouch: true });
  const page = await ctx.newPage();
  page.on("console", (m) => { if (m.type() === "error" && !EXPECTED_404.test(m.location().url + m.text()) && !(block && m.location().url.endsWith(block))) errors.push(`${kase}: ${m.text()}`); });
  page.on("pageerror", (e) => errors.push(`${kase}: ${e.message}`));
  if (block) await page.route(`**/web/${block}`, (r) => r.fulfill({ status: 404, body: "" })); // a lazy slot module that is missing
  if (hangVideo) await page.route("**/coach.webm", () => {}); // the request never answers: no metadata, no error
  if (lateVideoMs) await page.route("**/coach.webm", async (r) => { await new Promise((ok) => setTimeout(ok, lateVideoMs)); await r.continue().catch(() => {}); });
  if (noWebgl) {
    await page.addInitScript(() => {
      const orig = HTMLCanvasElement.prototype.getContext;
      HTMLCanvasElement.prototype.getContext = function (type, ...rest) { return /webgl/.test(type) ? null : orig.call(this, type, ...rest); };
    });
  }
  await page.goto(`http://127.0.0.1:${port}/tests/part7/harness/coach.html?case=${kase}`);
  await page.waitForFunction(() => window.__ready === true);
  await page.waitForTimeout(300);
  return page;
}
const tid = (p, id) => p.getByTestId(id);
const clockT = (p) => p.getByTestId("clock").getAttribute("data-t").then(Number);
const videoT = (p) => p.getByTestId("result-video").evaluate((v) => v.currentTime);
const videoPaused = (p) => p.getByTestId("result-video").evaluate((v) => v.paused);
const near = (a, b, tol, msg) => assert.ok(Math.abs(a - b) <= tol, `${msg}: ${a} vs ${b}`);
async function settledAt(p, at, msg) {
  await p.waitForFunction((t) => Math.abs(Number(document.querySelector('[data-testid="clock"]').dataset.t) - t) < 0.001
    && document.querySelector('[data-testid="play"]').dataset.playing === "false", at, { timeout: 6000 });
  await p.waitForTimeout(250);
  near(await clockT(p), at, 0.001, `${msg}: 3D clock`);
  near(await videoT(p), at, 0.12, `${msg}: video`);
  assert.equal(await videoPaused(p), true, `${msg}: video paused on the moment`);
}
/** Click `testid`, then sample both clocks every 40 ms for `ms`. */
const clickAndSample = (p, testid, ms) => p.evaluate(([id, ms]) => new Promise((resolve) => {
  const clock = document.querySelector('[data-testid="clock"]');
  const v = document.querySelector('[data-testid="result-video"]');
  const out = [];
  const t0 = performance.now();
  document.querySelector(`[data-testid="${id}"]`).click();
  const timer = setInterval(() => {
    out.push({ t: Number(clock.dataset.t), v: v.currentTime, paused: v.paused });
    if (performance.now() - t0 > ms) { clearInterval(timer); resolve(out); }
  }, 40);
}), [testid, ms]);
const noSideScroll = async (p, name) => assert.ok((await p.evaluate(() => document.documentElement.scrollWidth)) <= 412, `${name}: side scroll`);

try {
  const p = await open("ok");
  // ---- the video and the lost first seek ----------------------------------------------------------------
  assert.equal(await tid(p, "coach-stage").getAttribute("data-state"), "ready");
  assert.ok(await tid(p, "result-video").isVisible());
  near(await tid(p, "result-video").evaluate((v) => v.duration), 12, 0.3, "the test clip is 12 s");
  const worstWindow = ins.score.timeline.reduce((a, b) => (b.value < a.value ? b : a));
  near(await clockT(p), worstWindow.t_s[0], 0.001, "the timeline's opening window reaches the 3D clock");
  near(await videoT(p), worstWindow.t_s[0], 0.12, "and the video");
  assert.equal(await tid(p, "timeline-6").getAttribute("aria-pressed"), "true");
  await p.screenshot({ path: path.join(SHOTS, "20-coach-top.png"), fullPage: true });
  ok("the result shows the follower video and the first seek is no longer lost (video and 3D at the worst window)");

  // ---- a coaching row reads as a moment, and a tap moves both -------------------------------------------
  const x0 = ins.insights[0];
  assert.equal((await tid(p, "moment-chip-insight-0").textContent()).trim(), `At ${x0.at_s.toFixed(1)} s:`);
  assert.equal(await tid(p, "moment-chip-insight-0").getAttribute("data-at-s"), String(x0.at_s));
  assert.equal(await tid(p, "insight-0-cue").textContent(), x0.cue);
  assert.equal(await tid(p, "insight-0").getAttribute("data-cue-kind"), x0.kind, "rows carry their cue kind for the breakdown");
  assert.equal(await tid(p, "insight-4").getAttribute("data-cue-kind"), "tempo");
  const s = await clickAndSample(p, "insight-0", 2400);
  assert.ok(s.some((x) => x.t < x0.at_s - 0.3 && x.t >= x0.at_s - 1.05), "the lead-in plays up to a second before the moment");
  assert.ok(s.some((x) => !x.paused), "the video plays during the lead-in");
  const mid = s.filter((x) => x.t > x0.at_s - 0.8 && x.t < x0.at_s - 0.1 && !x.paused);
  assert.ok(mid.length && mid.every((x) => Math.abs(x.v - x.t) < 0.35), "during the lead-in video and 3D agree");
  assert.ok(Math.max(...s.map((x) => x.t)) <= x0.at_s + 0.001, "it stops on the moment and does not run past it");
  await settledAt(p, x0.at_s, "insight 0");
  ok("a tap on an insight plays the lead-in on the video and the 3D view and stops on the moment, both at at_s");

  // a fault-style row: a timeline miss moves the video too
  await tid(p, "timeline-6").click();
  await tid(p, "timeline-6-miss-0").click();
  const m0 = ins.score.timeline[6].misses[0];
  assert.equal((await tid(p, "moment-chip-timeline-6-0").textContent()).trim(), `At ${m0.at_s.toFixed(1)} s:`);
  assert.equal(await tid(p, "timeline-6-miss-0").getAttribute("data-cue-kind"), m0.cue_kind);
  await settledAt(p, m0.at_s, "timeline miss");
  ok("timeline misses read as moments and carry data-cue-kind");

  // ---- moments to review ---------------------------------------------------------------------------------
  const flagged = ins.score.timeline.map((w, i) => [w, i]).filter(([w]) => w.value <= ins.score.value - 15).map(([, i]) => i);
  for (const i of flagged) assert.equal(await tid(p, `timeline-${i}`).getAttribute("data-review"), "true", `window ${i} marked`);
  assert.equal(await tid(p, "timeline-4").getAttribute("data-review"), null, "a window only 8 points under is not marked");
  assert.equal(await tid(p, "timeline-0").getAttribute("data-review"), null);
  assert.equal(await p.locator('.sr-tl-bar[data-review="true"]').count(), flagged.length);
  const nMoments = await p.locator('[data-testid^="moment-marker-"]').count();
  assert.ok(nMoments >= flagged.length, "a mark for every flagged window");
  assert.equal(await p.locator('[data-testid^="moment-"][data-kind]').count(), nMoments, "the list repeats the marks");
  const first = tid(p, "moment-0");
  const at0 = Number(await first.getAttribute("data-at"));
  assert.equal((await first.textContent()).startsWith(`At ${at0.toFixed(1)} s:`), true);
  await first.click();
  await settledAt(p, at0, "moment 0");
  const marker = tid(p, `moment-marker-${nMoments - 1}`);
  const atLast = Number(await marker.getAttribute("data-at"));
  await marker.click();
  await settledAt(p, atLast, "last mark");
  const head = await tid(p, "moments-playhead").evaluate((e) => parseFloat(e.style.left));
  near(head, (atLast / 12.8) * 100, 6, "the playhead sits at the tapped moment on the strip");
  await p.screenshot({ path: path.join(SHOTS, "21-coach-moments.png"), fullPage: true });
  ok(`moments to review: ${nMoments} marks (windows 15+ points under ${ins.score.value}, biggest misses); a tap moves video and 3D`);

  // ---- replay worst moment -------------------------------------------------------------------------------
  const btn = tid(p, "replay-worst");
  assert.equal(await btn.textContent(), "Replay worst moment");
  near(Number(await btn.getAttribute("data-from")), worstWindow.t_s[0], 0.001, "loops from the worst window");
  near(Number(await btn.getAttribute("data-to")), worstWindow.t_s[1], 0.001, "to its end");
  const loop = await clickAndSample(p, "replay-worst", 3600);
  assert.equal(await btn.getAttribute("aria-pressed"), "true");
  assert.equal(await tid(p, "coach-stage").getAttribute("data-looping"), "true");
  const [a, b] = worstWindow.t_s;
  assert.ok(loop.every((x) => x.t >= a - 0.05 && x.t <= b + 0.05), "3D stays inside the worst window");
  assert.ok(loop.slice(1).some((x, i) => x.t < loop[i].t - 0.5), "and wraps back to its start");
  assert.ok(loop.filter((x) => !x.paused && Math.abs(x.v - x.t) < 0.4).length > loop.length * 0.6, "the video loops with it");
  await btn.click();
  assert.equal(await btn.getAttribute("aria-pressed"), "false");
  assert.equal(await btn.textContent(), "Replay worst moment");
  const stopped = await clockT(p);
  await p.waitForTimeout(600);
  near(await clockT(p), stopped, 0.001, "after Stop the clock stays put");
  assert.equal(await videoPaused(p), true);
  ok("Replay worst moment loops the lowest window on video and 3D, and Stop holds both");

  // the visitor's own scrub ends a replay
  await btn.click();
  await p.waitForTimeout(300);
  await tid(p, "scrub").evaluate((e) => { e.value = "2"; e.dispatchEvent(new Event("input", { bubbles: true })); });
  await p.waitForTimeout(500);
  assert.equal(await btn.getAttribute("aria-pressed"), "false");
  near(await clockT(p), 2, 0.001, "scrub wins over the loop");
  near(await videoT(p), 2, 0.12, "and moves the video");
  ok("using the 3D scrub ends the replay");

  await p.context().close();

  // ---- the breakdown slot: filled by another lane's module once the coaching rows exist -----------------------
  {
    const b = await open("ok");
    assert.equal(await tid(b, "breakdown-slot").count(), 1);
    const order = await b.evaluate(() => [...document.querySelectorAll('[data-testid="score-panel"], [data-testid="breakdown-slot"], [data-testid="challenge-slot"], [data-testid="mode-slot"]')].map((e) => e.dataset.testid));
    assert.deepEqual(order, ["mode-slot", "score-panel", "breakdown-slot", "challenge-slot"]);
    await b.waitForSelector('[data-testid="breakdown-slot"] [data-testid="breakdown"]');
    await b.context().close();
    const gone = await open("ok", { block: "breakdown.js" });
    assert.equal(await tid(gone, "breakdown-slot").evaluate((e) => e.childElementCount), 0, "a missing module leaves the slot empty");
    assert.ok(await tid(gone, "fault-list").count() + await tid(gone, "insights").count() > 0, "and the rest of the result still shows");
    await gone.context().close();
    ok("mode, breakdown and challenge slots sit around the score panel and the breakdown fills its slot, and a missing module leaves it empty");
  }

  // ---- B2: a tempo moment in the breakdown panel moves the real result's video and 3D clock ------------------------
  {
    const b = await open("ok");
    await b.waitForSelector('[data-testid="tempo-moment"]');
    const ats = await b.locator('[data-testid="tempo-moment"]').evaluateAll((els) => els.map((e) => Number(e.dataset.at)));
    const here0 = await clockT(b);
    const idx = ats.findIndex((a) => Math.abs(a - here0) > 0.6 && a > 1.2);
    assert.ok(idx >= 0, `a tempo moment away from ${here0}: ${ats}`);
    const before = { t: here0, v: await videoT(b) };
    await b.locator('[data-testid="tempo-moment"]').nth(idx).click();
    await settledAt(b, ats[idx], "tempo moment");
    assert.ok(Math.abs(await clockT(b) - before.t) > 0.5, "the 3D clock moved");
    assert.ok(Math.abs((await videoT(b)) - before.v) > 0.5, "the video moved");
    await b.context().close();
    ok("a tempo moment in the breakdown seeks the video and the 3D clock on the real result screen (simon:seek)");

    // negative: after destroy the document listener is gone
    const n = await open("ok");
    const calls = await n.evaluate(() => {
      let c = 0;
      const r = window.__r;
      const orig = r.coach.goTo;
      r.coach.goTo = (t) => { c++; return orig(t); };
      const fire = () => document.dispatchEvent(new CustomEvent("simon:seek", { detail: { at_s: 3 } }));
      fire();
      const live = c;
      r.destroy();
      fire();
      return { live, after: c };
    });
    assert.deepEqual(calls, { live: 1, after: 1 }, "one call while mounted, none after destroy");
    await n.context().close();
    ok("destroy removes the simon:seek listener");
  }

  // ---- R4: the Shape/Timing tags survive the timeline rebuilding its miss rows -------------------------------------
  {
    const r = await open("ok");
    await r.waitForSelector('[data-testid="breakdown"]');
    const withMisses = ins.score.timeline.map((w, i) => [w, i]).filter(([w]) => (w.misses || []).some((m) => m.cue_kind)).map(([, i]) => i);
    assert.ok(withMisses.length >= 2, "two windows with typed misses");
    for (const i of withMisses) {
      await tid(r, `timeline-${i}`).click();
      await r.waitForFunction(() => {
        const rows = [...document.querySelectorAll(".sr-tl-miss[data-cue-kind]")];
        return rows.length > 0 && rows.every((x) => x.querySelector('[data-testid="kind-tag"]'));
      }, null, { timeout: 3000 });
      assert.equal(await r.locator(".sr-tl-miss [data-testid=kind-tag]").count(), await r.locator(".sr-tl-miss[data-cue-kind]").count(), `window ${i}`);
    }
    await r.context().close();
    ok("after tapping another timeline window its miss rows are tagged Shape or Timing");
  }

  // ---- R3: a video that never loads does not hold the rest of the result back ---------------------------------
  {
    const t0 = Date.now();
    const h = await open("golden", { hangVideo: true });
    assert.ok(Date.now() - t0 < 15000);
    assert.equal(await tid(h, "coach-stage").count(), 1, "N1: the stage stays up after the settle timeout");
    assert.ok(await tid(h, "fault-list").isVisible(), "faults render");
    assert.ok(await tid(h, "download-analysis").count() === 1, "downloads render");
    await h.waitForSelector('[data-testid="breakdown"]');
    await h.context().close();
    ok("a video that never loads times out, the stage stays, and the faults, downloads and breakdown still render");
  }

  // ---- N1: a video that answers after the 4 s settle timeout still works ---------------------------------------
  {
    const l = await open("golden", { lateVideoMs: 5500 });
    assert.ok(await tid(l, "fault-list").isVisible(), "faults rendered at the timeout");
    assert.equal(await tid(l, "coach-stage").count(), 1, "stage present at the timeout");
    await l.waitForFunction(() => document.querySelector('[data-testid="coach-stage"]').getAttribute("data-state") === "ready", null, { timeout: 8000 });
    await l.context().close();
    ok("a video that loads after the settle timeout becomes ready in the kept stage");
  }

  // ---- N1: a real load error removes the stage ---------------------------------------------------------------------
  {
    const e = await open("novideo");
    assert.equal(await tid(e, "coach-stage").count(), 0, "the stage is removed on a load error");
    assert.equal(await tid(e, "download-analysis").count(), 1, "downloads render");
    await e.context().close();
    ok("a video load error removes the stage and the downloads still render");
  }

  // ---- no timeline: the worst moment falls back to a fault; nothing to split ----------------------------
  {
    const g = await open("golden");
    const gold = JSON.parse(fs.readFileSync(path.join(here, "../../fixtures/input/analysis-1.5.0.json")));
    assert.equal(Number(await tid(g, "replay-worst").getAttribute("data-at")), gold.faults[0].at_s);
    assert.equal(await g.locator('[data-cue-kind="range"]').count(), gold.faults.length * 2, "insights and faults carry their kind");
    assert.equal((await tid(g, "moment-chip-insight-0").textContent()).trim(), `At ${gold.insights[0].at_s.toFixed(1)} s:`);
    await tid(g, "fault-1").click();
    await settledAt(g, gold.faults[1].at_s, "fault tap");
    await g.context().close();
    ok("without a timeline the worst moment is the fault with the most points; fault taps move video and 3D");
  }

  // ---- a flawless take has no weak moment --------------------------------------------------------------------
  {
    const f = await open("flawless");
    assert.equal(await tid(f, "replay-worst").count(), 0);
    assert.equal(await f.locator('[data-testid^="moment-marker-"]').count(), 0);
    assert.ok(await tid(f, "moments-empty").isVisible());
    assert.equal(await f.locator('.sr-tl-bar[data-review="true"]').count(), 0);
    await f.context().close();
    ok("a flawless take: no worst moment, no marks, an honest empty line");
  }

  // ---- the video is missing: the 3D view still works -------------------------------------------------------------
  {
    const n = await open("novideo");
    assert.equal(await tid(n, "coach-stage").count(), 0);
    assert.equal(await tid(n, "replay-worst").count(), 0);
    await tid(n, "moment-0").click();
    const at = Number(await tid(n, "moment-0").getAttribute("data-at"));
    await n.waitForFunction((t) => Math.abs(Number(document.querySelector('[data-testid="clock"]').dataset.t) - t) < 0.001, at, { timeout: 6000 });
    await noSideScroll(n, "novideo");
    await n.context().close();
    ok("a missing video leaves no player, and a moment tap still moves the 3D view");
  }

  // ---- no WebGL: the video carries the moments ---------------------------------------------------------------
  {
    const w = await open("ok", { noWebgl: true });
    assert.equal(await tid(w, "coach-stage").getAttribute("data-state"), "ready");
    assert.equal(await tid(w, "result-video").getAttribute("controls"), "", "the video has its own controls");
    const at = Number(await tid(w, "moment-0").getAttribute("data-at"));
    await tid(w, "moment-0").click();
    await w.waitForFunction((t) => { const v = document.querySelector('[data-testid="result-video"]'); return v.paused && Math.abs(v.currentTime - t) < 0.12; }, at, { timeout: 6000 });
    near(await videoT(w), at, 0.12, "video-only moment tap");
    await w.context().close();
    ok("without WebGL the video alone plays the lead-in to the moment");
  }

  // ---- TICKET-087: one transport, and a paused clock does not move ----------------------------------------------
  {
    // the result opens paused, even when the video is slow: the staging drive reads the clock the moment the 3D view
    // shows and again 2 s later, while the video is still loading
    const ctx = await browser.newContext({ viewport: { width: 412, height: 915 }, hasTouch: true });
    const e = await ctx.newPage();
    e.on("pageerror", (x) => errors.push(`late-open: ${x.message}`));
    await e.route("**/coach.webm", async (r) => { await new Promise((res) => setTimeout(res, 1500)); await r.continue().catch(() => {}); });
    await e.goto(`http://127.0.0.1:${port}/tests/part7/harness/coach.html?case=ok`);
    await tid(e, "compare").waitFor({ state: "visible" });
    const c0 = await tid(e, "clock").innerText();
    await e.waitForTimeout(2500);
    assert.equal(await tid(e, "clock").innerText(), c0, "the clock the 3D view opened with did not move while the video loaded");
    await e.waitForFunction(() => window.__ready === true);
    assert.equal(await tid(e, "clock").innerText(), c0, "nor when the video became ready");
    assert.equal(await tid(e, "play").getAttribute("data-playing"), "false", "opens paused");
    assert.equal(await videoPaused(e), true, "the video opens paused");
    const o0 = await videoT(e);
    await e.waitForTimeout(1500);
    assert.equal(await videoT(e), o0, "and stays put");
    await ctx.close();
    ok("the result opens paused and neither clock moves while the video loads or after");
  }
  {
    const p = await open("ok");
    const still = async (why) => {
      const t = await clockT(p), v = await videoT(p);
      await p.waitForTimeout(1500);
      assert.equal(await clockT(p), t, `${why}: 3D clock`);
      assert.equal(await videoT(p), v, `${why}: video clock`);
      assert.equal(await videoPaused(p), true, `${why}: video paused`);
      assert.equal(await tid(p, "play").getAttribute("data-playing"), "false", `${why}: 3D paused`);
    };
    await still("opened");
    // pause with the 3D view's play button
    await tid(p, "play").click();
    await p.waitForFunction(() => document.querySelector('[data-testid="play"]').dataset.playing === "true");
    await p.waitForTimeout(700);
    assert.equal(await videoPaused(p), false, "play starts the video with the 3D view");
    await tid(p, "play").click();
    await still("paused with the 3D play button");
    // pause with the video
    await tid(p, "play").click();
    await p.waitForTimeout(600);
    await tid(p, "result-video").click();
    await still("paused by tapping the video");
    // a moment tap plays the lead-in, then stops
    await tid(p, "moment-0").click();
    await p.waitForTimeout(1800);
    await still("after a moment tap");
    await p.context().close();
    ok("pausing from the 3D play button or from the video pauses both, and a moment tap stops on the moment");
  }

  assert.deepEqual(errors, []);
  console.log(`${passed} coach browser checks passed`);
} finally {
  await browser.close();
  server.close();
}
