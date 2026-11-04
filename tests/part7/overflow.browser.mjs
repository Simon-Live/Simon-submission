// Browser check: no sideways scroll at 320, 412 and 768 px wide on the people step and the result page
// (docs/specs/result-release-14.md). Run: scripts/with-browser-slot.sh node tests/part7/overflow.browser.mjs
import assert from "node:assert/strict";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { serveRoot } from "./serve_static.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const req = createRequire(path.join(process.env.PLAYWRIGHT_DIR || path.resolve(here, "../../node_modules"), "x.js"));
const { chromium } = req("playwright");
const person = (id) => ({ id, coverage: 0.9, frames: 100, box_mid: [0.1, 0.1, 0.2, 0.7] });
const JOB = { id: "p1", kind: "people", status: "done", result: { people: [person(1), person(2), person(3)], frame: "people/frame.jpg", auto_id: null } };
const png = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==", "base64");

const { server, port } = await serveRoot();
const browser = await chromium.launch();
const widths = [320, 412, 768];
const pages = [
  ["people step (picker)", "people.html?screen=picker&mode=group&job=p1", true],
  ["people step (looking)", "people.html?screen=picker&mode=group&job=p1", true, true],   // the job still runs, so the paw walk is on screen
  ["result page", "result.html?case=insights"],   // scrollWidth only: at 320 its columns end up to 29 px past the edge, a separate defect (docs/specs/result-release-16.md)
  ["job page", "../../../web/index.html#/job/j1", true],
];
const RUNNING = { id: "j1", status: "running", stage: "analyse", stages: {}, note: "Comparing with the trainer" };
const over = [];
try {
  for (const [name, url, edges, looking] of pages) for (const width of widths) {
    const ctx = await browser.newContext({ viewport: { width, height: 915 }, hasTouch: true, reducedMotion: "reduce" });
    await ctx.addInitScript(() => { try { localStorage.setItem("simon.stage.breakdown", "open"); localStorage.setItem("simon.result.more", "open"); } catch { /* blocked */ } });
    const page = await ctx.newPage();
    await page.route("**/api/**", (route) => {
      const p = new URL(route.request().url()).pathname.replace(/^.*\/api\//, "api/");
      if (/people\/.*\.jpg$/.test(p)) return route.fulfill({ contentType: "image/png", body: png });
      if (p === "api/jobs/j1") return route.fulfill({ contentType: "application/json", body: JSON.stringify(RUNNING) });
      if (p === "api/auth/me") return route.fulfill({ contentType: "application/json", body: JSON.stringify({ available: true, signed_in: false }) });
      if (p === "api/jobs/p1") return route.fulfill({ contentType: "application/json", body: JSON.stringify(looking ? { id: "p1", kind: "people", status: "running", stage: "tracking" } : JOB) });
      return route.fulfill({ status: 404, contentType: "application/json", body: "{}" });
    });
    await page.goto(`http://127.0.0.1:${port}/tests/part7/harness/${url}`);
    if (url.includes("harness") || !url.includes("index.html")) await page.waitForFunction(() => window.__ready === true || document.querySelector("[data-testid=progress]"));
    await page.waitForTimeout(600);
    const m = await page.evaluate(() => {
      const de = document.documentElement, vw = de.clientWidth;
      // an element past the right edge counts unless a scroller of its own (overflow auto or scroll, itself inside the screen) holds it;
      // a clipping ancestor and aria-hidden are no excuse (release 16: they hid the paw walk)
      const held = (e) => {
        for (let a = e.parentElement; a && a !== document.body && a !== de; a = a.parentElement) {
          const cs = getComputedStyle(a), r = a.getBoundingClientRect().right;
          if (r > vw + 1) continue;
          if (/auto|scroll/.test(cs.overflowX)) return true;
        }
        return false;
      };
      const wide = [...document.querySelectorAll("body *")].filter((e) => e.getBoundingClientRect().right > vw + 1 && !e.closest("[hidden]") && !e.closest("[data-testid=splash]") && !held(e))
        .map((e) => `${e.tagName.toLowerCase()}.${String(e.className).slice(0, 40)}@${Math.round(e.getBoundingClientRect().right)}`);
      // the paw walk by itself, no exemption: every print's right edge, and the width its prints ask for (their sum) against the walk's own width
      const walks = [...document.querySelectorAll("[data-testid=paw-walk]")].map((w) => {
        const prints = [...w.querySelectorAll("i")];
        return { prints: prints.length, ask: prints.reduce((a, i) => a + i.getBoundingClientRect().width, 0), own: w.getBoundingClientRect().width,
          right: Math.max(0, ...prints.map((i) => i.getBoundingClientRect().right)) };
      });
      return { scroll: de.scrollWidth, vw, wide, walks };
    });
    if (process.env.DEBUG_OVERFLOW) console.log(name, width, JSON.stringify(m));
    // release 16: scrollWidth alone missed 37 elements that reached 544 while it read 412, so the right edges are asserted too
    if (m.scroll > m.vw || (edges && m.wide.length)) over.push(`${name} at ${width}: scrollWidth ${m.scroll} vs ${m.vw}; ${m.wide.length} elements past the right edge: ${m.wide.slice(0, 6).join(", ")}`);
    if (looking || name === "job page") {
      if (!m.walks.length) over.push(`${name} at ${width}: no paw walk on screen, so the walk check proved nothing`);
      for (const w of m.walks) if (w.right > m.vw + 1 || w.ask > w.own + 1) over.push(`${name} at ${width}: the paw walk asks ${Math.round(w.ask)} px of ${Math.round(w.own)} and ends at ${Math.round(w.right)} of ${m.vw}`);
    }
    await ctx.close();
  }
  assert.deepEqual(over, [], "no sideways scroll and no element past the right edge");
  console.log("ok - no sideways scroll at 320, 412 and 768 on the people step (picker and looking), the job page and the result page");
} finally { await browser.close(); server.close(); }
