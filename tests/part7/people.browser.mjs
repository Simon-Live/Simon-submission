// Browser checks for person choice and the group board at 412x915 (people.md AC-P1, P3, P4, P6).
// A fake API is installed with page.route; the harness is tests/part7/harness/people.html.
//   PLAYWRIGHT_DIR=/path/to/node_modules node tests/part7/people.browser.mjs
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
const fixture = (f) => JSON.parse(fs.readFileSync(path.join(here, "../../fixtures/input", f)));
const replay = fixture("replay.json");
const analysis = fixture("analysis-1.2.0.json");

const COLORS = ["#8aa4ff", "#3ddc97", "#ffc83d", "#ff7a90", "#c792ff", "#5cd6ff"];
const svg = (label, i) => `<svg xmlns="http://www.w3.org/2000/svg" width="240" height="320" viewBox="0 0 240 320"><rect width="240" height="320" fill="#1b2431"/><circle cx="120" cy="90" r="42" fill="${COLORS[i % 6]}"/><rect x="70" y="140" width="100" height="150" rx="40" fill="${COLORS[i % 6]}" opacity="0.8"/><text x="12" y="30" fill="#fff" font-size="22" font-family="sans-serif">${label}</text></svg>`;
const frameSvg = `<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360" viewBox="0 0 640 360"><rect width="640" height="360" fill="#202a38"/>${[0, 1, 2].map((i) => `<rect x="${60 + i * 190}" y="50" width="120" height="270" fill="none" stroke="${COLORS[i]}" stroke-width="4"/><text x="${66 + i * 190}" y="80" fill="${COLORS[i]}" font-size="28" font-family="sans-serif">${i + 1}</text>`).join("")}</svg>`;

const person = (id, coverage) => ({ id, coverage, frames: 100, box_mid: [0.1, 0.1, 0.2, 0.7] });
const JOBS = {
  p1: { id: "p1", kind: "people", status: "done", result: { people: [person(1, 0.95), person(2, 0.9), person(3, 0.4)], frame: "people/frame.jpg", auto_id: null } },
  pone: { id: "pone", kind: "people", status: "done", result: { people: [person(7, 0.97)], frame: "people/frame.jpg", auto_id: 7 } },
  pnone: { id: "pnone", kind: "people", status: "done", result: { people: [], frame: "people/frame.jpg", auto_id: null } },
  pmany: { id: "pmany", kind: "people", status: "done", result: { people: Array.from({ length: 10 }, (_, i) => person(i + 1, 0.9)), frame: "people/frame.jpg", auto_id: null } },
  pfail: { id: "pfail", kind: "people", status: "failed", note: "The tracker could not read the clip." },
  g1: {
    id: "g1", kind: "group", status: "done",
    result: {
      entry_id: "e1", trainer_id: 1,
      people: [
        { id: 2, label: "Front row left", status_code: "ok", score: 88, grade: "B", faults: [{}, {}] },
        { id: 3, label: "Front row right", status_code: "ok", score: 73, grade: "C", faults: [{}, {}, {}, {}] },
        { id: 5, label: "", status_code: "ok", score: 61, grade: "D", faults: [{}] },
        { id: 4, label: "Back row", status_code: "different_movement", score: null, grade: null, faults: [] },
      ],
    },
  },
};
let slowCalls = 0;

async function install(page) {
  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url());
    const p = url.pathname.replace(/^.*\/api\//, "api/");
    let m;
    if (p === "api/client-log") return route.fulfill({ status: 204, body: "" });
    if ((m = /^api\/jobs\/([^/]+)\/people\/(frame|\d+)\.jpg$/.exec(p))) {
      return route.fulfill({ contentType: "image/svg+xml", body: m[2] === "frame" ? frameSvg : svg(`Person ${m[2]}`, Number(m[2]) || 0) });
    }
    if ((m = /^api\/jobs\/([^/]+)$/.exec(p))) {
      if (m[1] === "pslow") {
        slowCalls++;
        const body = slowCalls < 3 ? { id: "pslow", status: "running", note: "Tracking people" } : { ...JOBS.p1, id: "pslow" };
        return route.fulfill({ contentType: "application/json", body: JSON.stringify(body) });
      }
      const job = JOBS[m[1]];
      return job ? route.fulfill({ contentType: "application/json", body: JSON.stringify(job) }) : route.fulfill({ status: 404, contentType: "application/json", body: "{}" });
    }
    if ((m = /^api\/results\/g1\/(\d+)\/replay\.json$/.exec(p))) {
      if (m[1] === "4") return route.fulfill({ status: 422, contentType: "application/json", body: "{}" });
      const r = structuredClone(replay);
      const shift = Number(m[1]) % 3;
      r.follower = r.follower.map((_, i, a) => a[(i + shift * 6) % a.length]);
      return route.fulfill({ contentType: "application/json", body: JSON.stringify(r) });
    }
    if (/^api\/results\/g1\/\d+\/analysis\.json$/.test(p)) return route.fulfill({ contentType: "application/json", body: JSON.stringify(analysis) });
    return route.fulfill({ status: 404, body: "{}" });
  });
}

const { server, port } = await serveRoot();
const browser = await chromium.launch({ args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"] });
const errors = [];
let passed = 0;
const ok = (name) => { passed++; console.log(`ok - ${name}`); };

async function open(query, { noWebgl = false } = {}) {
  const ctx = await browser.newContext({ viewport: { width: 412, height: 915 }, deviceScaleFactor: 2, hasTouch: true });
  const page = await ctx.newPage();
  page.on("console", (m) => { if (m.type() === "error" && !/status of (404|422)/.test(m.text())) errors.push(`${query}: ${m.text()}`); });
  page.on("pageerror", (e) => errors.push(`${query}: ${e.message}`));
  if (noWebgl) {
    await page.addInitScript(() => {
      const orig = HTMLCanvasElement.prototype.getContext;
      HTMLCanvasElement.prototype.getContext = function (type, ...rest) { return /webgl/.test(type) ? null : orig.call(this, type, ...rest); };
    });
  }
  await install(page);
  await page.goto(`http://127.0.0.1:${port}/tests/part7/harness/people.html?${query}`);
  await page.waitForFunction(() => window.__ready === true);
  return page;
}
const tid = (page, id) => page.getByTestId(id);
const result = (page) => page.evaluate(() => window.__result);
const shot = (page, name, full = false) => page.screenshot({ path: path.join(SHOTS, name), fullPage: full });

try {
  // ---- AC-P1: one person skips the picker ---------------------------------------------------
  let page = await open("screen=picker&mode=single&job=pone");
  await page.waitForFunction(() => window.__result !== "pending");
  assert.deepEqual(await result(page), { person_id: 7, auto: true, count: 1 }); // judge-take.md: `auto` and `count` start a judge's take by themselves
  assert.equal(await tid(page, "people").count(), 0);
  ok("AC-P1 one person: resolves with auto_id and shows no picker");

  // ---- nobody found --------------------------------------------------------------------------
  page = await open("screen=picker&mode=single&job=pnone");
  await tid(page, "people-error").waitFor();
  assert.equal(await tid(page, "people-error").textContent(), "No one was found in this clip. Record again with the person in frame.");
  assert.equal(await tid(page, "people-continue").isDisabled(), true);
  ok("nobody found: plain message, continue disabled");

  // ---- failed people job -------------------------------------------------------------------
  page = await open("screen=picker&mode=single&job=pfail");
  await tid(page, "people-error").waitFor();
  assert.match(await tid(page, "people-error").textContent(), /could not read the clip/);
  ok("failed people job shows the job note");

  // ---- AC-P3: single mode picker ----------------------------------------------------------
  page = await open("screen=picker&mode=single&job=p1");
  await tid(page, "person-1").waitFor();
  await page.waitForFunction(() => document.querySelector('[data-testid="people-frame"]').naturalWidth > 0);
  assert.equal(await tid(page, "people-continue").isDisabled(), true);
  await shot(page, "20-picker-single.png");
  await tid(page, "person-3").tap();
  assert.equal(await tid(page, "people-warning").isVisible(), true);
  assert.match(await tid(page, "people-warning").textContent(), /only part of the clip/);
  assert.equal(await tid(page, "people-continue").isDisabled(), false);
  await tid(page, "person-2").tap();
  assert.equal(await tid(page, "people-warning").isHidden(), true);
  assert.equal(await tid(page, "person-3").getAttribute("aria-pressed"), "false");
  assert.equal(await tid(page, "person-2").getAttribute("aria-pressed"), "true");
  await shot(page, "21-picker-single-chosen.png");
  await tid(page, "people-continue").tap();
  assert.deepEqual(await result(page), { person_id: 2 });
  assert.equal(await tid(page, "people").count(), 0);
  ok("AC-P3 single picker: choose, low coverage warning allows continue, resolves {person_id}");

  // ---- cancel ------------------------------------------------------------------------------
  page = await open("screen=picker&mode=single&job=p1");
  await tid(page, "person-1").waitFor();
  await tid(page, "people-cancel").tap();
  assert.equal(await result(page), null);
  ok("cancel resolves null");

  // ---- polling until the job is done ------------------------------------------------------
  page = await open("screen=picker&mode=single&job=pslow");
  await tid(page, "person-1").waitFor({ timeout: 5000 });
  ok("picker polls the job until it is done");

  // ---- AC-P4: group picker -----------------------------------------------------------------
  page = await open("screen=picker&mode=group&job=p1&trim=12000");
  await tid(page, "person-1").waitFor();
  assert.equal(await tid(page, "people-continue").isDisabled(), true);
  await tid(page, "person-1").tap(); // first tap marks the trainer
  assert.equal(await tid(page, "person-trainer-1").getAttribute("aria-pressed"), "true");
  assert.equal(await tid(page, "person-2").getAttribute("aria-pressed"), "true");
  assert.equal(await tid(page, "person-3").getAttribute("aria-pressed"), "true");
  assert.equal(await tid(page, "person-label-2").isVisible(), true);
  assert.equal(await tid(page, "person-label-1").isHidden(), true);
  await tid(page, "person-label-2").fill("Front row left");
  await tid(page, "person-3").tap(); // deselect
  assert.equal(await tid(page, "person-3").getAttribute("aria-pressed"), "false");
  assert.equal(await tid(page, "person-label-3").isHidden(), true);
  await shot(page, "22-picker-group.png", true);
  await tid(page, "people-continue").tap();
  assert.deepEqual(await result(page), { trainer_id: 1, follower_ids: [2], labels: { 2: "Front row left" } });
  ok("AC-P4 group picker: trainer, default followers, deselect, label, resolves the group choice");

  // switching the trainer moves the badge
  page = await open("screen=picker&mode=group&job=p1");
  await tid(page, "person-1").waitFor();
  await tid(page, "person-trainer-2").tap();
  assert.equal(await tid(page, "person-trainer-2").getAttribute("aria-pressed"), "true");
  await tid(page, "person-trainer-1").tap();
  assert.equal(await tid(page, "person-trainer-2").getAttribute("aria-pressed"), "false");
  await tid(page, "person-2").tap();
  await tid(page, "person-3").tap();
  assert.equal(await tid(page, "people-continue").isDisabled(), true);
  assert.match(await page.locator(".lede").textContent(), /at least one person/);
  ok("group picker: change trainer; no followers blocks continue with plain words");

  // ---- AC-P6: limits ------------------------------------------------------------------------
  page = await open("screen=picker&mode=group&job=p1&trim=30500");
  await tid(page, "people-error").waitFor();
  assert.match(await tid(page, "people-error").textContent(), /30 seconds or less/);
  ok("AC-P6 over 30 s trimmed is refused in group mode");

  page = await open("screen=picker&mode=group&job=pmany");
  await tid(page, "person-1").waitFor();
  await tid(page, "person-1").tap();
  const on = await page.locator('[data-role="follower"]').count();
  assert.equal(on, 8);
  await tid(page, "person-10").tap();
  assert.match(await tid(page, "people-error").textContent(), /at most 8/);
  assert.equal(await tid(page, "person-10").getAttribute("aria-pressed"), "false");
  await tid(page, "person-2").tap();
  await tid(page, "person-10").tap();
  assert.equal(await tid(page, "person-10").getAttribute("aria-pressed"), "true");
  await tid(page, "people-continue").tap();
  const r = await result(page);
  assert.equal(r.trainer_id, 1);
  assert.equal(r.follower_ids.length, 8);
  ok("AC-P6 at most 8 followers: the ninth is refused with plain words");

  page = await open("screen=picker&mode=group&job=pone");
  await tid(page, "people-error").waitFor();
  assert.match(await tid(page, "people-error").textContent(), /trainer and at least one other/);
  ok("group mode with one person says so");

  // ---- mode switch -------------------------------------------------------------------------
  page = await open("screen=switch");
  assert.equal(await tid(page, "mode-solo").getAttribute("aria-pressed"), "true");
  await tid(page, "mode-group").tap();
  assert.equal(await tid(page, "mode-group").getAttribute("aria-pressed"), "true");
  assert.equal(await tid(page, "mode-solo").getAttribute("aria-pressed"), "false");
  await tid(page, "mode-group").tap();
  await tid(page, "mode-solo").tap();
  assert.deepEqual(await page.evaluate(() => window.__events), ["group", "single"]);
  ok("mode switch: Just me and Group, onChange fires once per change");

  // ---- AC-P4: the board ---------------------------------------------------------------------
  page = await open("screen=board&job=g1");
  await tid(page, "group-board").waitFor();
  const order = await page.locator('[data-testid^="group-row-"]').evaluateAll((els) => els.map((e) => e.getAttribute("data-testid")));
  assert.deepEqual(order, ["group-row-2", "group-row-3", "group-row-5", "group-row-4"]);
  assert.equal(await tid(page, "group-score-2").textContent(), "88");
  assert.equal(await tid(page, "group-grade-2").textContent(), "B");
  assert.equal(await tid(page, "group-grade-5").textContent(), "D");
  assert.match(await tid(page, "group-row-3").textContent(), /Front row right/);
  assert.match(await tid(page, "group-row-3").textContent(), /4 faults/);
  assert.match(await tid(page, "group-row-5").textContent(), /Person 5/);
  assert.match(await tid(page, "group-row-5").textContent(), /1 fault(?!s)/);
  assert.match(await tid(page, "group-warning-4").textContent(), /different movement/);
  assert.equal(await tid(page, "group-score-4").textContent(), "0");
  assert.equal(await tid(page, "group-grade-4").textContent(), "F");
  assert.equal(await tid(page, "group-row-2").getAttribute("href"), "#/result/g1/2");
  await page.waitForFunction(() => [...document.images].every((i) => i.complete && i.naturalWidth > 0));
  await shot(page, "23-board.png");
  ok("AC-P4 board: one row per person in server order, score, grade, faults, a warning with a 0 and an F for a take that did not match, link to the result");

  await tid(page, "group-row-3").tap();
  assert.equal(await page.evaluate(() => location.hash), "#/result/g1/3");
  ok("AC-P4 a tap on a row opens #/result/<job>/<pid>");

  // ---- Watch all ---------------------------------------------------------------------------
  page = await open("screen=board&job=g1");
  await tid(page, "watch-all").tap();
  await tid(page, "multi-compare").waitFor();
  await tid(page, "group-toggle-2").waitFor();
  await page.waitForTimeout(600);
  assert.equal(await tid(page, "multi-compare").getAttribute("data-people"), "2,3,5");
  assert.equal(await page.locator('[data-testid^="group-toggle-"]').count(), 3);
  assert.equal(await tid(page, "multi-compare").getAttribute("data-mode"), "overlay");
  const lit = await page.evaluate(() => { const c = document.querySelector("canvas"); return !!c && c.width > 0; });
  assert.equal(lit, true);
  await tid(page, "play").tap();
  await page.waitForTimeout(700);
  assert.ok(Number(await tid(page, "clock").getAttribute("data-t")) > 0.3);
  await tid(page, "play").tap();
  await shot(page, "24-watch-all.png", true);
  await tid(page, "group-toggle-3").tap();
  assert.equal(await tid(page, "group-toggle-3").getAttribute("aria-pressed"), "false");
  assert.equal(await tid(page, "multi-compare").getAttribute("data-hidden"), "3");
  await shot(page, "25-watch-all-hidden.png", true);
  await tid(page, "group-toggle-3").tap();
  assert.equal(await tid(page, "multi-compare").getAttribute("data-hidden"), "");
  await tid(page, "watch-all").tap();
  assert.equal(await tid(page, "multi-compare").count(), 0);
  ok("Watch all: three followers over the ghost, play, hide and show per person, close");

  page = await open("screen=board&job=g1", { noWebgl: true });
  await tid(page, "watch-all").tap();
  await tid(page, "multi-note").waitFor();
  assert.match(await tid(page, "multi-note").textContent(), /3D view is not available/);
  ok("Watch all without WebGL says so and keeps the board");

  // ---- board errors -----------------------------------------------------------------------
  page = await open("screen=board&job=nope");
  await tid(page, "not-found").waitFor();
  ok("a missing group job shows not found");
} finally {
  await browser.close();
  server.close();
}
if (errors.length) { console.error(errors.join("\n")); process.exit(1); }
console.log(`${passed} browser checks passed`);
