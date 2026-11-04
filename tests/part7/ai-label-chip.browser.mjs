// The "Worded by AI" label is a legal promise, so it must be readable (docs/specs/result-release-16.md, AC-R16-1b): at 320 and 412
// wide the pill holds its text and the text on the pill measures at least 4.5:1. Uses the app's own stylesheets, in index.html's order.
// Run: PLAYWRIGHT_DIR=<node_modules> scripts/with-browser-slot.sh node tests/part7/ai-label-chip.browser.mjs
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { serveRoot } from "./serve_static.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const req = createRequire(path.join(process.env.PLAYWRIGHT_DIR || path.resolve(here, "../../node_modules"), "x.js"));
const { chromium } = req("playwright");
const html = fs.readFileSync(path.resolve(here, "../../web/index.html"), "utf8");
const sheets = [...html.matchAll(/<link rel="stylesheet" href="([^"]+)"/g)].map((m) => m[1]);
assert.ok(sheets.includes("theme/results.css"), "the app links the sheet that holds the chip's rule");
const OLD_RULE = "body .sr-chip.sr-ai { height: 26px !important; min-height: 0 !important; padding: 0 10px !important; line-height: normal !important; }";

/** One entry per label on the page: does its box hold its text, and how its text measures on its own background. */
const measure = (page) => page.evaluate(() => {
  const channels = (css) => css.match(/[\d.]+/g).map(Number);
  const luminance = ([r, g, b]) => {
    const f = (v) => { const s = v / 255; return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4; };
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
  };
  return [...document.querySelectorAll(".sr-ai")].map((chip) => {
    const box = chip.getBoundingClientRect();
    const range = document.createRange();
    range.selectNodeContents(chip);
    const text = range.getBoundingClientRect();
    const style = getComputedStyle(chip);
    const [bg, fg] = [channels(style.backgroundColor), channels(style.color)];
    const [hi, lo] = [luminance(bg), luminance(fg)].sort((a, b) => b - a);
    return {
      holds: text.top >= box.top - 0.5 && text.bottom <= box.bottom + 0.5 && text.left >= box.left - 0.5 && text.right <= box.right + 0.5,
      opaque: bg.length === 3 || bg[3] === 1,
      ratio: (hi + 0.05) / (lo + 0.05),
      inRow: box.right <= chip.parentElement.getBoundingClientRect().right + 0.5,
    };
  });
});

const { server, port } = await serveRoot();
const browser = await chromium.launch({ args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"] });
try {
  for (const width of [320, 412]) {
    const ctx = await browser.newContext({ viewport: { width, height: 915 }, hasTouch: true, reducedMotion: "reduce" });
    await ctx.addInitScript(() => { try { localStorage.setItem("simon.stage.breakdown", "open"); } catch { /* blocked */ } });
    const page = await ctx.newPage();
    // insight rows, then the rep rows of a real take (the timeline's labels)
    for (const [name, open] of [["insights-live", false], ["real", true]]) {
      await page.goto(`http://127.0.0.1:${port}/tests/part7/harness/result.html?case=${name}`);
      await page.waitForFunction(() => window.__ready === true);
      for (const href of sheets) await page.addStyleTag({ url: `/web/${href}` });
      await page.waitForTimeout(500);
      if (open) await page.getByTestId("timeline-0").click();
      const chips = await measure(page);
      assert.ok(chips.length > 0, `${name} at ${width}: a label is on the page`);
      for (const c of chips) {
        assert.ok(c.holds, `${name} at ${width}: the pill holds its text ${JSON.stringify(c)}`);
        assert.ok(c.inRow, `${name} at ${width}: the pill stays inside its row ${JSON.stringify(c)}`);
        assert.ok(c.opaque && c.ratio >= 4.5, `${name} at ${width}: readable on the pill ${JSON.stringify(c)}`);
      }
      console.log(`ok - ${name} at ${width}: ${chips.length} label(s), contrast ${chips[0].ratio.toFixed(2)}:1`);
      // negative: with the old fixed height back, this measure sees the spill (the insight rows wrap the label at both widths)
      if (name === "insights-live") {
        await page.addStyleTag({ content: OLD_RULE });
        const spilled = await measure(page);
        assert.ok(spilled.some((c) => !c.holds), `${name} at ${width}: negative, the old rule must spill`);
        console.log(`ok - negative at ${width}: the old rule spills`);
      }
    }
    await ctx.close();
  }
  console.log("all green");
} finally { await browser.close(); server.close(); }
