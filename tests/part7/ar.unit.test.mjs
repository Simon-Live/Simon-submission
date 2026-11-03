// TICKET-282 (docs/specs/heat-and-ar.md AC-A1 to AC-A4): the AR feature check and the intent link, pure. Run:
//   node --test tests/part7/ar.unit.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { arMode, isTouchDevice, sceneViewerHref, readEnv } from "../../web/ar/ar-support.js";
import { mountArControls, AR_TEXT } from "../../web/ar/ar-ui.js";
import { acceptSigned, signedArUrl } from "../../web/ar/ar-sign.js";

const ANDROID = "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 Chrome/126.0 Mobile Safari/537.36";
const IPHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 Version/17.5 Mobile/15E148 Safari/604.1";
const IPAD_AS_MAC = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Version/17.5 Safari/605.1.15";
const DESKTOP = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36";
const FILES = { glb: "api/results/j/trainer.glb", usdz: "api/results/j/trainer.usdz" };

test("AC-A1 Android with a GLB gets Scene Viewer; iPhone and iPad with a USDZ get Quick Look", () => {
  assert.equal(arMode({ userAgent: ANDROID }, FILES), "scene-viewer");
  assert.equal(arMode({ userAgent: IPHONE, relAr: true }, FILES), "quick-look");
  assert.equal(arMode({ userAgent: IPAD_AS_MAC, maxTouchPoints: 5, relAr: true }, FILES), "quick-look");
});

test("AC-A1 no AR button where AR is unsupported (negative): desktop, a Mac without touch, iOS without the ar rel, a missing file", () => {
  assert.equal(arMode({ userAgent: DESKTOP }, FILES), null);
  assert.equal(arMode({ userAgent: IPAD_AS_MAC, maxTouchPoints: 0, relAr: true }, FILES), null);
  assert.equal(arMode({ userAgent: IPHONE, relAr: false }, FILES), null);
  assert.equal(arMode({ userAgent: IPHONE, relAr: true }, { glb: FILES.glb, usdz: null }), null, "iOS needs the USDZ");
  assert.equal(arMode({ userAgent: ANDROID }, { glb: null, usdz: FILES.usdz }), null, "Android needs the GLB");
  assert.equal(arMode({ userAgent: ANDROID }, { glb: null, usdz: null }), null);
  assert.equal(arMode({}, FILES), null);
});

test("a touch device never gets the QR fallback, a desktop does", () => {
  assert.equal(isTouchDevice({ userAgent: DESKTOP }), false);
  assert.equal(isTouchDevice({ userAgent: DESKTOP, coarse: true }), true);
  assert.equal(isTouchDevice({ userAgent: ANDROID }), true);
  assert.equal(isTouchDevice({ userAgent: IPHONE }), true);
});

test("the Scene Viewer link carries the encoded absolute GLB address and falls back to the Play Store", () => {
  const href = sceneViewerHref("https://s.example/api/results/j/trainer.glb?a=1&b=2", "Your trainer");
  assert.match(href, /^intent:\/\/arvr\.google\.com\/scene-viewer\/1\.0\?file=https%3A%2F%2Fs\.example%2Fapi%2Fresults%2Fj%2Ftrainer\.glb%3Fa%3D1%26b%3D2&mode=ar_preferred&title=Your%20trainer/);
  assert.match(href, /#Intent;scheme=https;package=com\.google\.ar\.core;action=android\.intent\.action\.VIEW;S\.browser_fallback_url=https%3A%2F%2Fplay\.google\.com/);
  assert.doesNotMatch(href, /<|"| /);
});

test("readEnv reads the page's own answers and survives a bare window", () => {
  const env = readEnv({ navigator: { userAgent: IPHONE, maxTouchPoints: 5 }, document: { createElement: () => ({ relList: { supports: (r) => r === "ar" } }) }, matchMedia: () => ({ matches: true }) });
  assert.deepEqual(env, { userAgent: IPHONE, maxTouchPoints: 5, relAr: true, coarse: true });
  assert.deepEqual(readEnv({}), { userAgent: "", maxTouchPoints: 0, relAr: false, coarse: false });
});

test("AC-A3 a job with no file kind or no link request adds nothing, whatever the device (negative)", () => {
  const env = { userAgent: ANDROID };
  const linkFor = (k) => `api/results/j/take-ar-url?who=trainer&kind=${k}`;
  assert.equal(mountArControls({}, { linkFor, kinds: [], pageUrl: "https://s.example/", env }), null);
  assert.equal(mountArControls({}, { linkFor: null, kinds: ["glb"], pageUrl: "https://s.example/", env }), null);
  assert.equal(mountArControls(null, { linkFor, kinds: ["glb"], env }), null);
});

// ---- take-ar.md signed links: api/take-ar/<token>, minutes long, never the job's path ---------------------------
const NOW = Date.parse("2026-11-02T12:00:00Z");
const BASE = "https://s.example/simon/";
const inMin = (m) => new Date(NOW + m * 60000).toISOString();
const SIGNED = (m = 5) => ({ url: "api/take-ar/eyJqIjoxfQ.bWFjMTIz", expires_utc: inMin(m) });

test("signed link: api/take-ar/<token> relative to the base path, expiring in minutes, is accepted and made absolute", () => {
  const ok = acceptSigned(SIGNED(5), NOW, BASE);
  assert.equal(ok.url, "https://s.example/simon/api/take-ar/eyJqIjoxfQ.bWFjMTIz");
  assert.equal(ok.expiresMs, NOW + 5 * 60000);
});

test("no AR link is rendered with a plain job path (negative): job paths, unsigned, expired, long-lived and malformed answers are refused", () => {
  const bad = (doc, why) => assert.equal(acceptSigned(doc, NOW, BASE), null, why);
  bad({ url: "api/results/j/take/trainer.glb", expires_utc: inMin(5) }, "the plain job path");
  bad({ url: "/api/results/j/take/trainer.glb", expires_utc: inMin(5) }, "the plain job path, rooted");
  bad({ url: "https://s.example/api/results/j/take/trainer.glb?x=1", expires_utc: inMin(5) }, "absolute job path with a query");
  bad({ url: "api/take-ar/", expires_utc: inMin(5) }, "no token");
  bad({ url: "api/take-ar/notoken", expires_utc: inMin(5) }, "a token without a mac");
  bad({ url: "api/take-ar/a.b?x=1", expires_utc: inMin(5) }, "a query on the signed path");
  bad({ url: "api/results/j/take-ar/a.b", expires_utc: inMin(5) }, "the token path under a job");
  bad({ url: "javascript:alert(1)", expires_utc: inMin(5) }, "not http");
  bad(SIGNED(-1), "already expired");
  bad(SIGNED(31), "lives longer than 30 minutes");
  bad({ ...SIGNED(), expires_utc: "soon" }, "bad expiry");
  bad({ url: SIGNED().url }, "no expiry");
  bad(null, "no answer");
});

test("signedArUrl GETs the link request with the cookie and gives null on a 404 or a failure (the button then does not appear)", async () => {
  const calls = [];
  const good = async (u, o) => { calls.push([u, o]); return { ok: true, json: async () => SIGNED(5) }; };
  const got = await signedArUrl("api/results/j/take-ar-url?who=trainer&kind=usdz", good, () => NOW, BASE);
  assert.equal(got.url.endsWith("/api/take-ar/eyJqIjoxfQ.bWFjMTIz"), true);
  assert.equal(calls[0][0], "api/results/j/take-ar-url?who=trainer&kind=usdz");
  assert.deepEqual(calls[0][1], { credentials: "same-origin" });
  assert.equal(await signedArUrl("l", async () => ({ ok: false, status: 404 }), () => NOW), null, "not allowed to view this take");
  assert.equal(await signedArUrl("l", async () => { throw new Error("offline"); }, () => NOW), null);
  assert.equal(await signedArUrl("l", async () => ({ ok: true, json: async () => { throw new Error("bad json"); } }), () => NOW), null);
});

test("AC-A2 the QR code and the feature check make no network call and use no QR service", () => {
  for (const f of ["ar/ar-support.js", "model/qr.js"]) {
    const src = fs.readFileSync(new URL(`../../web/${f}`, import.meta.url), "utf8");
    assert.doesNotMatch(src, /\bfetch\b|XMLHttpRequest|api\.qrserver|chart\.googleapis|goqr/i, f);
  }
  assert.doesNotMatch(fs.readFileSync(new URL("../../web/ar/ar-ui.js", import.meta.url), "utf8"), /api\.qrserver|chart\.googleapis|goqr/i);
  assert.doesNotMatch(Object.values(AR_TEXT).join(" "), /\u2014|\u2013| - /);
});
