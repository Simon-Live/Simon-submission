// demo/remembers/capture.mjs: record the "Simon remembers" segment from the real UI (shotlist.md, TICKET-185).
// Runs ONLY once sign-in is live (TICKET-176 and TICKET-177) and demo/remembers/facts.json is filled from TICKET-184's
// saved report. It stops, and records nothing, while any slot is null or no signed-in session is given.
// Usage: REMEMBERS_STORAGE_STATE=<file> node demo/remembers/capture.mjs <out-dir> <base-url>
//   REMEMBERS_STORAGE_STATE: a Playwright storage state saved after the sign-in recipe
//   (qa/recipes/history-sign-in-and-claim.md). It holds a session cookie: keep it outside the repo, never print it.
//   STAGING_USER / STAGING_PASSWORD: gateway login via httpCredentials, only when the base URL needs it.
// Writes <out-dir>/remembers.webm and <out-dir>/captions.srt. Run it through scripts/with-browser-slot.sh.
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const FACTS = JSON.parse(fs.readFileSync(path.join(HERE, "facts.json"), "utf8"));
const STATE_FILE = process.env.REMEMBERS_STORAGE_STATE || "";
const OUT = path.resolve(process.argv[2] || path.join(os.tmpdir(), "simon-remembers"));
const BASE = (process.argv[3] || process.env.QA_BASE_URL || "").replace(/\/?$/, "/");
const VIEWPORT = { width: 412, height: 915 };

/** Slots that are still null: capture refuses to type a number in by hand. */
export function emptySlots(facts) {
  const gaps = Object.entries(facts.slots).filter(([, v]) => v === null || v === undefined).map(([k]) => `slots.${k}`);
  if (facts.movement === null) gaps.push("movement");
  facts.takes.forEach((t, i) => { for (const k of ["recorded_at", "score", "label"]) if (t[k] === null) gaps.push(`takes[${i}].${k}`); });
  return gaps;
}

/** Fill `{slot}` markers of a caption line from facts.json. */
export function fill(text, slots) {
  return text.replace(/\{(\w+)\}/g, (_, k) => {
    if (slots[k] === null || slots[k] === undefined) throw new Error(`slot ${k} is empty`);
    return String(slots[k]);
  });
}

const CAPTIONS = [
  [0, 6, "Your takes of {movement}"],
  [6, 12, "{takes} takes, {first_date} to {last_date}"],
  [12, 19, "Compare my takes"],
  [19, 27, "What changed between takes, in plain words"],
  [27, 34, "Take {cite_take}, {cite_s} s"],
  [34, 41, "{input_tokens} of 1,048,576 tokens, {cached_tokens} cached; watched {clips} of {takes} takes; {checked} claims checked"],
  [41, 46, "Stock clips and one cleared real take stand in for a student's practice."],
];

const stamp = (s) => new Date(s * 1000).toISOString().slice(11, 23).replace(".", ",");
export function srt(slots, movement = FACTS.movement) {
  const all = { ...slots, movement };
  return CAPTIONS.map(([a, b, text], i) => `${i + 1}\n${stamp(a)} --> ${stamp(b)}\n${fill(text, all)}\n`).join("\n");
}

async function main() {
  const gaps = emptySlots(FACTS);
  if (gaps.length) { console.error(`remembers: facts.json is not filled (${gaps.join(", ")}); fill it from TICKET-184's report first`); return 2; }
  if (!STATE_FILE || !fs.existsSync(STATE_FILE)) { console.error("remembers: set REMEMBERS_STORAGE_STATE to a signed-in storage state (sign-in is not live until TICKET-176 and TICKET-177 land)"); return 2; }
  if (!/^https?:\/\//.test(BASE)) { console.error("remembers: pass the app's own-origin base URL"); return 2; }
  const { chromium } = createRequire(process.env.PLAYWRIGHT_ROOT || path.join(HERE, "..", "..", "package.json"))("playwright");
  fs.mkdirSync(OUT, { recursive: true });
  const dir = path.join(OUT, "raw");
  fs.rmSync(dir, { recursive: true, force: true });
  const browser = await chromium.launch();
  const ctx = await browser.newContext({
    viewport: VIEWPORT, deviceScaleFactor: 2, storageState: STATE_FILE, recordVideo: { dir, size: VIEWPORT },
    ...(process.env.STAGING_USER ? { httpCredentials: { username: process.env.STAGING_USER, password: process.env.STAGING_PASSWORD || "" } } : {}),
  });
  const page = await ctx.newPage();
  const t = (id) => page.getByTestId(id);
  const pause = (ms) => page.waitForTimeout(ms);
  await page.goto(`${BASE}#/me`, { waitUntil: "domcontentloaded" });
  await t("me-takes").waitFor();                                  // R1
  await pause(5000);
  await t("history-mytakes-0").click();                           // R2
  await t("history-page").waitFor();
  await pause(5000);
  const consent = t("history-consent-toggle");                    // R3
  if (await consent.count()) await consent.click();
  await t("history-run").click();
  await t("history-status").waitFor();
  await t("history-trend-0").waitFor({ timeout: 300000 });        // R4
  await pause(6000);
  await t("history-cite-0-0").click();                            // R5
  await t("history-video").waitFor();
  await pause(6000);
  await t("history-context").scrollIntoViewIfNeeded();            // R6
  await pause(6000);
  const video = page.video();
  await ctx.close();
  fs.copyFileSync(await video.path(), path.join(OUT, "remembers.webm"));
  fs.rmSync(dir, { recursive: true, force: true });
  fs.writeFileSync(path.join(OUT, "captions.srt"), srt(FACTS.slots));
  await browser.close();
  console.log(`remembers: wrote ${path.join(OUT, "remembers.webm")} and captions.srt`);
  return 0;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) process.exit(await main());
