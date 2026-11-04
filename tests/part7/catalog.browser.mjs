// Browser checks for the demo catalog, the flags, the consent line and Delete this take at 412x915
// (TICKET-131, TICKET-137, TICKET-159). The page is the real app; the API is a small fake served by this file.
//   PLAYWRIGHT_DIR=/path/to/node_modules/playwright node tests/part7/catalog.browser.mjs [shots-dir]
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const WEB = path.resolve(here, "../../web");
const FIX = path.resolve(here, "../../fixtures/input");
const out = path.resolve(process.argv[2] || path.join(here, "screens"));
fs.mkdirSync(out, { recursive: true });
const { chromium } = createRequire(import.meta.url)(process.env.PLAYWRIGHT_DIR || "playwright");
const TYPES = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json" };

const frames = Array.from({ length: 30 }, (_, i) => {
  const a = Math.sin(i / 4) * 0.3;
  const j = (x, y) => ({ x, y, z: 0, conf: 1 });
  return { frame: i, t_ms: i * 33, people: [{ id: 0, joints: {
    nose: j(0, 1.6), left_shoulder: j(0.2, 1.4), right_shoulder: j(-0.2, 1.4), left_elbow: j(0.4, 1.2 + a), right_elbow: j(-0.4, 1.2 - a),
    left_wrist: j(0.5, 1 + a), right_wrist: j(-0.5, 1 - a), left_hip: j(0.1, 0.9), right_hip: j(-0.1, 0.9),
    left_knee: j(0.1, 0.5), right_knee: j(-0.1, 0.5), left_ankle: j(0.1, 0.05), right_ankle: j(-0.1, 0.05) } }] };
});
const entry = (id, name, extra = {}) => ({ id, name, category: "dance", files_source: "fixture", video_uri: null, animation: "animation.json", duration_ms: 1000, ...extra });
const ENTRIES = [
  entry("verify-2026-10-31t06-23-06z-317d3534", "verify 2026-10-31T06:23:06Z", { files_source: "import" }),
  entry("arm-salute-8b6512a8", "arm salute", { files_source: "import" }),
  entry("squat", "Squat", { category: "exercise", video_uri: "video.mp4" }), // TICKET-316: the judge view lists entries with a trainer video
  entry("arm-wave", "Arm wave", { video_uri: "video.mp4" }),
  entry("extra-move", "Extra move"),
];
const LABELS = { "extra-move": { tags: ["rehab"], notes: "" } };
const JOBS = { gj1: { id: "gj1", kind: "group", status: "done", entry_id: "arm-wave", result: {} }, tj1: { id: "tj1", kind: "trainer", status: "done", entry_id: "arm-wave", result: { entry_id: "arm-wave" } }, tj2: { id: "tj2", kind: "trainer", status: "done", entry_id: "arm-wave", result: { entry_id: "arm-wave" } }, rj1: { id: "rj1", kind: "follow", status: "done", entry_id: "arm-wave", result: { score: 80, grade: "B" } } };
// The judge URL (docs/specs/judge-view.md): the server writes the default-profile meta into the page and lists boards.
const judge = { on: false, heroAsked: 0, boardQueries: [] };
const BOARDS = [
  { id: "bReal", entry_id: "arm-wave", title: "Beat my wave", kind: "friend", entry_count: 1, ended: false, leader: null },
  { id: "bVerify", entry_id: "verify-2026-10-31t06-23-06z-317d3534", title: "Beat my verify", kind: "friend", entry_count: 1, ended: false, leader: null },
  { id: "bWave", entry_id: "arm-wave", title: "Beat my verify wave", kind: "friend", entry_count: 1, ended: false, leader: null },
];
const posts = [];
const deletes = [];
const deleteBodies = [];

const json = (res, body, status = 200) => { res.writeHead(status, { "content-type": "application/json" }); res.end(JSON.stringify(body)); };
const server = http.createServer((req, res) => {
  const url = new URL(req.url, "http://x");
  const p = decodeURIComponent(url.pathname);
  const chunks = [];
  req.on("data", (c) => chunks.push(c));
  req.on("end", () => {
    let m;
    // a failed policy load is fail-closed (policy.js): the fake answers an open policy so Rehab shows
    if (p === "/api/policy") return json(res, { prod: false, switches: { rehab: true, face_copy: true, trainer_public: true, prize_boards: true, byok_ranked: true, mms_tts: true, muse: true }, phrasing_live: true, consent: { required: false, version: null, items: [], header: "X-Simon-Consent" }, age: { minimum: 18, adult: 18 } });
    if (p === "/api/config") return json(res, { limits: { max_seconds: 60, max_bytes: 95000000, recorder_bps: 2500000 }, part5: { lang: true, video: true, private: true } });
    if (p === "/api/client-log") { res.writeHead(200, { "Content-Type": "application/json" }); return res.end('{"ok": true}'); }
    if (p === "/api/policy") return json(res, { prod: false, switches: { face_copy: true, rehab: true, trainer_public: true, prize_boards: true, byok_ranked: true, mms_tts: true, muse: true }, phrasing_live: false, age: { minimum: 13, adult: 18 }, consent: { required: false, version: null, items: [], header: "X-Simon-Consent" } }); // non-prod: a failed load would read as closed
    if (p === "/api/version") return json(res, { short: "abc123def", started_at: "2026-10-31T12:00:00Z", parts: {} });
    if (p === "/api/labels") return json(res, LABELS);
    if (p === "/api/judge/hero") { judge.heroAsked += 1; return json(res, { job_id: "rj1", entry_id: "arm-wave", score: 81, source: "configured" }); }
    if ((m = /^\/api\/movements\/([^/]+)\/boards$/.exec(p)) && judge.on) { // the movement page asks for cards, the same filter
      judge.boardQueries.push(url.search);
      const rows = BOARDS.filter((b) => b.entry_id === m[1] && (url.searchParams.get("view") !== "judge" || (!b.entry_id.startsWith("verify-") && b.id !== "bWave")));
      return json(res, { boards: rows.map((b) => ({ id: b.id, title: b.title, kind: b.kind, visibility: "public", ends_at: null, ended: false, entries: 1, viewer_rank: null, top: [], url: `#/challenge/${b.id}` })) });
    }
    if (/^\/api\/(boards|movements\/[^/]+\/boards)$/.test(p)) return json(res, { boards: [] });
    if (p === "/api/challenges" && judge.on) {
      judge.boardQueries.push(url.search);
      const rows = url.searchParams.get("view") === "judge" ? BOARDS.filter((b) => !b.entry_id.startsWith("verify-") && b.id !== "bWave") : BOARDS;
      return json(res, { challenges: rows });
    }
    if (p === "/api/challenges") return json(res, { challenges: [] });
    if (p === "/catalog/api/entries") return json(res, { entries: ENTRIES });
    if ((m = /^\/catalog\/api\/entries\/([^/]+)(?:\/(.+))?$/.exec(p))) {
      const found = ENTRIES.find((e) => e.id === m[1]);
      if (!found) return json(res, { error: "no" }, 404);
      if (!m[2]) return json(res, found);
      if (m[2] === "animation.json") return json(res, { fps: 30, frames });
      return json(res, { error: "no" }, 404);
    }
    if (p === "/api/follow") { posts.push(JSON.parse(Buffer.concat(chunks).toString() || "{}")); return json(res, { job: "rj1" }, 202); }
    if ((m = /^\/api\/jobs\/([^/]+)\/delete$/.exec(p))) {
      deletes.push([req.method, m[1]]);
      deleteBodies.push(Buffer.concat(chunks).toString());
      if (!JOBS[m[1]]) return json(res, { error: "This take was not found." }, 404);
      delete JOBS[m[1]];
      return json(res, { deleted: true, removed: ["job"], ...(m[1] === "tj2" ? { kept: ["entry"] } : {}) });
    }
    if ((m = /^\/api\/jobs\/([^/]+)$/.exec(p))) return JOBS[m[1]] ? json(res, JOBS[m[1]]) : json(res, { error: "no" }, 404);
    if ((m = /^\/api\/results\/gj1\/(?:0\/)?(analysis|replay)\.json$/.exec(p))) return res.writeHead(200, { "content-type": "application/json" }).end(fs.readFileSync(path.join(FIX, m[1] === "analysis" ? "analysis-1.2.0.json" : "replay.json")));
    if (p === "/api/results/rj1/analysis.json") return res.writeHead(200, { "content-type": "application/json" }).end(fs.readFileSync(path.join(FIX, "analysis-1.2.0.json")));
    if (p === "/api/results/rj1/replay.json") return res.writeHead(200, { "content-type": "application/json" }).end(fs.readFileSync(path.join(FIX, "replay.json")));
    const rel = p === "/" ? "index.html" : p.replace(/^\//, "");
    const file = path.resolve(WEB, rel);
    if (!file.startsWith(WEB) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) { res.writeHead(404).end("no"); return; }
    res.writeHead(200, { "content-type": TYPES[path.extname(file)] || "application/octet-stream" });
    const page = fs.readFileSync(file);
    res.end(judge.on && rel === "index.html" ? page.toString().replace("</head>", '<meta name="simon-default-profile" content="submission">\n</head>') : page);
  });
});
await new Promise((r) => server.listen(0, "127.0.0.1", r));
const BASE = `http://127.0.0.1:${server.address().port}/`;

const browser = await chromium.launch({ args: ["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"] });
const errors = [];
const fresh = async () => {
  const ctx = await browser.newContext({ viewport: { width: 412, height: 915 }, deviceScaleFactor: 2, permissions: ["camera"] });
  const page = await ctx.newPage();
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("console", (msg) => { if (msg.type() === "error" && !/Failed to load resource/.test(msg.text())) errors.push(msg.text()); });
  return page;
};
// The routine library (redesign): cards grouped in sections by kind; a rehab-tagged move shows under Rehab and its own kind.
const names = (page) => page.locator('[data-testid="entries"] .lib-name').allTextContents(); // one list, paged and filtered (home-browse.md)
const allIds = async (page) => [...new Set(await page.locator('[data-testid="entries"] .lib-thumb').evaluateAll((els) => els.map((e) => e.dataset.testid.replace(/^entry-rehab-/, "entry-"))))]; // distinct movements: the Rehab copy has its own test id
// TICKET-436: the header has no Exercise / Dance / Rehab switch in any profile
const kindSwitchCount = (page) => page.locator('[data-testid^="kind-"], .kind-switch, #kind-switch').count();
const tid = (pg, id) => pg.getByTestId(id);
const ok = (msg) => console.log(`ok  ${msg}`);

try {
  // ---- default catalog: curated first, no test entries, no arm salute, no build line, pitch
  let page = await fresh();
  await page.goto(BASE);
  await page.waitForSelector('[data-testid="entry-squat"]');
  assert.deepEqual((await names(page)).sort(), ["Arm wave", "Extra move", "Squat"].sort(), "the curated list, no test entries");
  assert.equal(await page.locator('[data-testid="entry-verify-2026-10-31t06-23-06z-317d3534"]').count(), 0, "negative: no verify entry");
  assert.equal(await page.locator('[data-testid="entry-arm-salute-8b6512a8"]').count(), 0, "negative: no arm salute");
  assert.equal(await page.locator("#build").isVisible(), false, "no build line");
  assert.equal(await page.locator('[data-testid="build-line"]').count(), 0);
  assert.match(await page.getByTestId("pitch").textContent(), /Record a movement once.*3D reference.*students/);
  assert.equal(await kindSwitchCount(page), 0, "negative: no Exercise / Dance / Rehab switch in the header");
  // the header height variable is measured, not a constant: scrolls stop right below the real header
  const headerPx = () => page.evaluate(() => ({ css: getComputedStyle(document.documentElement).getPropertyValue("--header-height").trim(), box: Math.round(document.querySelector("header.bar").getBoundingClientRect().height) }));
  const hh = await headerPx();
  assert.equal(hh.css, `${hh.box}px`, "--header-height is the measured header");
  assert.ok(hh.box < 80, `without the build line the header is short (${hh.box}px), not the 88px constant`);
  await page.screenshot({ path: path.join(out, "catalog-default.png") });
  // a search by name brings a hidden test entry back (the verify run finds its own entry)
  await page.getByTestId("search").fill("verify 2026");
  await page.waitForSelector('[data-testid="entry-verify-2026-10-31t06-23-06z-317d3534"]');
  ok("catalog: curated order, no test entries, no arm salute, no build line, picker visible");

  // ---- ?debug=1: build line and every entry
  await page.goto(`${BASE}?debug=1`);
  await page.waitForSelector('[data-testid="build-line"]');
  assert.match(await page.getByTestId("build-line").textContent(), /abc123def/);
  const hd = await headerPx();
  assert.equal(hd.css, `${hd.box}px`, "the measured header height follows the build line");
  assert.equal((await allIds(page)).length, 5);
  ok("?debug=1: the build line and every entry show");

  // ---- the submission profile: modes and sponsored challenges hidden, curated only, kept after a reload
  await page.goto(`${BASE}?profile=submission`);
  await page.waitForSelector('[data-testid="entry-squat"]');
  assert.deepEqual((await names(page)).sort(), ["Arm wave", "Squat"], "curated list only");
  assert.equal((await allIds(page)).length, 2, "curated list only");
  assert.equal(await kindSwitchCount(page), 0);
  await page.goto(`${BASE}#/follow/arm-wave`);
  await page.reload();
  await page.getByTestId("lang-picker-slot").waitFor({ state: "attached" });
  assert.equal(await page.getByTestId("follow-mode").isVisible(), false, "no mode picker on Follow");
  assert.equal(await page.getByTestId("mode-safety").count(), 0);
  await page.goto(`${BASE}?profile=default`);
  await page.waitForSelector('[data-testid="entry-squat"]');
  assert.equal(await kindSwitchCount(page), 0);
  ok("?profile=submission hides the mode picker and keeps to the curated list; ?profile=default restores the full list");
  await page.close();

  // ---- consent on Record and Follow, lang sent with the take
  page = await fresh();
  await page.goto(`${BASE}#/record`);
  assert.match(await page.getByTestId("consent-line").textContent(), /agree.*7 days.*delete/);
  await page.getByTestId("data-note").locator("summary").click();
  assert.match(await page.getByTestId("data-note").textContent(), /Meta's Model API/);
  await page.screenshot({ path: path.join(out, "record-consent.png"), fullPage: true });
  await page.goto(`${BASE}#/follow/arm-wave`);
  await page.getByTestId("consent-line").waitFor();
  assert.equal(await page.getByTestId("lang-picker-slot").count(), 1);
  ok("Record and Follow show the consent line and the data note; Follow holds the language slot");

  // ---- a Part 5 without --lang: the picker is not mounted and no language is sent
  await page.route("**/api/config", (route) => route.fulfill({ contentType: "application/json", body: JSON.stringify({
    base: "", limits: { max_seconds: 60, max_bytes: 95000000, recorder_bps: 2500000 }, phrasing: "template",
    part5: { lang: false, video: false, private: false } }) }));
  await page.goto(`${BASE}#/follow/squat`);
  await page.reload();
  await page.getByTestId("consent-line").waitFor();
  assert.equal(await page.getByTestId("lang-picker-slot").count(), 0);
  assert.equal(await page.getByLabel(/language/i).count(), 0, "nothing language-related shows");
  await page.unroute("**/api/config");
  ok("a pin without --lang shows no language picker");

  // ---- Delete this take on a result; the committed example has none
  await page.goto(`${BASE}#/result/rj1`);
  await page.getByTestId("delete-take-btn").waitFor({ timeout: 20000 });
  await page.getByTestId("delete-take-btn").click();
  await page.getByTestId("delete-keep").click();
  assert.equal(deletes.length, 0, "Keep it sends nothing");
  await page.getByTestId("delete-take-btn").click();
  await page.getByTestId("delete-confirm").click();
  await page.getByTestId("delete-done").waitFor();
  assert.deepEqual(deletes, [["POST", "rj1"]]);
  assert.match(await page.getByTestId("delete-done").textContent(), /video, the tracking and the analysis/);
  await page.screenshot({ path: path.join(out, "result-deleted.png") });
  await page.getByTestId("delete-take-btn").waitFor({ state: "detached", timeout: 1000 }).catch(() => {});
  assert.equal(await page.getByTestId("delete-take-btn").count(), 0);
  // ---- a person's page of a group take: the button says it deletes the whole group take, and asks first (TICKET-106 B1)
  await page.goto(`${BASE}#/result/gj1/0`);
  await page.getByTestId("delete-take-btn").waitFor({ timeout: 20000 });
  assert.equal((await page.getByTestId("delete-take-btn").textContent()).trim(), "Delete this group take");
  await page.getByTestId("delete-take-btn").click();
  assert.match(await page.getByTestId("delete-ask").textContent(), /everyone in it, not only this person/);
  await page.getByTestId("delete-keep").click();
  assert.equal(deletes.length, 1, "negative: Keep it sends nothing for the group");
  await page.getByTestId("delete-take-btn").click();
  await page.getByTestId("delete-confirm").click();
  await page.getByTestId("delete-done").waitFor();
  assert.deepEqual(deletes[1], ["POST", "gj1"]);
  assert.match(await page.getByTestId("delete-done").textContent(), /everyone in this group take/);
  await page.goto(`${BASE}#/result/fixture`);
  await page.waitForTimeout(1500);
  assert.equal(await page.getByTestId("delete-take-btn").count(), 0, "negative: the example result has no delete");
  ok("Delete this take: two taps, one POST, a confirmation; nothing on the example result");

  // ---- a trainer's recording (TICKET-111): from its job view, two ways to delete; the movement stays by default
  const before = deletes.length;
  await page.goto(`${BASE}#/job/tj1`);
  await page.getByTestId("delete-take-btn").waitFor({ timeout: 20000 });
  assert.equal((await page.getByTestId("delete-take-btn").textContent()).trim(), "Delete my recording");
  await page.getByTestId("delete-take-btn").click();
  const ask = await page.getByTestId("delete-ask").textContent();
  assert.match(ask, /stays in the catalog without sound/);
  assert.match(ask, /Delete the movement too removes it from the catalog/);
  assert.equal(await page.getByTestId("delete-confirm-entry").count(), 1);
  await page.getByTestId("delete-keep").click();
  assert.equal(deletes.length, before, "negative: Keep it sends nothing for the recording");
  await page.getByTestId("delete-take-btn").click();
  await page.getByTestId("delete-confirm").click();
  await page.getByTestId("delete-done").waitFor();
  assert.deepEqual(deletes.at(-1), ["POST", "tj1"]);
  assert.equal(deleteBodies.at(-1), "{}", "the default asks only for the recording and its files (an empty JSON object, no remove_entry)");
  assert.match(await page.getByTestId("delete-done").textContent(), /The movement stays in the catalog/);
  await page.goto(`${BASE}#/job/tj2`);
  await page.getByTestId("delete-take-btn").waitFor({ timeout: 20000 });
  await page.getByTestId("delete-take-btn").click();
  await page.getByTestId("delete-confirm-entry").click();
  await page.getByTestId("delete-done").waitFor();
  assert.deepEqual(JSON.parse(deleteBodies.at(-1)), { remove_entry: true });
  assert.match(await page.getByTestId("delete-done").textContent(), /stays in the catalog because/, "the server kept the movement and the page says so");
  ok("trainer job view: delete my recording keeps the movement; the second option removes it when it can");

  // ---- no kind bar on any page (TICKET-436): movement, follow, record and result pages keep their address; an old mode link opens
  for (const hash of ["#/watch/arm-wave", "#/follow/squat", "#/record", "#/result/rj1"]) {
    await page.goto(`${BASE}${hash}`);
    await page.waitForTimeout(600);
    assert.equal(await kindSwitchCount(page), 0, `${hash}: no kind switch`);
    assert.equal(new URL(page.url()).hash, hash, `${hash}: the page stays`);
  }
  await page.goto(`${BASE}#/?mode=dance`);
  await page.waitForSelector('[data-testid="entry-squat"]');
  assert.equal(await tid(page, "result-count").count(), 1, "witness: an old mode link opens the library");
  assert.equal(await page.locator('[data-testid="route-missing"]').count(), 0, "negative: not a page-not-found");
  ok("no kind bar: watch, follow, record and result keep their address; an old mode link opens the library");

  // ---- the judge URL: the first visit opens curated with the hero take and without test boards; ?profile=default shows all
  judge.on = true;
  page = await fresh();
  await page.goto(BASE);
  await page.waitForSelector('[data-testid="entry-squat"]');
  await page.waitForSelector('[data-testid="hero-link"]');
  assert.equal(await page.getByTestId("hero-link").getAttribute("href"), "#/result/rj1");
  assert.match(await page.getByTestId("hero-take").textContent(), /Scored 81 out of 100/);
  assert.equal(await kindSwitchCount(page), 0, "negative: the judge view has no mode picker");
  assert.equal(await page.locator('[data-testid="entry-extra-move"]').count(), 0, "negative: only the curated list");
  await page.goto(`${BASE}#/watch/arm-wave`);
  await page.waitForSelector('[data-testid="challenge-link-bReal"]');
  assert.equal(await page.locator('[data-testid="challenge-link-bVerify"]').count(), 0, "negative: no test board in the judge view");
  assert.ok(judge.boardQueries.some((q) => q.includes("view=judge")), "the judge view asks for view=judge");
  await page.goto(`${BASE}?profile=default#/watch/arm-wave`);
  await page.waitForSelector('[data-testid="challenge-link-bWave"]');
  assert.equal(await page.locator('[data-testid="challenge-link-bReal"]').count(), 1);
  assert.ok(judge.boardQueries.some((q) => !q.includes("view=judge")), "the full app asks for the plain list");
  const heroBefore = judge.heroAsked;
  await page.goto(`${BASE}#/`);
  await page.waitForSelector('[data-testid="entry-extra-move"]');
  assert.equal(await kindSwitchCount(page), 0, "?profile=default is kept; still no header switch");
  assert.equal(await page.locator('[data-testid="hero-link"]').count(), 0, "negative: no hero link in the full app");
  assert.equal(judge.heroAsked, heroBefore, "the full app does not ask for the hero");
  judge.on = false;
  ok("judge URL: curated with the hero take and no test boards by default; ?profile=default shows the full app");

  assert.deepEqual(errors, [], "no console errors");
  ok("no console errors");
} finally {
  await browser.close();
  server.close();
}
