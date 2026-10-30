// Playwright drive of the unified take flow (web/take-flow.js) at 412x915 with Chromium's fake camera and a
// fake API: trainer (one person, picker skipped), follower (two people, picker, take labels) and group mode.
//   PLAYWRIGHT_DIR=/path/to/node_modules/playwright \
//     node tests/part7/drive_takeflow.mjs <out-dir>
import http from "node:http";
import fs from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";
import assert from "node:assert/strict";

const here = path.dirname(fileURLToPath(import.meta.url));
const WEB = path.resolve(here, "../../web");
const out = path.resolve(process.argv[2] || path.join(here, "screens"));
fs.mkdirSync(out, { recursive: true });
const { chromium } = createRequire(import.meta.url)(process.env.PLAYWRIGHT_DIR || "playwright");
const TYPES = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json" };

const server = http.createServer((req, res) => {
  const rel = decodeURIComponent(new URL(req.url, "http://x").pathname).replace(/^\//, "") || "index.html";
  const file = path.resolve(WEB, rel);
  if (!file.startsWith(WEB) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) { res.writeHead(404).end("no"); return; }
  res.writeHead(200, { "content-type": TYPES[path.extname(file)] || "application/octet-stream" });
  fs.createReadStream(file).pipe(res);
});
await new Promise((r) => server.listen(0, "127.0.0.1", r));
const BASE = `http://127.0.0.1:${server.address().port}/`;

const PNG = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==", "base64");
const errors = [];
const posts = [];
let scenario = { people: [], auto_id: null };
const person = (id, coverage = 0.9) => ({ id, coverage, frames: 40, box_mid: [10, 10, 50, 120] });

const browser = await chromium.launch({
  args: ["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream", "--autoplay-policy=no-user-gesture-required"],
});
const ctx = await browser.newContext({ viewport: { width: 412, height: 915 }, deviceScaleFactor: 2, permissions: ["camera"] });
const page = await ctx.newPage();
page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
page.on("console", (m) => { if (m.type() === "error" && !/Failed to load resource/.test(m.text())) errors.push(m.text()); });
await page.route("**/api/config", (r) => r.fulfill({ json: { limits: { max_seconds: 60, max_bytes: 95000000, recorder_bps: 2500000 } } }));
await page.route("**/api/uploads", (r) => { posts.push({ url: "uploads" }); r.fulfill({ status: 201, json: { upload_id: "u1", duration_ms: 5000, width: 640, height: 480 } }); });
await page.route("**/api/people", (r) => { posts.push({ url: "people", body: r.request().postDataJSON() }); r.fulfill({ status: 202, json: { job: "pj1" } }); });
await page.route("**/api/trainer", (r) => { posts.push({ url: "trainer", body: r.request().postDataJSON() }); r.fulfill({ status: 202, json: { job: "tj1" } }); });
await page.route("**/api/follow", (r) => { posts.push({ url: "follow", body: r.request().postDataJSON() }); r.fulfill({ status: 202, json: { job: "fj1" } }); });
await page.route("**/api/group", (r) => { posts.push({ url: "group", body: r.request().postDataJSON() }); r.fulfill({ status: 202, json: { job: "gj1" } }); });
await page.route("**/api/jobs/pj1/people/*.jpg", (r) => r.fulfill({ body: PNG, contentType: "image/png" }));
await page.route("**/api/jobs/pj1", (r) => r.fulfill({ json: { id: "pj1", kind: "people", status: "done", result: { ...scenario, frame: "people/frame.jpg" } } }));
await page.route("**/api/jobs/gj1", (r) => r.fulfill({ json: { id: "gj1", kind: "group", status: "done", stage: "followers", entry_id: "class", result: { entry_id: "class", trainer_id: "0", people: [] } } }));
await page.route("**/catalog/api/entries/e1", (r) => r.fulfill({ json: { id: "e1", name: "Lateral raise" } }));
await page.route("**/catalog/api/entries", (r) => r.fulfill({ json: { entries: [] } }));
await page.route("**/api/labels", (r) => r.fulfill({ json: {} }));

const tid = (id) => page.getByTestId(id);
const shot = (name) => page.screenshot({ path: path.join(out, `${name}.png`), fullPage: true });
const log = (m) => console.log(`ok  ${m}`);

async function go(hash) {
  await page.goto("about:blank"); // a fresh document, not a hash change
  await page.goto(`${BASE}${hash}`);
}

async function record() {
  await tid("countdown-select").selectOption("0");
  await tid("duration-select").selectOption("5");
  await tid("framing-hint").waitFor();
  await tid("cam-start").click();
  await tid("trim-continue").waitFor({ timeout: 20000 });
  assert.notEqual((await tid("trim-length").textContent()).trim(), "", "the trim length shows for a MediaRecorder take");
  await tid("trim-continue").click();
}

// 1. Trainer, one person: the picker is skipped, details, save.
scenario = { people: [person("0")], auto_id: "0" };
await go("#/record");
await record();
await tid("name").waitFor();
assert.equal(await tid("people").count(), 0, "one person skips the picker");
await tid("name").fill("Lateral raise");
await tid("tag-input").fill("shoulders,");
await tid("notes").fill("Slow");
await shot("takeflow-1-trainer-details");
await tid("save").click();
await page.waitForURL(/#\/job\/tj1/);
const t = posts.find((p) => p.url === "trainer").body;
assert.deepEqual([t.name, t.category, t.upload_id, t.people_job, t.person_id], ["Lateral raise", "exercise", "u1", "pj1", "0"]);
assert.ok(t.trim && t.trim.end_ms > t.trim.start_ms);
assert.deepEqual(t.labels, { tags: ["shoulders"], notes: "Slow" });
assert.deepEqual(posts.find((p) => p.url === "people").body.trim, t.trim);
log("trainer: people job after the trim, picker skipped, trainer POST has trim, person and labels");

// 2. Follower, two people: picker, optional labels.
posts.length = 0;
scenario = { people: [person("0"), person("1", 0.5)], auto_id: null };
await go("#/follow/e1");
await record();
await tid("people").waitFor();
assert.equal(await tid("mode-group").count(), 0, "no group switch on the follower screen");
await tid("person-1").click();
await shot("takeflow-2-follower-picker");
await tid("people-continue").click();
await tid("analyse").waitFor();
assert.equal(await tid("name").count(), 0, "a follower has no name field");
await tid("tag-input").fill("left-side,");
await tid("analyse").click();
await page.waitForURL(/#\/job\/fj1/);
const f = posts.find((p) => p.url === "follow").body;
assert.deepEqual([f.entry_id, f.people_job, f.person_id], ["e1", "pj1", "1"]);
assert.deepEqual(f.labels, { tags: ["left-side"], notes: "" });
log("follower: picker, take labels in the follow POST");

// 3. Follower without labels sends none.
posts.length = 0;
scenario = { people: [person("0")], auto_id: "0" };
await go("#/follow/e1");
await record();
await tid("analyse").waitFor();
await tid("analyse").click();
await page.waitForURL(/#\/job\/fj1/);
assert.equal("labels" in posts.find((p) => p.url === "follow").body, false);
log("follower: no labels, none sent");

// 4. Group: switch, picker with trainer and followers, group POST, the finished job opens the board.
posts.length = 0;
scenario = { people: [person("0"), person("1"), person("2")], auto_id: null };
await go("#/record");
await tid("mode-group").click();
await record();
await tid("people").waitFor();
await tid("person-0").click();
await tid("person-label-1").fill("Front row left");
await shot("takeflow-3-group-picker");
await tid("people-continue").click();
await tid("name").fill("Monday class");
await tid("category").selectOption("dance");
await tid("save").click();
await page.waitForURL(/#\/group\/gj1/, { timeout: 15000 });
const g = posts.find((p) => p.url === "group").body;
assert.deepEqual([g.name, g.category, g.people_job, g.trainer_id, g.follower_ids, g.save_entry], ["Monday class", "dance", "pj1", "0", ["1", "2"], true]);
assert.equal(g.labels["1"], "Front row left");
assert.ok(g.trim);
log("group: mode switch, picker, group POST, a done group job opens #/group/<job>");

assert.deepEqual(errors, [], errors.join("\n"));
await browser.close();
server.close();
console.log("drive_takeflow: all ok");
