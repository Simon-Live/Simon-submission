// Browser checks for Heat (TICKET-274) and "See it in your room" (TICKET-282) on the result screen
// (docs/specs/heat-and-ar.md AC-H3 to AC-H5, AC-A1 to AC-A3). The job's routes are answered with page.route; the meshes are
// web/mesh-demo, the heat is tests/part7/fixtures/heat (contract H1). Run:
//   PLAYWRIGHT_DIR=<node_modules> /home/gingy/claude-template/scripts/with-browser-slot.sh node tests/part7/heat_ar.browser.mjs
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { serveRoot } from "./serve_static.mjs";
import { isLaneModule404, isPickerRequest404, isOptionalResult404 } from "./lane_modules.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const req = createRequire(path.join(process.env.PLAYWRIGHT_DIR || path.resolve(here, "../../node_modules"), "x.js"));
const { chromium } = req("playwright");
const AXE = fs.readFileSync(req.resolve("axe-core/axe.min.js"), "utf8");
const SHOTS = process.env.SHOTS_DIR || path.join(here, "screens");
fs.mkdirSync(SHOTS, { recursive: true });
const web = path.resolve(here, "../../web");
const JOB = "abcdef123456";
const ANDROID = "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36";
const IPHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1";

const { server, port } = await serveRoot();
const browser = await chromium.launch({ args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"] });
const errors = [];
const external = [];
let passed = 0;
const ok = (name) => { passed++; console.log(`ok - ${name}`); };

/** device: desktop | android | iphone. files: which of heat/glb/usdz the mesh.json names. width: viewport width. */
async function open(label, { device = "desktop", width = 412, heat = true, glb = true, usdz = true, sign = "ok", faultAt = 3 } = {}) {
  const phone = device !== "desktop";
  const ctx = await browser.newContext({
    viewport: { width, height: phone ? 915 : 900 }, hasTouch: phone, isMobile: phone,
    userAgent: device === "android" ? ANDROID : device === "iphone" ? IPHONE : undefined,
  });
  // Safari answers a.relList.supports("ar"); Chromium does not, so the iPhone case says so
  if (device === "iphone") await ctx.addInitScript(() => { const s = DOMTokenList.prototype.supports; DOMTokenList.prototype.supports = function (t) { return t === "ar" ? true : s.call(this, t); }; });
  await ctx.addInitScript(() => { try { localStorage.setItem("simon.result.more", "open"); } catch { /* blocked */ } });   // the lean result keeps the worst moment card (and its 3D bodies) in "More"
  const page = await ctx.newPage();
  page.on("console", (m) => { if (m.type() === "error" && !(sign === "fail" && /\/take-ar-url/.test(m.location().url)) && !isLaneModule404(m.location().url) && !isOptionalResult404(m.location().url) && !isPickerRequest404(m.location().url)) errors.push(`${label}: ${m.text()} ${m.location().url}`); });
  page.on("pageerror", (e) => errors.push(`${label}: ${e.message}`));
  page.on("request", (r) => { const u = new URL(r.url()); if (!["127.0.0.1", "localhost"].includes(u.hostname) && u.protocol.startsWith("http")) external.push(r.url()); });
  const json = (route, body, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
  await page.route(`**/api/results/${JOB}/video.mp4`, (r) => r.continue({ url: `http://127.0.0.1:${port}/tests/part7/fixtures/coach.webm` }));
  await page.route("**/api/auth/me", (r) => json(r, { available: false }));
  await page.route(`**/api/results/${JOB}/models.json`, (r) => json(r, { error: "gone" }, 404));
  await page.route(`**/api/results/${JOB}/skeleton2d.json`, (r) => json(r, {}, 404));
  const rel = (f) => `api/results/${JOB}/${f}`;
  await page.route(`**/api/results/${JOB}/mesh.json`, (r) => json(r, {
    trainer: rel("mesh/trainer/mesh3d.json"), you: rel("mesh/you/mesh3d.json"),
    ...(heat ? { heat: rel("heat/heat.json") } : {}),
  }));
  // take-ar.md, faked: which files the trainer has, and the signed-link request. sign: ok (a take-ar token valid 5 minutes),
  // fail (404), plain (the job's own path, which the page must refuse)
  const entry = glb || usdz ? { glb: glb ? rel("take/trainer.glb") : null, usdz: usdz ? rel("take/trainer.usdz") : null, duration_s: 6 } : null;
  await page.route(`**/api/results/${JOB}/take-ar.json`, (r) => json(r, { schema: "simon.take-ar.v1", trainer: entry, you: null }));
  page.signed = [];
  await page.route(`**/api/results/${JOB}/take-ar-url?*`, (r) => {
    const q = new URL(r.request().url()).searchParams;
    page.signed.push({ who: q.get("who"), kind: q.get("kind") });
    if (sign === "fail") return r.fulfill({ status: 404, body: "" });
    const url = sign === "plain" ? rel(`take/trainer.${q.get("kind")}`) : `api/take-ar/dGVzdA.c2ln${q.get("kind")}`;
    return json(r, { url, expires_utc: new Date(Date.now() + 5 * 60000).toISOString() });
  });
  await page.route(`**/api/results/${JOB}/mesh/*/*`, (r) => {
    const [who, file] = new URL(r.request().url()).pathname.split("/").slice(-2);
    const demo = path.join(web, "mesh-demo", who === "you" ? "follower" : "trainer", file);
    return fs.existsSync(demo) ? r.fulfill({ path: demo }) : r.fulfill({ status: 404, body: "" });
  });
  await page.route(`**/api/results/${JOB}/heat/*`, (r) => r.fulfill({ path: path.join(here, "fixtures/heat", new URL(r.request().url()).pathname.split("/").pop()) }));
  await page.route("**/catalog/api/entries/*", (r) => json(r, { id: "lateral-raise-0f13199f", name: "Lateral raise" }));
  for (const f of ["voice.js", "second-opinion.js", "export.js", "narration.js"]) await page.route(`**/web/${f}`, (r) => r.fulfill({ contentType: "text/javascript", body: "export {};" }));
  await page.goto(`http://127.0.0.1:${port}/tests/part7/harness/result-additions.html?case=ok&faultAt=${faultAt}`);
  await page.waitForFunction(() => window.__ready === true);
  await page.waitForTimeout(500);
  return page;
}
const tid = (page, id) => page.getByTestId(id);
const overflow = (page) => page.evaluate(() => {
  const vw = document.documentElement.clientWidth;
  const wide = [...document.querySelectorAll('[data-testid="stage-tools"], [data-testid="stage-tools"] *')].filter((n) => { const r = n.getBoundingClientRect(); return r.width > 0 && (r.right > vw + 0.5 || r.left < -0.5); }).map((n) => n.className || n.tagName);
  return { scroll: document.documentElement.scrollWidth, vw, wide };
});
/** Counts of cool (blue), hot (yellow) and lime pixels on the 3D canvas. */
const pixels = (page) => page.evaluate(() => {
  const c = document.querySelector('[data-testid="summary-mesh"] canvas');
  const o = document.createElement("canvas");
  o.width = c.width; o.height = c.height;
  const g = o.getContext("2d");
  g.drawImage(c, 0, 0);
  const d = g.getImageData(0, 0, o.width, o.height).data;
  let cool = 0, hot = 0, lime = 0;
  for (let i = 0; i < d.length; i += 4) {
    const [r, gr, b, a] = [d[i], d[i + 1], d[i + 2], d[i + 3]];
    if (a < 200) continue;
    if (b > r + 25 && b > gr) cool++;
    if (r > 50 && r > b + 25 && gr < r * 1.05 && gr > r * 0.8) hot++;
    if (gr > r * 1.15 && gr > b + 40) lime++;
  }
  return { cool, hot, lime };
});
const axe = async (page, label) => {
  await page.evaluate(AXE);
  const res = await page.evaluate(() => axe.run(document.querySelector('[data-testid="summary-mesh"]'), { runOnly: ["wcag2a", "wcag2aa"] }));
  const bad = res.violations.filter((v) => ["serious", "critical"].includes(v.impact));
  assert.deepEqual(bad.map((v) => `${v.id}: ${v.nodes.map((n) => n.target).join(" ")}`), [], `${label}: axe`);
};

try {
  // ---- desktop: Heat, legend, QR, no AR button -----------------------------------------------------------------
  const d = await open("desktop", { width: 1440 });
  await tid(d, "summary-mesh").locator("canvas").waitFor({ timeout: 15000 });
  await tid(d, "heat-toggle").waitFor();
  assert.equal(await tid(d, "heat-toggle").getAttribute("aria-pressed"), "false");
  assert.equal(await tid(d, "heat-panel").isVisible(), false, "the legend waits for the Heat press");
  assert.equal(await tid(d, "ar-button").count(), 0, "negative: no AR button on a desktop");
  assert.deepEqual(d.signed, [], "a desktop asks for no signed address: the QR code carries only the page address");
  await tid(d, "ar-qr").waitFor();
  assert.equal(await tid(d, "ar-qr").locator("svg path").count(), 1, "the QR code is drawn locally");
  assert.match(await tid(d, "ar-qr").locator("figcaption").textContent(), /^Scan with your phone/);
  const before = await pixels(d);
  assert.ok(before.hot < 400, `the lime body is not the hot end of the ramp (${JSON.stringify(before)})`);
  assert.ok(before.lime > 50, `the body is lime before the press (${before.lime})`);
  assert.equal(await tid(d, "heat-readout").textContent(), "Opens at your first reported fault, 3.0 s", "before the press the readout says where it opens");
  assert.equal(await tid(d, "heat-caption").textContent(), "Where your body differed most from the trainer in this frame.");
  await tid(d, "heat-toggle").click();
  assert.equal(await tid(d, "heat-toggle").getAttribute("aria-pressed"), "true");
  await tid(d, "heat-legend").waitFor({ state: "visible" });
  await d.waitForFunction(() => /^Differs most here: left knee$/.test(document.querySelector('[data-testid="heat-readout"]').textContent), null, { timeout: 15000 });
  const claims = await tid(d, "heat-panel").textContent();
  assert.doesNotMatch(claims, /worst|agree|where the fault|your fault is/i, "negative: the panel makes no claim that the heat shows the fault");
  // the seek to the opening frame lands a moment after the readout names the region: wait for the hot end to show
  let on = await pixels(d);
  for (let k = 0; k < 40 && on.hot <= before.hot + 100; k++) { await d.waitForTimeout(250); on = await pixels(d); }
  assert.ok(on.lime < before.lime / 10, `the lime body is replaced by the ramp (${JSON.stringify(on)})`);
  assert.ok(on.cool > 50, `cool parts are blue (${JSON.stringify(on)})`);
  assert.ok(on.hot > before.hot + 100, `the hottest region reaches the hot end of the ramp (${JSON.stringify(on)})`);
  // the legend gradient is the token ramp
  const ramp = await tid(d, "heat-legend").locator(".st-heat-ramp").evaluate((n) => getComputedStyle(n).backgroundImage);
  assert.match(ramp, /linear-gradient/);
  assert.equal((ramp.match(/rgb\(/g) || []).length, 5, "five token stops");
  await tid(d, "summary-mesh").screenshot({ path: path.join(SHOTS, "heat-desktop-1440.png") });
  await axe(d, "desktop heat on");
  await tid(d, "heat-toggle").click();
  await d.waitForTimeout(500);
  const off = await pixels(d);
  assert.ok(off.hot < on.hot / 2, `heat off takes the ramp away (${JSON.stringify({ off, on })})`);
  assert.ok(off.lime > 50, "and the lime body returns");
  ok("desktop: Heat opens at the first fault's frame, paints the ramp with a legend, toggles off; QR drawn locally, no AR button");

  // ---- Android: the button, no QR ------------------------------------------------------------------------------
  for (const width of [412, 320]) {
    const a = await open(`android-${width}`, { device: "android", width });
    await tid(a, "ar-button").waitFor();
    assert.equal(await tid(a, "ar-qr").count(), 0, "negative: no QR on a phone");
    const href = await tid(a, "ar-button").getAttribute("href");
    assert.match(href, /^intent:\/\/arvr\.google\.com\/scene-viewer\/1\.0\?file=http/);
    assert.ok(href.includes(encodeURIComponent(`http://127.0.0.1:${port}/tests/part7/harness/api/take-ar/dGVzdA.c2ln`)), "the link carries the signed address");
    assert.deepEqual(a.signed, [{ who: "trainer", kind: "glb" }], "one signing request, for the trainer's GLB");
    assert.equal((await tid(a, "ar-button").textContent()).trim(), "See it in your room");
    await tid(a, "heat-toggle").click();
    await tid(a, "heat-legend").waitFor({ state: "visible" });
    const o = await overflow(a);
    assert.ok(o.scroll <= o.vw, `${width}: the page is not wider than the screen (${o.scroll} > ${o.vw})`);
    assert.deepEqual(o.wide, [], `${width}: nothing in the tools leaves the screen`);
    for (const id of ["heat-toggle", "heat-reopen", "ar-button"]) {
      const box = await tid(a, id).boundingBox();
      assert.ok(box.height >= 44, `${width}: ${id} is a 44 px target (${box.height})`);
    }
    await axe(a, `android ${width}`);
    await tid(a, "summary-mesh").screenshot({ path: path.join(SHOTS, `heat-ar-android-${width}.png`) });
    ok(`android ${width}: AR button with the Scene Viewer link, no QR, tools inside the screen, 44 px targets, axe clean`);
  }

  // ---- iPhone: Quick Look ---------------------------------------------------------------------------------------
  const i = await open("iphone", { device: "iphone" });
  await tid(i, "ar-button").waitFor();
  assert.equal(await tid(i, "ar-button").getAttribute("rel"), "ar");
  assert.match(await tid(i, "ar-button").getAttribute("href"), /^http:\/\/127\.0\.0\.1:\d+\/tests\/part7\/harness\/api\/take-ar\/dGVzdA\.c2lnusdz$/);
  assert.deepEqual(i.signed, [{ who: "trainer", kind: "usdz" }]);
  assert.equal(await tid(i, "ar-button").locator("img").count(), 1, "Quick Look needs an image in the link");
  assert.equal(await tid(i, "ar-qr").count(), 0);
  ok("iPhone: Quick Look link to the USDZ");

  // ---- unsupported phone: nothing -------------------------------------------------------------------------------
  const noUsdz = await open("iphone-no-usdz", { device: "iphone", usdz: false, heat: false });
  await noUsdz.waitForTimeout(300);
  assert.equal(await tid(noUsdz, "ar-button").count() + await tid(noUsdz, "ar-qr").count(), 0, "negative: an iPhone job with no USDZ shows no AR button and no QR");
  const noGlb = await open("android-no-glb", { device: "android", glb: false, usdz: true, heat: false });
  await noGlb.waitForTimeout(300);
  assert.equal(await tid(noGlb, "ar-button").count() + await tid(noGlb, "ar-qr").count(), 0, "negative: an Android job with no GLB shows no AR button");
  ok("negative: no AR button where the device or the job has no route");

  // ---- contract S1: a failed or plain answer shows nothing -----------------------------------------------------
  for (const [sign, why] of [["fail", "the server answered 404"], ["plain", "the server answered with the job's plain path"]]) {
    for (const device of ["android", "iphone"]) {
      const p = await open(`sign-${sign}-${device}`, { device, sign, heat: false });
      await p.waitForTimeout(800);
      assert.equal(p.signed.length, 1, `${sign} ${device}: the page asked once`);
      assert.equal(await tid(p, "ar-button").count() + await tid(p, "ar-qr").count(), 0, `negative: ${device}, ${why}: no AR link`);
      assert.equal(await p.locator('a[href*="/take/"]').count(), 0, `negative: no link to the job's path anywhere (${sign} ${device})`);
    }
  }
  ok("negative: no AR link when the signing request fails or answers with a plain job path");

  // ---- no data: no controls -------------------------------------------------------------------------------------
  const none = await open("no-data", { device: "desktop", width: 1440, heat: false, glb: false, usdz: false });
  await tid(none, "summary-mesh").locator("canvas").waitFor({ timeout: 15000 });
  assert.equal(await tid(none, "stage-tools").count(), 0, "negative: no tools row");
  assert.equal(await tid(none, "heat-toggle").count(), 0, "negative: no Heat control without heat data");
  assert.equal(await tid(none, "ar-qr").count() + await tid(none, "ar-button").count(), 0, "negative: no AR control without files");
  ok("negative: a job with no heat file and no AR files shows neither control");

  assert.deepEqual(external, [], "no request left this machine (the QR code is made locally)");
  assert.deepEqual(errors, [], "no console errors");
  console.log(`# ${passed} groups passed`);
} finally {
  await browser.close();
  server.close();
}
