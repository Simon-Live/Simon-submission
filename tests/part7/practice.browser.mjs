// Browser checks for modes and "Learn in sections" at 412x915 (practice-and-modes.md). The page is the real app;
// the API is a small fake served by this file (additive: no shared fake is touched).
//   PLAYWRIGHT_DIR=/path/to/node_modules/playwright node tests/part7/practice.browser.mjs [shots-dir]
import http from "node:http";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const WEB = path.resolve(here, "../../web");
const out = path.resolve(process.argv[2] || path.join(here, "screens"));
fs.mkdirSync(out, { recursive: true });
const { chromium } = createRequire(import.meta.url)(process.env.PLAYWRIGHT_DIR || "playwright");
const TYPES = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json" };

const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "practice-"));
execFileSync("ffmpeg", ["-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=15", "-t", "12", "-c:v", "libvpx", "-b:v", "200k", path.join(tmp, "ref.webm")]);
const VIDEO = fs.readFileSync(path.join(tmp, "ref.webm"));
fs.rmSync(tmp, { recursive: true, force: true });

const rep = (n, ...ms) => ({ rep: n, movement: "raise", keyframes: ms.map((t_ms, i) => ({ name: `k${i}`, frame: t_ms / 40, t_ms })) });
const ENTRIES = [
  { id: "salsa", name: "Salsa basic", category: "dance", files_source: "import", video_uri: null, animation: "animation.json", duration_ms: 12000 },
  { id: "sq", name: "Lateral raise", category: "exercise", files_source: "import", video_uri: "video.webm", keyframes: "keyframes.json", animation: "animation.json", duration_ms: 12000 },
  { id: "knee", name: "Knee bends", category: "exercise", files_source: "import", video_uri: "video.webm", keyframes: "keyframes.json", animation: "animation.json", duration_ms: 12000 },
  // TICKET-311: an entry with no kind (no category, no rehab tag) is the only one whose mode the picker decides
  { id: "free", name: "Free move", files_source: "import", video_uri: null, animation: "animation.json", duration_ms: 12000 },
];
const LABELS = { knee: { tags: ["rehab"], notes: "" } };
const KEYFRAMES = { fps: 25, people: [{ id: 0, repetitions: [rep(1, 0, 1500), rep(2, 4000, 5500), rep(3, 8000, 9500)] }] };
const JOBS = {
  fj1: { id: "fj1", kind: "follow", status: "done", entry_id: "knee", mode: "rehab", section: { start_ms: 0, end_ms: 4000, index: 1, count: 3, speed: 0.5 }, result: { score: 85, grade: "B" } },
  fjlow: { id: "fjlow", kind: "follow", status: "done", entry_id: "knee", result: { score: 70, grade: "C" } },
};
const posts = [];

const json = (res, body, status = 200) => { res.writeHead(status, { "content-type": "application/json" }); res.end(JSON.stringify(body)); };
const server = http.createServer((req, res) => {
  const url = new URL(req.url, "http://x");
  const p = decodeURIComponent(url.pathname);
  let body = [];
  req.on("data", (c) => body.push(c));
  req.on("end", () => {
    let m;
    if (p === "/api/config") return json(res, { limits: { max_seconds: 60, max_bytes: 95000000, recorder_bps: 2500000 }, part5: { lang: true, video: true, private: true } });
    // a failed policy load is fail-closed (policy.js): the fake answers an open policy so Rehab shows
    if (p === "/api/policy") return json(res, { prod: false, switches: { rehab: true, face_copy: true, trainer_public: true, prize_boards: true, byok_ranked: true, mms_tts: true, muse: true }, phrasing_live: true, consent: { required: false, version: null, items: [], header: "X-Simon-Consent" }, age: { minimum: 18, adult: 18 } });
    if (p === "/api/client-log") { res.writeHead(204); return res.end(); }
    if (p === "/api/labels") return json(res, LABELS);
    if (p === "/catalog/api/entries") return json(res, { entries: ENTRIES });
    if ((m = /^\/catalog\/api\/entries\/([^/]+)(?:\/(.+))?$/.exec(p))) {
      const entry = ENTRIES.find((e) => e.id === m[1]);
      if (!entry) return json(res, { error: "no" }, 404);
      if (!m[2]) return json(res, entry);
      if (m[2] === "keyframes.json") return json(res, KEYFRAMES);
      if (m[2] === "animation.json") return json(res, { fps: 30, frames: [] });
      if (m[2] === "video.webm") {
        const rng = req.headers.range;
        if (rng) {
          const [a, b] = rng.replace("bytes=", "").split("-");
          const start = Number(a || 0);
          const end = b ? Number(b) : VIDEO.length - 1;
          res.writeHead(206, { "content-type": "video/webm", "accept-ranges": "bytes", "content-range": `bytes ${start}-${end}/${VIDEO.length}` });
          return res.end(VIDEO.subarray(start, end + 1));
        }
        res.writeHead(200, { "content-type": "video/webm", "accept-ranges": "bytes" });
        return res.end(VIDEO);
      }
    }
    if (p === "/api/uploads") return json(res, { upload_id: "u1", duration_ms: 5000, width: 640, height: 480 }, 201);
    if (p === "/api/people") return json(res, { job: "pj1" }, 202);
    if (p === "/api/jobs/pj1") return json(res, { id: "pj1", kind: "people", status: "done", result: { people: [{ id: "0", coverage: 0.9, frames: 40, box_mid: [10, 10, 50, 120] }], frame: "people/frame.jpg", auto_id: "0" } });
    if (p === "/api/challenges/chOpen") return json(res, { id: "chOpen", entry_id: "sq", title: "Beat my Lateral raise", kind: "friend", ended: false, entries: [] });
    if (p === "/api/challenges/chEnded") return json(res, { id: "chEnded", entry_id: "sq", title: "Old news", kind: "friend", ended: true, entries: [] });
    if (p === "/api/follow") { posts.push(JSON.parse(Buffer.concat(body).toString() || "{}")); return json(res, { job: "fj1" }, 202); }
    if ((m = /^\/api\/jobs\/([^/]+)$/.exec(p))) return JOBS[m[1]] ? json(res, JOBS[m[1]]) : json(res, { error: "no" }, 404);
    const rel = p === "/" ? "index.html" : p.replace(/^\//, "");
    const file = path.resolve(WEB, rel);
    if (!file.startsWith(WEB) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) { res.writeHead(404).end("no"); return; }
    res.writeHead(200, { "content-type": TYPES[path.extname(file)] || "application/octet-stream" });
    fs.createReadStream(file).pipe(res);
  });
});
await new Promise((r) => server.listen(0, "127.0.0.1", r));
const BASE = `http://127.0.0.1:${server.address().port}/`;

const browser = await chromium.launch({ args: ["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream", "--autoplay-policy=no-user-gesture-required"] });
const ctx = await browser.newContext({ viewport: { width: 412, height: 915 }, deviceScaleFactor: 2, permissions: ["camera"] });
const page = await ctx.newPage();
const errors = [];
page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
page.on("console", (m) => { if (m.type() === "error" && !/Failed to load resource/.test(m.text())) errors.push(m.text()); });
const tid = (id) => page.getByTestId(id);
const shot = (name) => page.screenshot({ path: path.join(out, `practice-${name}.png`), fullPage: true });
const ok = (m) => console.log(`ok  ${m}`);
const MSG_CLOSED = "This challenge is closed or not for this movement."; // web/follow-challenge.js
const go = async (hash) => { await page.goto("about:blank"); await page.goto(`${BASE}${hash}`); };
const store = (k) => page.evaluate((key) => localStorage.getItem(key), k);
// The home library is one paged list; the Type filter (Exercise, Dance, Rehab) narrows it (home-browse.md).
const cardIds = async () => (await page.locator('[data-testid="entries"] .lib-thumb').evaluateAll((els) => els.map((e) => e.dataset.testid.replace(/^entry-/, "")))).sort();

try {
  // 1. Catalog: the Type filter does the header switch's old job; there is no switch; an old stored choice is ignored (TICKET-436)
  await go("#/");
  await page.evaluate(() => localStorage.setItem("simon.mode", "dance")); // what the removed header switch left behind
  await go("#/");
  await tid("entry-sq").waitFor();
  assert.deepEqual(await cardIds(), ["free", "knee", "salsa", "sq"], "one list: every kind, and the entry with no kind (home-browse.md)");
  assert.equal(await page.locator('[data-testid^="kind-"], .kind-switch, #kind-switch').count(), 0, "negative: no kind switch in the header");
  assert.equal(await store("simon.mode"), null, "the old stored choice is dropped");
  await go("#/?type=rehab");
  await tid("entry-knee").waitFor();
  assert.deepEqual(await cardIds(), ["knee"], "a rehab-tagged move shows under Rehab, the plain exercise does not");
  await go("#/?type=dance");
  await tid("entry-salsa").waitFor();
  assert.deepEqual(await cardIds(), ["salsa"]);
  await go("#/?mode=dance");
  await tid("entry-sq").waitFor();
  await go("#/follow/sq?mode=rehab");
  await tid("follow-mode").waitFor();
  assert.equal(await tid("follow-mode-fitness").getAttribute("aria-pressed"), "true", "the old mode parameter does not override the entry's kind");
  await go("#/?type=dance");
  await tid("entry-salsa").waitFor();
  await shot("1-catalog-dance");
  ok("catalog: the Type filter narrows the list, no switch, old stored mode dropped, old mode links open");

  // 2. Follow screen: the default comes from the category until a choice is stored
  await page.evaluate(() => localStorage.clear());
  await go("#/follow/sq");
  await tid("follow-mode").waitFor();
  assert.equal(await tid("follow-mode").getAttribute("data-value"), "fitness", "exercise defaults to fitness");
  assert.equal(await tid("mode-safety").count(), 0);
  assert.equal(await store("simon.practice.mode"), null, "nothing is stored until the person chooses");
  await go("#/follow/salsa");
  await tid("follow-mode").waitFor();
  assert.equal(await tid("follow-mode").getAttribute("data-value"), "dance", "dance defaults to dance");
  // TICKET-311: an entry with a kind shows that kind's mode, locked; the rehab tag wins over the category
  await go("#/follow/sq");
  await tid("follow-mode").waitFor();
  assert.equal(await tid("follow-mode").getAttribute("data-locked"), "entry");
  assert.equal(await tid("follow-mode-fitness").getAttribute("aria-pressed"), "true");
  assert.equal(await tid("follow-mode-rehab").isDisabled(), true, "the picker refuses another mode for this entry");
  await go("#/follow/knee");
  await tid("follow-mode").waitFor();
  await page.waitForFunction(() => document.querySelector('[data-testid="follow-mode"]').dataset.value === "rehab");
  assert.equal(await tid("follow-mode").getAttribute("data-locked"), "entry");
  await go("#/follow/free");
  await tid("follow-mode").waitFor();
  assert.equal(await tid("follow-mode").getAttribute("data-locked"), null, "negative: an entry without a kind keeps the picker");
  await tid("follow-mode-rehab").click();
  assert.match(await tid("mode-safety").textContent(), /Move within a pain-free range; stop if it hurts\./);
  assert.equal(await tid("countdown-select").inputValue(), "10", "rehab counts down longer");
  await tid("follow-mode-fitness").click();
  assert.equal(await tid("mode-safety").count(), 0);
  assert.equal(await tid("countdown-select").inputValue(), "5");
  await tid("follow-mode-rehab").click();
  assert.equal(await store("simon.practice.mode"), "rehab");
  ok("follow: default from category, the entry's kind locks the picker, picker stored, rehab safety line and 10 s countdown");

  await go("#/follow/knee"); // the rehab-tagged entry: rehab presets whatever was picked
  await tid("follow-mode").waitFor();

  // 3. Sections: derived from the keyframes, the ladder, the reference at the step's rate
  await tid("practice-toggle").check();
  await tid("ladder").waitFor();
  assert.equal(await tid("ladder").getAttribute("data-source"), "keyframes");
  assert.equal(await page.locator('[data-testid^="step-"]').count(), 8, "3 sections x (slow, full) + joined + full routine");
  const ref = tid("reference");
  assert.equal(await ref.getAttribute("data-section"), "0-4");
  assert.equal(await tid("reference-video").evaluate((v) => v.playbackRate), 0.5);
  assert.equal(await tid("step-s1@slow").isEnabled(), true);
  for (const k of ["s1@full", "s2@slow", "j1-2", "full"]) assert.equal(await tid(`step-${k}`).isDisabled(), true, `${k} is locked`);
  await tid("step-s2@slow").click({ force: true });
  assert.equal(await ref.getAttribute("data-section"), "0-4", "negative: a locked step cannot be started");
  assert.equal(await tid("step-s2@slow").getAttribute("data-state"), "locked");
  await tid("practice-watch").click();
  await page.waitForFunction(() => !document.querySelector('[data-testid="reference-video"]').paused);
  await tid("reference-video").evaluate((v) => { v.currentTime = 3.9; });
  await page.waitForTimeout(700);
  const t = await tid("reference-video").evaluate((v) => v.currentTime);
  assert.ok(t < 3, `the video looped back inside the section (at ${t})`);
  assert.equal(await tid("reference-video").evaluate((v) => v.loop), false);
  await tid("practice-watch").click();
  await shot("2-ladder");
  ok("practice: 8 steps from keyframes, reference at 0.5x looping 0 to 4 s, locked step refused");

  // 4. Record a take: the POST carries mode and the section; the score comes back on return
  await tid("countdown-select").selectOption("0");
  await tid("duration-select").selectOption("5");
  await tid("cam-start").click();
  await tid("trim-continue").waitFor({ timeout: 20000 });
  await tid("trim-continue").click();
  await tid("analyse").waitFor();
  await tid("analyse").click();
  await page.waitForURL(/#\/(job|result)\/fj1/);
  assert.deepEqual(posts.at(-1).section, { start_ms: 0, end_ms: 4000, index: 1, count: 3, speed: 0.5 });
  assert.equal(posts.at(-1).mode, "rehab");
  assert.equal("lang" in posts.at(-1), false, "no language is sent until the person picks one");
  assert.deepEqual(JSON.parse(await store("simon.practice.knee")).pending, { key: "s1@slow", job: "fj1" });
  await go("#/follow/knee");
  await tid("ladder").waitFor();
  await tid("step-s1@full").waitFor();
  await page.waitForFunction(() => !document.querySelector('[data-testid="step-s1@full"]').disabled);
  assert.equal(await tid("step-s1@slow").getAttribute("data-state"), "passed");
  assert.match(await tid("step-s1@slow").textContent(), /Passed with 85/);
  assert.equal(await tid("step-s2@slow").isDisabled(), true, "the next section waits for section 1 at full speed");
  assert.equal(JSON.parse(await store("simon.practice.knee")).pending, null);
  await tid("step-s1@full").click();
  assert.equal(await tid("reference-video").evaluate((v) => v.playbackRate), 1);
  assert.equal(await tid("reference").getAttribute("data-section"), "0-4");
  await shot("3-unlocked");
  ok("practice: POST api/follow has mode and section, score 85 passes the slow step and unlocks full speed");

  // 5. A score below 80 does not unlock
  await page.evaluate(() => localStorage.setItem("simon.practice.knee", JSON.stringify({ v: 1, on: true, best: {}, pending: { key: "s1@slow", job: "fjlow" } })));
  await go("#/follow/knee");
  await tid("ladder").waitFor();
  await page.waitForFunction(() => JSON.parse(localStorage.getItem("simon.practice.knee")).best["s1@slow"] === 70);
  assert.equal(await tid("step-s1@full").isDisabled(), true, "negative: 70 is below 80");
  ok("practice: a take scored 70 does not unlock the next step");

  // 6. The result screen note
  await go("#/");
  const note = (record, analysis) => page.evaluate(async ([record, analysis]) => {
    const m = await import("/modes.js");
    const slot = document.createElement("div");
    document.body.append(slot);
    m.mountModeNote(slot, { job: "j", pid: null, analysis, jobRecord: record });
    const text = (id) => (slot.querySelector(`[data-testid="${id}"]`) || {}).textContent || "";
    return { html: slot.innerHTML.length, chip: text("mode-chip"), safety: text("mode-safety"), scoring: text("mode-scoring"), section: text("section-line"), back: !!slot.querySelector('[data-testid="back-to-practice"]') };
  }, [record, analysis]);
  const rehab = await note(JOBS.fj1, { score: { value: 85 } });
  assert.equal(rehab.chip, "Rehab mode");
  assert.match(rehab.safety, /pain-free range/);
  assert.equal(rehab.scoring, "This score uses the standard rules.", "an older job with a mode but no profile");
  assert.equal(rehab.section, "Section 1 of 3");
  assert.equal(rehab.back, true);
  const profiled = await note(JOBS.fj1, { score: { value: 85 }, profile: "rehab" });
  assert.match(profiled.scoring, /^Scored with rehab rules\. These practice rules are more forgiving\. They are not a more accurate measure\.$/);
  assert.doesNotMatch(profiled.scoring, /standard rules/);
  const part7 = await note(JOBS.fj1, { score: { value: 85 }, profile: "dance", profile_source: "part7-rules" });
  assert.match(part7.scoring, /^Scored with dance rules\./, "a Part 7 profile reads like a Part 5 one");
  const fit = await note({ ...JOBS.fj1, mode: "fitness" }, { profile: "fitness", profile_source: "part7-rules" });
  assert.equal(fit.scoring, "Scored with fitness rules. These are the standard rules.");
  assert.doesNotMatch(fit.scoring, /forgiving/, "negative: fitness is not called forgiving");
  const secOnly = await note({ ...JOBS.fj1, mode: undefined }, { profile: "fitness" });
  assert.equal(secOnly.chip, "", "no mode chip when the person chose no mode");
  assert.equal(secOnly.scoring, "This score uses the standard rules.", "negative: Part 5's default fitness is not announced as a choice");
  const none = await note({ id: "old", kind: "follow" }, { score: { value: 85 } });
  assert.equal(none.html, 0, "negative: a job with no mode or section shows nothing");
  ok("result note: mode chip, rehab safety line, section line, scoring line with and without a Part 5 profile");

  // 6. What a take sends: mode only when chosen (B3), challenge_id only for an open challenge of this movement (B5)
  const takeOne = async () => {
    await tid("countdown-select").selectOption("0");
    await tid("duration-select").selectOption("5");
    await tid("cam-start").click();
    await tid("trim-continue").waitFor({ timeout: 20000 });
    await tid("trim-continue").click();
    await tid("analyse").waitFor();
    await tid("analyse").click();
    await page.waitForURL(/#\/(job|result)\/fj1/);
    return posts.at(-1);
  };
  await page.evaluate(() => localStorage.clear());
  await go("#/follow/sq/c/chOpen");
  await tid("follow-mode").waitFor();
  await page.waitForFunction(() => !document.querySelector('[data-testid="follow-challenge"]').hidden);
  assert.match(await tid("follow-challenge").textContent(), /Beat my Lateral raise/);
  let sent = await takeOne();
  assert.equal(sent.challenge_id, "chOpen", "the challenge id travels with the take");
  assert.equal(sent.mode, "fitness", "TICKET-311: the entry's category decides, even with nothing chosen");
  assert.equal("lang" in sent, false, "no language is sent until the person picks one");
  assert.equal(await store("simon.practice.mode"), null);
  await go("#/follow/sq/c/chEnded");
  await tid("follow-mode").waitFor();
  await page.waitForTimeout(400);
  assert.equal(await tid("follow-challenge").textContent(), MSG_CLOSED, "an ended challenge is not offered: the link says so (challenges.md)");
  await page.evaluate(() => localStorage.setItem("simon.lang", "es"));
  sent = await takeOne();
  assert.equal("challenge_id" in sent, false, "negative: an ended challenge is not sent");
  assert.equal(sent.lang, "es", "the picked language (simon.lang) is sent with the take");
  await go("#/follow/salsa/c/chOpen");
  await tid("follow-mode").waitFor();
  await page.waitForTimeout(400);
  assert.equal(await tid("follow-challenge").textContent(), MSG_CLOSED, "a challenge for another movement is not offered: the link says so");
  await go("#/follow/free");
  await tid("follow-mode-rehab").click();
  sent = await takeOne();
  assert.equal(sent.mode, "rehab", "an entry without a kind sends the picked mode");
  assert.equal("challenge_id" in sent, false);
  await go("#/follow/sq");
  await tid("follow-mode").waitFor();
  assert.equal(await store("simon.practice.mode"), "rehab", "the picker last said Rehab");
  sent = await takeOne();
  assert.equal(sent.mode, "fitness", "TICKET-311: a fitness entry with the picker on Rehab follows the entry");
  await page.evaluate(() => localStorage.setItem("simon.practice.mode", "fitness"));
  await go("#/follow/knee");
  await tid("follow-mode").waitFor();
  sent = await takeOne();
  assert.equal(sent.mode, "rehab", "TICKET-311: a rehab entry with the picker on Fitness sends rehab");
  ok("take: the entry's kind decides the mode, the picker only for an entry without one; challenge_id only for an open challenge of this movement");

  assert.deepEqual(errors, [], `console errors: ${errors.join(" | ")}`);
  ok("no console errors");
} finally {
  await browser.close();
  server.close();
}
