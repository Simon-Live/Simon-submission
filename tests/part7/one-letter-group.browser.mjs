// One take, one letter L5 (docs/specs/one-letter.md) at 412x915: a group result where every take was capped says why.
// 44's dance run: every person capped by low_match. A fake API is installed with page.route on the people harness.
//   PLAYWRIGHT_DIR=<node_modules> /home/gingy/claude-template/scripts/with-browser-slot.sh node tests/part7/one-letter-group.browser.mjs
import assert from "node:assert/strict";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { serveRoot } from "./serve_static.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const req = createRequire(path.join(process.env.PLAYWRIGHT_DIR || path.resolve(here, "../../node_modules"), "x.js"));
const { chromium } = req("playwright");

const CAPPED = { letter: "F", figures: "59", caption: "score out of 100", unit: "score", capped: true, warning: ["low_match"], measure: 59 };
const CREDIT = { letter: "C", figures: "16,239", caption: "of 22,367", unit: "points", capped: false, warning: [], measure: 72.6 };
const row = (id, score, shown) => ({ id, label: `Dancer ${id}`, status_code: "ok", score, grade: "F", faults: [], shown });
const JOBS = {
  gcap: { id: "gcap", kind: "group", status: "done", result: { entry_id: "e1", trainer_id: 1, people: [row(2, 59, CAPPED), row(3, 59, CAPPED)] } },
  gmix: { id: "gmix", kind: "group", status: "done", result: { entry_id: "e1", trainer_id: 1, people: [row(2, 37, CREDIT), row(3, 59, CAPPED)] } },
};

const { server, port } = await serveRoot();
const browser = await chromium.launch();
const errors = [];
let passed = 0;
const ok = (name) => { passed++; console.log(`ok - ${name}`); };

async function open(job) {
  const ctx = await browser.newContext({ viewport: { width: 412, height: 915 }, deviceScaleFactor: 2, hasTouch: true });
  const page = await ctx.newPage();
  page.on("console", (m) => { if (m.type() === "error" && !/status of (404|422)/.test(m.text())) errors.push(`${job}: ${m.text()}`); });
  page.on("pageerror", (e) => errors.push(`${job}: ${e.message}`));
  await page.route("**/api/**", async (route) => {
    const p = new URL(route.request().url()).pathname.replace(/^.*\/api\//, "api/");
    const m = /^api\/jobs\/([^/]+)$/.exec(p);
    if (m && JOBS[m[1]]) return route.fulfill({ contentType: "application/json", body: JSON.stringify(JOBS[m[1]]) });
    if (p === "api/client-log") return route.fulfill({ status: 204, body: "" });
    return route.fulfill({ status: 404, contentType: "application/json", body: "{}" });
  });
  await page.goto(`http://127.0.0.1:${port}/tests/part7/harness/people.html?screen=board&job=${job}`);
  await page.waitForFunction(() => window.__ready === true);
  await page.getByTestId("group-board").waitFor();
  return page;
}
const tid = (page, id) => page.getByTestId(id);

try {
  let page = await open("gcap");
  assert.equal(await tid(page, "group-cap-note").textContent(), "Every take here is graded F at most: these takes do not closely match the trainer's movement.");
  assert.equal(await tid(page, "group-cap-2").textContent(), "Graded F at most: this take does not closely match the trainer's movement.");
  assert.equal(await tid(page, "group-cap-3").textContent(), "Graded F at most: this take does not closely match the trainer's movement.");
  assert.equal(await tid(page, "group-grade-2").textContent(), "F");
  ok("a group capped by low_match says why each grade is F, on each row and once for the page");
  await page.context().close();

  page = await open("gmix");
  assert.equal(await tid(page, "group-cap-note").count(), 0, "negative: no page line when one take was not capped");
  assert.equal(await tid(page, "group-cap-2").count(), 0, "negative: no cap line on the uncapped row");
  assert.equal(await tid(page, "group-cap-3").count(), 1);
  assert.deepEqual([await tid(page, "group-score-2").textContent(), await tid(page, "group-grade-2").textContent()], ["16,239", "C"]);
  ok("a mixed group: the cap line only on the capped row; the credit take shows its headline score");
  await page.context().close();
} finally {
  await browser.close();
  server.close();
}
if (errors.length) { console.error(errors.join("\n")); process.exit(1); }
console.log(`${passed} browser checks passed`);
