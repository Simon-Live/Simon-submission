// Browser checks for the home library: search, filters, sort, pages, the hash address, the states and the layout at seven
// widths and a short landscape phone (docs/specs/home-browse.md). The page is the real app; the API is a small fake.
//   PLAYWRIGHT_DIR=/path/to/node_modules/playwright scripts/with-browser-slot.sh node tests/part7/home-browse.browser.mjs [shots-dir]
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const WEB = path.resolve(here, "../../web");
const out = path.resolve(process.argv[2] || path.join(here, "screens"));
fs.mkdirSync(out, { recursive: true });
const { chromium } = createRequire(import.meta.url)(process.env.PLAYWRIGHT_DIR || "playwright");
const TYPES = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".svg": "image/svg+xml" };

const LONG = "A very long movement title that keeps going with Supercalifragilisticexpialidocious_Pneumonoultramicroscopicsilicovolcanoconiosis and more words";
const cfg = { n: 40, search: true, fail: 0, delay: 0, mineSignedIn: false, calls: [] };
const entries = () => Array.from({ length: cfg.n }, (_, i) => ({
  id: `m${i}`, name: i === 3 ? LONG : i % 7 === 0 ? `Squat variation ${i}` : `Movement ${i}`, category: i % 3 === 0 ? "dance" : "exercise",
  duration_ms: [12000, 30000, 120000][i % 3], video_uri: i % 2 ? "video.mp4" : null, animation: "animation.json", files_source: "import", created_at: new Date(2026, 0, 1 + (i % 28)).toISOString(), rehab: i % 5 === 0,
}));
const json = (res, body, status = 200) => { res.writeHead(status, { "content-type": "application/json" }); res.end(JSON.stringify(body)); };
const band = (ms) => (ms < 15000 ? "short" : ms > 45000 ? "long" : "medium");
function search(url) {
  const q = (url.searchParams.get("q") || "").toLowerCase();
  const list = (k) => (url.searchParams.get(k) || "").split(",").filter(Boolean);
  const type = list("type"); const has = list("has"); const duration = url.searchParams.get("duration");
  const base = entries().filter((e) => e.name.toLowerCase().includes(q));
  const isType = (e, t) => (t === "rehab" ? e.rehab : e.category === t);
  let found = base.filter((e) => (!type.length || type.some((t) => isType(e, t))) && (!duration || band(e.duration_ms) === duration)
    && has.every((k) => (k === "video" ? e.video_uri : k === "model" ? e.animation : false)) && (url.searchParams.get("mine") !== "1" || e.id.endsWith("0")));
  const sort = url.searchParams.get("sort");
  if (sort === "title") found = [...found].sort((a, b) => a.name.localeCompare(b.name));
  if (sort === "duration") found = [...found].sort((a, b) => a.duration_ms - b.duration_ms);
  if (sort === "newest") found = [...found].sort((a, b) => b.created_at.localeCompare(a.created_at));
  const per = Number(url.searchParams.get("per_page")) || 12;
  const pages = Math.max(1, Math.ceil(found.length / per));
  const page = Math.min(Number(url.searchParams.get("page")) || 1, pages);
  return {
    ok: true, entries: found.slice((page - 1) * per, page * per), total: found.length, page, per_page: per, pages,
    facets: {
      type: Object.fromEntries(["exercise", "dance", "rehab"].map((t) => [t, base.filter((e) => isType(e, t)).length])),
      duration: Object.fromEntries(["short", "medium", "long"].map((d) => [d, base.filter((e) => band(e.duration_ms) === d).length])),
      has: { video: base.filter((e) => e.video_uri).length, model: base.length },
    },
  };
}

const server = http.createServer((req, res) => {
  const url = new URL(req.url, "http://x");
  const p = decodeURIComponent(url.pathname);
  req.resume();
  req.on("end", async () => {
    if (p === "/api/config") return json(res, { limits: { max_seconds: 60, max_bytes: 95000000, recorder_bps: 2500000 }, part5: {} });
    if (p === "/api/client-log") return json(res, { ok: true });
    if (p === "/api/policy") return json(res, { prod: false, switches: { face_copy: true, rehab: true, trainer_public: true, prize_boards: true, byok_ranked: true, mms_tts: true, muse: true }, phrasing_live: false, age: { minimum: 13, adult: 18 }, consent: { required: false, version: null, items: [], header: "X-Simon-Consent" } });
    if (p === "/api/version") return json(res, { short: "abc123def", started_at: "2026-10-31T12:00:00Z", parts: {} });
    if (p === "/api/labels") return json(res, Object.fromEntries(entries().filter((e) => e.rehab).map((e) => [e.id, { tags: ["rehab"], notes: "" }])));
    if (p === "/api/auth/me") return cfg.mineSignedIn ? json(res, { available: true, signed_in: true, user_id: "u1", email: "a@b.c" }) : json(res, { error: "no" }, 401);
    if (p === "/api/challenges" || /^\/api\/(boards|movements\/[^/]+\/boards)$/.test(p)) return json(res, { boards: [], challenges: [] });
    if (p === "/api/catalog/search") {
      cfg.calls.push(url.search);
      if (cfg.delay) await new Promise((r) => setTimeout(r, cfg.delay));
      if (!cfg.search) return json(res, { error: "no" }, 404);
      if (cfg.fail) { cfg.fail -= 1; return json(res, { error: "The search is down." }, 503); }
      return json(res, search(url));
    }
    if (p === "/catalog/api/entries") return json(res, { entries: entries() });
    if (p.startsWith("/api/") || p.startsWith("/catalog/")) return json(res, { error: "no" }, 404);
    const rel = p === "/" ? "index.html" : p.replace(/^\//, "");
    const file = path.resolve(WEB, rel);
    if (!file.startsWith(WEB) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) { res.writeHead(404).end("no"); return; }
    res.writeHead(200, { "content-type": TYPES[path.extname(file)] || "application/octet-stream" });
    res.end(fs.readFileSync(file));
  });
});
await new Promise((r) => server.listen(0, "127.0.0.1", r));
const BASE = `http://127.0.0.1:${server.address().port}/`;
const browser = await chromium.launch();
const errors = [];
const ok = (msg) => console.log(`ok  ${msg}`);
const open = async (size, hash = "", n = 40) => {
  cfg.n = n; cfg.calls = [];
  const ctx = await browser.newContext({ viewport: size, deviceScaleFactor: 1, hasTouch: size.width < 900 });
  const page = await ctx.newPage();
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("console", (m) => { if (m.type() === "error" && !/Failed to load resource/.test(m.text())) errors.push(m.text()); });
  await page.goto(`${BASE}${hash}`);
  await page.waitForFunction(() => !document.querySelector(".splash"), null, { timeout: 15000 }); // the brand splash plays in full, then the screen is measured
  await page.waitForFunction(() => document.querySelector('[data-testid="result-count"]')?.textContent &&!/Loading/.test(document.querySelector('[data-testid="result-count"]').textContent));
  return page;
};
const tid = (page, id) => page.getByTestId(id);
const hashOf = (page) => page.evaluate(() => location.hash);
const overflow = (page) => page.evaluate(() => ({ doc: document.documentElement.scrollWidth - document.documentElement.clientWidth, body: document.body.scrollWidth - document.documentElement.clientWidth }));
const wide = (page) => page.evaluate(() => [...document.querySelectorAll("html, body, body *")].filter((e) => e.scrollWidth > e.clientWidth + 1 && e.clientWidth > 0).map((e) => `${e.tagName}.${e.className} sw${e.scrollWidth} cw${e.clientWidth}`).slice(0, 8).concat([...document.querySelectorAll("html, body, body *")].filter((e) => e.getBoundingClientRect().right > document.documentElement.clientWidth + 0.5)
  .slice(0, 8).map((e) => `${e.tagName}#${e.id}.${e.className} ${Math.round(e.getBoundingClientRect().right)}`)));
const culprit = (page) => page.evaluate(() => {
  const over = () => document.documentElement.scrollWidth - document.documentElement.clientWidth;
  const m = document.querySelector("main"); const cs = getComputedStyle(m);
  const info = [`main ${Math.round(m.getBoundingClientRect().left)}..${Math.round(m.getBoundingClientRect().right)} pad ${cs.paddingLeft}/${cs.paddingRight} ov ${cs.overflowX} disp ${cs.display}`, ...[...m.querySelectorAll(".screen, .bw-layout, .bw-results, .bw-results-body, .lib-grid, .bw-head, .bw-pager")].map((e) => `${e.className} ${Math.round(e.getBoundingClientRect().left)}..${Math.round(e.getBoundingClientRect().right)} sw${e.scrollWidth}`)];
  return info.concat([...document.querySelectorAll("main *")].filter((e) => { const d = e.style.display; e.style.display = "none"; const fixed = over() <= 0; e.style.display = d; return fixed; })
    .slice(0, 4).map((e) => `${e.tagName}.${e.className} ${Math.round(e.getBoundingClientRect().left)}..${Math.round(e.getBoundingClientRect().right)}`));
});
const settle = (page) => page.waitForFunction(() => document.querySelector(".bw")?.getAttribute("aria-busy") === "false");
/** Visible interactive controls in `scope` that intersect another, by rectangle. */
const overlaps = (page, scope) => page.evaluate((sel) => {
  const root = document.querySelector(sel);
  const els = [...root.querySelectorAll("a[href], button, input, select")].filter((e) => e.offsetParent !== null && e.getBoundingClientRect().width > 0)
    .filter((e) => { const r = e.getBoundingClientRect(); const top = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2); return !top || e.contains(top) || top.contains(e) || e.closest("label")?.contains(top); }); // scrolled out of its box: not on screen
  const hits = [];
  els.forEach((a, i) => els.slice(i + 1).forEach((b) => {
    if (a.contains(b) || b.contains(a)) return;
    const r = a.getBoundingClientRect(); const s = b.getBoundingClientRect();
    const w = Math.min(r.right, s.right) - Math.max(r.left, s.left); const hgt = Math.min(r.bottom, s.bottom) - Math.max(r.top, s.top);
    if (w > 1 && hgt > 1) hits.push(`${a.dataset.testid || a.textContent} x ${b.dataset.testid || b.textContent}`);
  }));
  return hits;
}, scope);
const small = (page, scope) => page.evaluate((sel) => [...document.querySelector(sel).querySelectorAll("a[href]:not([tabindex='-1']), button, select, input:not([type=checkbox]):not([type=radio])")]
  .filter((e) => e.offsetParent !== null && !e.closest("[aria-hidden=true]") && (e.getBoundingClientRect().height < 43.5 || e.getBoundingClientRect().width < 43.5) && !e.classList.contains("lib-use") && !e.classList.contains("lib-name"))
  .map((e) => `${e.dataset.testid || e.textContent} ${Math.round(e.getBoundingClientRect().width)}x${Math.round(e.getBoundingClientRect().height)}`), scope);

const WIDTHS = [[320, 640], [375, 667], [412, 915], [768, 1024], [1024, 768], [1280, 800], [1440, 900], [844, 390]];
const table = [];

try {
  // ---- layout at every width: home, the filters, a deep page of 200
  for (const [width, height] of WIDTHS) {
    const row = { width: `${width}x${height}` };
    let page = await open({ width, height }, "", 40);
    row.home = (await overflow(page)).doc <= 0 ? "fits" : `OVERFLOW ${JSON.stringify(await overflow(page))}`;
    assert.ok((await overflow(page)).doc <= 0 && (await overflow(page)).body <= 0, `${width}: no sideways scroll on home ${JSON.stringify(await wide(page))} ${JSON.stringify(await overflow(page))} culprit ${JSON.stringify(await culprit(page))}`);
    assert.deepEqual(await overlaps(page, ".bw"), [], `${width}: no controls overlap on home`);
    const field = await page.evaluate(() => { const i = document.querySelector('[data-testid="search"]'); const main = document.querySelector("main"); const c = document.createElement("canvas").getContext("2d"); const cs = getComputedStyle(i); c.font = `${cs.fontSize} ${cs.fontFamily}`; return { w: i.getBoundingClientRect().width, main: main.clientWidth, text: c.measureText(i.placeholder).width, pad: parseFloat(cs.paddingLeft) + parseFloat(cs.paddingRight) }; });
    assert.ok(field.w >= field.main - 60 && field.text + field.pad <= field.w, `${width}: the search box spans the column and shows its whole placeholder (${JSON.stringify(field)})`);
    await page.screenshot({ path: path.join(out, `home-${width}x${height}.png`), fullPage: false });
    if (width < 900) {
      await tid(page, "filters-open").click();
      await tid(page, "opt-type-dance").waitFor();
      const box = await tid(page, "filters").boundingBox();
      assert.ok(box.x >= -0.5 && box.x + box.width <= width + 0.5 && box.y >= -0.5 && box.y + box.height <= height + 0.5, `${width}: the sheet sits inside the screen (${JSON.stringify(box)})`);
      assert.deepEqual(await overlaps(page, '[data-testid="filters"]'), [], `${width}: no sheet control overlaps`);
      assert.equal(await tid(page, "filters").getAttribute("role"), "dialog");
      await tid(page, "opt-type-dance").check();
      await settle(page);
      await page.screenshot({ path: path.join(out, `sheet-${width}x${height}.png`) });
      await tid(page, "filters-done").click();
      assert.equal(await page.evaluate(() => document.activeElement?.dataset.testid), "filters-open", `${width}: focus returns to the Filters button`);
      assert.equal(await tid(page, "filters-open").textContent(), "Filters (1)");
      row.sheet = "usable";
    } else {
      assert.ok(await tid(page, "filters").isVisible(), `${width}: the filters are a visible column`);
      await tid(page, "opt-type-dance").check();
      await settle(page);
      row.sheet = "column";
    }
    assert.deepEqual(await small(page, ".bw"), [], `${width}: every control is 44 px`);
    await page.context().close();

    page = await open({ width, height }, "#/?page=100", 2400);
    await settle(page);
    assert.equal(await tid(page, "page-100").getAttribute("aria-current"), "page");
    const pager = await page.evaluate(() => { const n = document.querySelector(".bw-pages"); return { sw: n.scrollWidth, cw: n.clientWidth }; });
    assert.ok(pager.sw <= pager.cw, `${width}: the pager fits (${JSON.stringify(pager)})`);
    assert.deepEqual(await overlaps(page, '[data-testid="pager"]'), [], `${width}: no pager control overlaps`);
    assert.ok((await overflow(page)).doc <= 0, `${width}: no sideways scroll on page 100 of 200`);
    await tid(page, "pager").scrollIntoViewIfNeeded();
    await page.screenshot({ path: path.join(out, `pager-${width}x${height}.png`) });
    row.pager = "fits";
    table.push(row);
    await page.context().close();
  }
  ok("layout at 320, 375, 412, 768, 1024, 1280, 1440 and 844x390");

  // ---- behaviour at a phone width
  const phone = { width: 412, height: 915 };
  let page = await open(phone, "", 40);
  assert.equal(await tid(page, "result-count").textContent(), "40 movements");
  assert.equal(await tid(page, "result-count").getAttribute("aria-live"), "polite");
  assert.equal(await page.locator(".lib-card").count(), 12, "12 cards a page");
  assert.equal(await tid(page, "page-1").getAttribute("aria-current"), "page");
  assert.equal(await page.locator('[aria-current="page"]').count(), 1);
  assert.equal(await tid(page, "page-prev-off").getAttribute("aria-disabled"), "true", "Previous is off on page 1");
  ok("first page: count line, 12 cards, page 1 current, Previous off");

  // search: debounced, no reload, URL, clear button, Enter
  await page.evaluate(() => { window.__same = true; });
  cfg.calls = [];
  await tid(page, "search").pressSequentially("squat", { delay: 30 });
  await page.waitForFunction(() => document.querySelector('[data-testid="result-count"]').textContent === "6 movements");
  assert.equal(await page.evaluate(() => window.__same), true, "no full reload");
  assert.ok(cfg.calls.length <= 2, `debounced (${cfg.calls.length} calls for 5 keys)`);
  assert.equal(await hashOf(page), "#/?q=squat");
  assert.equal(await page.locator('[data-testid="chip-q-x"]').count(), 1);
  assert.equal(await page.locator(".bw").getAttribute("data-browsing"), "");
  assert.equal(await page.locator(".lib-pitch").isVisible(), false, "the pitch steps aside while searching");
  await tid(page, "search-clear").click();
  await page.waitForFunction(() => document.querySelector('[data-testid="result-count"]').textContent === "40 movements");
  assert.equal(await hashOf(page), "#/");
  assert.equal(await page.evaluate(() => document.activeElement?.dataset.testid), "search", "Clear puts focus back in the box");
  assert.equal(await page.locator(".lib-pitch").isVisible(), true, "and the pitch comes back");
  await tid(page, "search").fill("movement 1");
  await tid(page, "search").press("Enter");
  await page.waitForFunction(() => document.querySelector('[data-testid="result-count"]').textContent === "10 movements");
  ok("search: debounced, no reload, URL, clear, Enter");

  // filters, chips, page reset, back and forward, refresh
  await tid(page, "search").fill("");
  await tid(page, "search").press("Enter");
  await settle(page);
  await tid(page, "page-3").click();
  await page.waitForFunction(() => location.hash === "#/?page=3");
  await page.waitForFunction(() => document.activeElement?.id === "bw-results-title", null, { timeout: 5000 }); // focus lands on the results heading after a page change
  assert.equal(await tid(page, "page-prev").getAttribute("rel"), "prev");
  await tid(page, "filters-open").click();
  await tid(page, "opt-type-dance").check();
  await page.waitForFunction(() => location.hash === "#/?type=dance");
  await tid(page, "opt-has-video").check();
  await tid(page, "opt-duration-short").check();
  await settle(page);
  assert.equal(await hashOf(page), "#/?type=dance&duration=short&has=video", "a change of any filter resets to page 1");
  await page.keyboard.press("Escape");
  assert.equal(await page.evaluate(() => document.activeElement?.dataset.testid), "filters-open", "Escape closes the sheet and returns focus");
  assert.equal(await page.locator(".bw-chip").count(), 3);
  assert.equal(await page.locator('[data-testid="chips-clear"]').count(), 1);
  await page.goBack();
  await page.waitForFunction(() => location.hash === "#/?type=dance&has=video");
  await settle(page);
  assert.equal(await page.locator(".bw-chip").count(), 2, "Back restores the earlier filters");
  await page.goForward();
  await page.waitForFunction(() => location.hash.includes("duration=short"));
  await page.reload();
  await settle(page);
  assert.equal(await page.locator(".bw-chip").count(), 3, "refresh restores the filters");
  await tid(page, "chip-duration-short").click();
  await settle(page);
  assert.equal(await hashOf(page), "#/?type=dance&has=video", "a chip removes its filter");
  await tid(page, "chips-clear").click();
  await settle(page);
  assert.equal(await hashOf(page), "#/");
  ok("filters: chips, page reset, back, forward, refresh, Clear all");

  // sort and per page
  await tid(page, "sort").selectOption("title");
  await settle(page);
  assert.equal(await hashOf(page), "#/?sort=title");
  assert.equal(await page.locator(".lib-name").first().textContent(), "A very long movement title that keeps going with Supercalifragilisticexpialidocious_Pneumonoultramicroscopicsilicovolcanoconiosis and more words");
  await tid(page, "per-page").selectOption("24");
  await settle(page);
  assert.equal(await hashOf(page), "#/?sort=title&per_page=24");
  assert.equal(await page.locator(".lib-card").count(), 24);
  assert.equal(await page.locator("[data-page]").count() > 0, true);
  await page.close();
  ok("sort and page size");

  // a page past the end corrects itself; junk in the address is ignored
  page = await open(phone, "#/?page=99&type=bogus&sort=nope&per_page=7", 40);
  assert.equal(await hashOf(page), "#/?page=4", `corrected (${await hashOf(page)})`);
  assert.equal(await tid(page, "page-4").getAttribute("aria-current"), "page");
  assert.equal(await tid(page, "page-next-off").getAttribute("aria-disabled"), "true");
  await page.goto(`${BASE}#/?q=%zz`);
  await page.waitForSelector('[data-testid="result-count"]');
  await page.close();
  ok("page past the end, junk and malformed escapes");

  // 0 results, 1 page, filter that has no matches
  page = await open(phone, "#/?q=zzzz", 40);
  assert.equal(await tid(page, "result-count").textContent(), "No movements");
  assert.match(await tid(page, "no-match").textContent(), /Nothing matches "zzzz"/);
  assert.equal(await page.locator("[data-testid=pager] nav").count(), 0, "no page numbers on an empty list");
  await page.screenshot({ path: path.join(out, "empty-412.png") });
  await tid(page, "clear-filters").click();
  await page.waitForFunction(() => document.querySelector('[data-testid="result-count"]').textContent === "40 movements");
  assert.equal(await hashOf(page), "#/");
  await page.close();
  page = await open(phone, "", 5);
  assert.equal(await page.locator("[data-testid=pager] nav").count(), 0, "one page: no page numbers");
  assert.equal(await page.locator("[data-testid=pager] [data-testid=per-page]").count(), 1, "the page size stays");
  await page.close();
  page = await open(phone, "", 0);
  assert.equal(await tid(page, "empty").count(), 1, "an empty library says so and offers Record");
  assert.equal(await tid(page, "empty-record").count(), 1);
  await page.close();
  ok("0 results, 1 page, empty library");

  // error with Try again, and loading skeleton
  cfg.n = 40; cfg.fail = 1;
  const ctx = await browser.newContext({ viewport: phone });
  page = await ctx.newPage();
  await page.goto(`${BASE}#/`);
  await tid(page, "load-error").waitFor();
  assert.match(await tid(page, "load-error").textContent(), /The catalog did not load: The search is down\./);
  await page.screenshot({ path: path.join(out, "error-412.png") });
  await tid(page, "retry").click();
  await page.waitForFunction(() => document.querySelector('[data-testid="result-count"]').textContent === "40 movements");
  assert.equal(await tid(page, "load-error").count(), 0);
  cfg.delay = 600;
  await tid(page, "page-2").click();
  await page.waitForTimeout(150);
  assert.equal(await page.locator(".bw-results-body.is-stale").count(), 1, "later loads keep the old cards (no jump)");
  cfg.delay = 0;
  await ctx.close();
  cfg.delay = 700;
  const slow = await browser.newContext({ viewport: phone });
  page = await slow.newPage();
  await page.goto(`${BASE}#/`);
  await tid(page, "skeleton").waitFor();
  const before = await page.evaluate(() => document.querySelector(".bw-results-body").getBoundingClientRect().height);
  await page.screenshot({ path: path.join(out, "loading-412.png") });
  await page.waitForFunction(() => document.querySelector('[data-testid="result-count"]').textContent === "40 movements");
  cfg.delay = 0;
  const after = await page.evaluate(() => document.querySelector(".bw-results-body").getBoundingClientRect().height);
  assert.ok(Math.abs(after - before) / after < 0.35, `skeleton height ${before} close to loaded ${after}`);
  await slow.close();
  ok("error with Try again, loading skeleton, stale results kept");

  // a server with no search: the same screen from the whole catalog, with only what it can back
  cfg.search = false;
  page = await open(phone, "#/?type=dance&sort=title", 40);
  assert.equal(await tid(page, "result-count").textContent(), "14 movements");
  assert.equal(await page.locator('[data-testid="opt-has-board"]').count(), 0, "no leaderboard filter without a server that counts it");
  assert.equal(await page.locator('#bw-sort option[value="popular"]').count(), 0, "no popularity sort");
  await page.close();
  cfg.search = true;
  ok("fallback without api/catalog/search");

  // signed in: Only my movements
  cfg.mineSignedIn = true;
  page = await open({ width: 1280, height: 800 }, "#/?mine=1", 40);
  assert.equal(await tid(page, "result-count").textContent(), "4 movements");
  assert.equal(await tid(page, "opt-mine-1").isChecked(), true);
  await page.screenshot({ path: path.join(out, "signed-in-1280.png") });
  await page.close();
  cfg.mineSignedIn = false;
  page = await open({ width: 1280, height: 800 }, "#/?mine=1", 40);
  assert.equal(await page.locator('[data-testid="opt-mine-1"]').count(), 0, "signed out: no Only my movements");
  assert.equal(await tid(page, "result-count").textContent(), "40 movements");
  await page.close();
  ok("signed in and signed out");

  // keyboard: Tab reaches search, sort, a filter, the pager
  page = await open({ width: 1280, height: 800 }, "", 40);
  const seen = new Set();
  for (let i = 0; i < 60; i++) { await page.keyboard.press("Tab"); const t = await page.evaluate(() => document.activeElement?.dataset.testid || document.activeElement?.id || ""); if (t) seen.add(t); }
  for (const want of ["search", "opt-type-dance", "sort", "page-2", "per-page"]) assert.ok(seen.has(want), `Tab reaches ${want}`);
  const ring = await page.evaluate(() => { document.querySelector('[data-testid="sort"]').focus(); const s = getComputedStyle(document.activeElement); return s.outlineStyle !== "none" || s.boxShadow !== "none"; });
  assert.ok(ring, "a focused control shows a ring");
  await page.close();
  ok("keyboard reaches every control, visible focus");

  assert.deepEqual(errors, [], "no page errors");
  console.log("\nwidth       home   sheet    pager");
  for (const r of table) console.log(`${r.width.padEnd(11)} ${r.home.padEnd(6)} ${r.sheet.padEnd(8)} ${r.pager}`);
  console.log("\nhome-browse browser checks passed");
} finally {
  await browser.close();
  server.close();
}
