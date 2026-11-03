// Browser drive of the Impact and architecture pages on the REAL Part 7 app (tests/part7/serve_impact.py), at 412 and
// 1440 px (docs/specs/impact-page.md AC-I1, AC-I4, AC-A2). Witness 1 is the page; witness 2 is the server's own
// api/impact answer. Negative: no card shows the QA take, the committed example or a placeholder take.
//   PLAYWRIGHT_DIR=<node_modules> /home/gingy/claude-template/scripts/with-browser-slot.sh node tests/part7/impact.browser.mjs [shots dir]
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import fs from "node:fs";
import net from "node:net";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const req = createRequire(path.join(process.env.PLAYWRIGHT_DIR || path.resolve(here, "../../node_modules"), "x.js"));
const { chromium } = req("playwright");
const AXE = fs.readFileSync(req.resolve("axe-core/axe.min.js"), "utf8");
const shots = process.argv[2] || null;
if (shots) fs.mkdirSync(shots, { recursive: true });

const port = await new Promise((resolve) => {
  const probe = net.createServer().listen(0, "127.0.0.1", () => { const p = probe.address().port; probe.close(() => resolve(p)); });
});
const base = `http://127.0.0.1:${port}/simon-part-7/`;
const server = spawn("python3", [path.join(here, "serve_impact.py"), String(port)], { stdio: ["ignore", "pipe", "inherit"], env: { ...process.env, SIMON7_P2_WARM_WORKERS: "0" } }); // no warm GPU worker; stopped by its pid below
process.on("exit", () => server.kill());
const ids = await new Promise((resolve, reject) => {
  let out = "";
  server.stdout.on("data", (d) => { out += d; const m = out.match(/ready (\{.*\})/); if (m) resolve(JSON.parse(m[1])); });
  server.on("exit", (c) => reject(new Error(`serve_impact.py exited ${c}`)));
});

const api = await (await fetch(`${base}api/impact`)).json(); // witness 2: what the server says
const byPersona = Object.fromEntries(api.personas.map((p) => [p.persona, p]));
assert.equal(byPersona.seated.take.job_id, ids.seated);
assert.equal(byPersona["home-rehab"].take.job_id, ids["home-rehab"]);
assert.deepEqual([byPersona["remote-class"].take, byPersona["remote-class"].missing], [null, "not_found"], "the QA take is refused by the server");
assert.equal(byPersona.bodies.missing, "not_listed");

const browser = await chromium.launch({ args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
const failures = [];
let passed = 0;
const ok = (name) => { passed++; console.log(`ok - ${name}`); };

async function audit(page, who, scope) {
  await page.evaluate(AXE);
  const res = await page.evaluate(() => axe.run(document, { resultTypes: ["violations"], rules: { region: { enabled: false } } }));
  for (const v of res.violations.filter((x) => ["serious", "critical"].includes(x.impact))) {
    failures.push(`${who}: axe ${v.id} (${v.impact}) ${v.nodes.slice(0, 3).map((n) => n.target.join(" ")).join(" | ")}`);
  }
  const geo = await page.evaluate((scope) => ({
    small: [...document.querySelectorAll(`${scope} a[href], ${scope} button`)].filter((e) => {
      const r = e.getBoundingClientRect(); return r.width > 0 && (r.height < 43.5 || r.width < 43.5);
    }).map((e) => `${e.dataset.testid || e.textContent.trim().slice(0, 24)} ${Math.round(e.getBoundingClientRect().width)}x${Math.round(e.getBoundingClientRect().height)}`),
    overflow: document.documentElement.scrollWidth - innerWidth,
  }), scope);
  for (const s of geo.small) failures.push(`${who}: small target ${s}`);
  if (geo.overflow > 0) failures.push(`${who}: sideways overflow ${geo.overflow}px`);
}

try {
  for (const [label, width, height] of [["phone", 412, 915], ["desktop", 1440, 900]]) {
    const ctx = await browser.newContext({ viewport: { width, height }, reducedMotion: "reduce" });
    ctx.setDefaultTimeout(15000);
    const page = await ctx.newPage();
    const errors = [];
    page.on("pageerror", (e) => errors.push(e.message));

    await page.goto(`${base}?profile=submission#/`);
    await page.getByTestId("impact-link").waitFor();
    assert.equal(await page.getByTestId("architecture-link").count(), 1, `${label}: Home links the architecture page`);
    await page.getByTestId("impact-link").click();
    await page.getByTestId("impact").waitFor();
    assert.equal(await page.locator("article.imp-card").count(), 4, `${label}: four persona cards`);
    for (const persona of ["seated", "home-rehab"]) {
      const card = page.getByTestId(`impact-card-${persona}`);
      assert.equal(await card.getAttribute("data-has-take"), "true", `${label}: ${persona} has its take`);
      assert.equal(await card.getByTestId("impact-open").getAttribute("href"), `#/result/${ids[persona]}`);
      assert.match(await card.getByTestId("impact-clip").innerText(), /Clip: Pexels License, source/);
      assert.equal(await card.getByTestId("impact-clip-source").getAttribute("href"), "https://www.pexels.com/video/test-clip/");
    }
    for (const persona of ["remote-class", "bodies"]) {
      const card = page.getByTestId(`impact-card-${persona}`);
      assert.equal(await card.getByTestId("impact-open").count(), 0, `${label}: negative: ${persona} has no take link`);
      assert.equal(await card.getByTestId("impact-empty").count(), 1, `${label}: ${persona} says why it has none`);
    }
    const hrefs = await page.locator("[data-testid=impact] a").evaluateAll((as) => as.map((a) => a.getAttribute("href")));
    assert.ok(!hrefs.some((h) => h.includes(ids.qa) || h.includes("fixture")), `${label}: negative: no link to the QA take or the committed example`);
    assert.doesNotMatch(await page.getByTestId("impact").innerText(), /qa-|fixture|Scored 99/i, `${label}: negative: no QA take on the page`);
    assert.equal(await page.getByTestId("impact-need-source").count(), 2, `${label}: two sourced need figures`);
    await audit(page, `${label} impact`, "[data-testid=impact]");
    if (shots) await page.screenshot({ path: path.join(shots, `impact-${width}.png`), fullPage: true });

    await page.getByTestId("impact-card-seated").getByTestId("impact-open").click();
    await page.waitForFunction((id) => location.hash === `#/result/${id}`, ids.seated);
    ok(`${label}: Impact page, 4 cards, 2 real takes, QA take refused, take link opens its result`);

    await page.goto(`${base}?profile=submission#/architecture`);
    await page.getByTestId("architecture").waitFor();
    assert.equal(await page.getByTestId("arch-figure").count(), 3, `${label}: three diagrams`);
    await page.waitForFunction(() => document.querySelectorAll("[data-testid=arch-slot][data-drawn=true] svg").length === 3, null, { timeout: 30000 });
    assert.equal(await page.getByTestId("arch-failed").count(), 0, `${label}: negative: no diagram failed to draw`);
    assert.equal(await page.locator("[data-testid=arch-slot] svg[role=img][aria-label]").count(), 3, `${label}: each drawing is a labelled image`);
    await audit(page, `${label} architecture`, "[data-testid=architecture]");
    if (shots) await page.screenshot({ path: path.join(shots, `architecture-${width}.png`), fullPage: true });
    if (errors.length) failures.push(`${label}: page errors ${errors.join("; ")}`);
    ok(`${label}: architecture page, three Mermaid drawings from docs/ARCHITECTURE.md`);
    await ctx.close();
  }
} finally {
  await browser.close();
  server.kill();
}
if (failures.length) { console.error(failures.join("\n")); process.exit(1); }
console.log(`${passed} passed`);
