// Release 14, in a real browser (docs/specs/result-release-14.md): (1) the AI label sits on an insight row whose line the
// model worded and on no row of fixed text; (2) a tapped row puts its own cue on the stage caption.
// Run: PLAYWRIGHT_DIR=<node_modules> scripts/with-browser-slot.sh node tests/part7/result-label-caption.browser.mjs
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
try {
  const ctx = await browser.newContext({ viewport: { width: 412, height: 915 }, hasTouch: true, reducedMotion: "reduce" });
  await ctx.addInitScript(() => { try { localStorage.setItem("simon.stage.breakdown", "open"); } catch { /* blocked */ } });
  const page = await ctx.newPage();
  await page.goto(`http://127.0.0.1:${port}/tests/part7/harness/result.html?case=insights-live`);
  await page.waitForFunction(() => window.__ready === true);
  await page.waitForTimeout(500);
  const tid = (id) => page.getByTestId(id);

  // the label: on the insight the model worded, with its sentence; not on the fixed-text rows
  await tid("insight-1-ai").waitFor();
  assert.equal(await tid("insight-1-ai").textContent(), "Worded by AI");
  assert.match(await tid("insight-1-live").textContent(), /far more than the trainer/);
  assert.equal(await tid("insight-2-ai").count(), 0, "negative: a fixed-text row has no label");
  assert.equal(await tid("insight-0-ai").count(), 0, "negative: an insight with no fault has no label");
  assert.equal(await page.locator(".sr-ai").count(), 1, "one model-worded line, one label");

  // R14b R6: Part 5's retimed words, with the rep count, stay on the row; B2: a persistent note says some lines are AI words
  assert.match(await tid("insight-1-live").textContent(), /\(5 of 5 reps\)/);
  assert.match(await tid("ai-note").textContent(), /worded by an AI model/);

  // the caption: each tapped row shows its own cue, however the lead-in lands
  for (const [row, cue] of [["insight-1", "Straighten your right arm more"], ["insight-2", "Move your hands out wider"], ["insight-0", "Raise your left arm higher"]]) {
    await tid(row).click();
    await page.waitForTimeout(400);
    assert.equal(await tid("stage-caption").textContent(), cue, `${row}: the caption is the tapped row's cue`);
  }
  // R15: the why is template words, so the row shows the live sentence under the label, without template words
  await page.goto(`http://127.0.0.1:${port}/tests/part7/harness/result.html?case=insights-live-tmplwhy`);
  await page.waitForFunction(() => window.__ready === true);
  await page.waitForTimeout(500);
  assert.equal(await tid("insight-1-live").textContent(), "Your right elbow bends far more than the trainer's.");
  assert.equal(await tid("insight-1-ai").textContent(), "Worded by AI");
  assert.doesNotMatch(await tid("insight-1-live").textContent(), /example/, "negative: template words carry no label");
  // R14b R7, R15: lines in another language: the list carries no lang or dir, and no label sits on fixed text
  await page.goto(`http://127.0.0.1:${port}/tests/part7/harness/result.html?case=insights-live-es`);
  await page.waitForFunction(() => window.__ready === true);
  await page.waitForTimeout(500);
  assert.equal(await tid("insight-list").getAttribute("lang"), null, "R15: rows are English, so the list claims no other language");
  assert.equal(await tid("insight-list").getAttribute("dir"), null);
  assert.equal(await page.locator(".sr-ai").count(), 0, "negative: Part 5 wrote English fixed words, so no label");
  assert.match(await tid("ai-note").textContent(), /worded by an AI model/, "the take still has live lines, so the note stays");
  // R16: a real j7 take as Part 5 wrote it. Every rep row holds its fault's live sentence, so all seven are labelled, after the filler
  // pass too; an `es` take is labelled; a take with one fallback fault leaves exactly that row unlabelled.
  const open = async (c) => {
    await page.goto(`http://127.0.0.1:${port}/tests/part7/harness/result.html?case=${c}`);
    await page.waitForFunction(() => window.__ready === true);
    await page.waitForTimeout(500);
    await tid("timeline-0").click();
  };
  const repRows = () => page.evaluate(() => [...document.querySelectorAll(".sr-tl-miss")].map((r) => ({ text: r.querySelector(".sr-tl-miss-text").textContent, ai: !!r.querySelector(".sr-ai") })));
  await open("real");
  let rows = await repRows();
  assert.equal(rows.length, 7);
  assert.equal(rows.filter((r) => r.ai).length, 7, "all seven real rep rows are the model's sentences, each labelled");
  assert.match(rows.find((r) => /^Compared with the recording/.test(r.text) || /too far left/.test(r.text)).text, /right hand is too far left/);
  const first = page.locator(".sr-tl-miss").first();
  await first.click();
  await page.waitForTimeout(400);
  assert.equal(await tid("stage-caption").textContent(), "Straighten your arms more", "a tapped rep row shows its own cue");
  await open("real-es");
  rows = await repRows();
  assert.equal(rows.filter((r) => r.ai).length, 7, "a translated live line is labelled on the rep row too");
  assert.match(rows[0].text, /^Linea en espanol/);
  await open("real-mixed");
  rows = await repRows();
  assert.equal(rows.filter((r) => r.ai).length, 6, "the row whose fault fell back to fixed text has no label");
  assert.equal(rows.filter((r) => !r.ai).length, 1);
  // the dance take's drift card and marks: labelled card, fixed cue as the mark's name, never the sentence unlabelled
  await open("real-dance");
  const mark = page.locator('[data-testid="summary-drift-mark"]').first();
  const name = await mark.getAttribute("title");
  assert.equal(name, "Straighten your arms more", "the mark's title is the fixed cue");
  assert.equal(await mark.getAttribute("aria-label"), name);
  await mark.evaluate((b) => b.click());
  await page.waitForTimeout(300);
  const card = tid("summary-drift-detail");
  assert.match(await card.textContent(), /your elbows are bent much more/);
  assert.equal(await card.locator(".sr-ai").count(), 1, "the sentence on the drift card carries the label");
  await page.goto(`http://127.0.0.1:${port}/tests/part7/harness/result.html?case=insights-live`);
  await page.waitForFunction(() => window.__ready === true);
  await page.waitForTimeout(500);
  await tid("timeline-0").click();
  assert.equal(await page.locator(".sr-tl-miss .sr-ai").count(), 0, "negative: fixed-text rep rows carry no label");
  console.log("ok - AI label only on model-worded insight rows; a tapped row owns the caption");
} finally { await browser.close(); server.close(); }
