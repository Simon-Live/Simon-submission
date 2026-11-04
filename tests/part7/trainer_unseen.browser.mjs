// TICKET-116 (compare-view.md AC-C11): the trainer's joints Part 3 never saw are dimmed on the trainer's figure in the
// 3D compare and the results summary, whatever the follower shows. Run through scripts/with-browser-slot.sh.
import assert from "node:assert/strict";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { serveRoot } from "./serve_static.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const req = createRequire(path.join(process.env.PLAYWRIGHT_DIR || path.resolve(here, "../../node_modules"), "x.js"));
const { chromium } = req("playwright");

const { server, port } = await serveRoot();
const browser = await chromium.launch({ args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"] });
const errors = [];
let passed = 0;
const ok = (name) => { passed++; console.log(`ok - ${name}`); };

async function open(kase) {
  const ctx = await browser.newContext({ viewport: { width: 412, height: 915 }, reducedMotion: "reduce" });
  await ctx.addInitScript(() => { try { localStorage.setItem("simon.result.more", "open"); } catch { /* blocked */ } });   // the lean result keeps the worst moment card in "More"
  const page = await ctx.newPage();
  page.on("pageerror", (e) => errors.push(`${kase}: ${e.message}`));
  await page.goto(`http://127.0.0.1:${port}/tests/part7/harness/result.html?case=${kase}`);
  await page.waitForFunction(() => window.__ready === true);
  await page.waitForTimeout(400);
  return page;
}
const dimmed = async (page) => (await page.getByTestId("compare").getAttribute("data-joints-dimmed")).split(",");
const figDims = (page, who) => page.locator(`[data-testid="summary-worst"] .rs-fig-${who} .rs-fig-dim`).count();
const figLines = (page, who) => page.locator(`[data-testid="summary-worst"] .rs-fig-${who} line`).count();

try {
  const seated = await open("trainer-seated");
  assert.deepEqual(await dimmed(seated), ["4", "0"], "the trainer's 4 leg joints are dimmed, the follower's none");
  assert.deepEqual((await seated.getByTestId("compare").getAttribute("data-joints-drawn")).split(","), ["17", "17"], "dimmed, not dropped");
  assert.equal(await figDims(seated, "ref"), 4, "the summary's trainer figure dims the 4 leg bones");
  assert.equal(await figDims(seated, "you"), 0, "the follower's figure is unchanged");
  assert.ok((await figLines(seated, "ref")) > 4 && (await figLines(seated, "ref")) === (await figLines(seated, "you")), "both figures keep every bone");
  await seated.context().close();
  ok("seated trainer: legs dimmed on the trainer in the compare and the summary, follower unchanged");

  const standing = await open("trainer-standing");
  assert.deepEqual(await dimmed(standing), ["0", "0"]);
  assert.equal(await figDims(standing, "ref"), 0);
  assert.equal(await figDims(standing, "you"), 0);
  await standing.context().close();
  ok("standing trainer with full visibility: nothing dimmed");

  const plain = await open("ok");
  assert.deepEqual(await dimmed(plain), ["0", "0"], "no visibility data (a job without a skeleton file) dims nothing");
  await plain.context().close();
  ok("no visibility data: nothing dimmed");

  assert.deepEqual(errors, []);
  ok("no page errors");
  console.log(`# pass ${passed}`);
} catch (err) {
  console.error(err);
  process.exitCode = 1;
} finally {
  await browser.close();
  server.close();
}
