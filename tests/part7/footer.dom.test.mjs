// The footer drawn into the fake DOM (docs/specs/version-footer.md, TICKET-326).   node --test tests/part7/footer.dom.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { installDom, El } from "./fake-dom.mjs";

installDom();
const { mountFooter, renderFooter } = await import("../../web/footer.js");

const SHA = "1234abcd" + "e".repeat(32);
const BUILD = { sha: SHA, short: SHA.slice(0, 9), subject: "x", committed_at: "2026-11-02T10:05:00Z",
  started_at: "2026-11-02T11:40:00Z", environment: "staging", parts: { 1: "a".repeat(9), 2: "b".repeat(9) },
  keys: "/home/gingy/.config/firm/operator-keys" };
const q = (el, id) => el.querySelector(`[data-testid="${id}"]`);
const tick = () => new Promise((r) => setTimeout(r, 0));

test("AC-F1 collapsed: environment, version and short sha in the summary; details hold the full sha", async () => {
  const el = new El("footer");
  el.hidden = true;
  assert.equal(await mountFooter(el, async () => BUILD), true);
  assert.equal(el.hidden, false);
  assert.equal(q(el, "footer-env").textContent, "Staging");
  assert.equal(q(el, "footer-sha").textContent, SHA.slice(0, 9));
  assert.equal(q(el, "footer-build-name").textContent, "Build 2026.11.02 (commit date)");
  assert.equal(q(el, "footer-build").tag, "details");
  const details = q(el, "footer-build-details").textContent;
  assert.ok(details.includes(SHA) && details.includes("Live since") && details.includes("Part 2"));
  assert.ok(!el.textContent.includes("/home") && !el.textContent.includes("[object"));
});

test("AC-F3 Copy build info puts the rows on the clipboard and says so", async () => {
  let copied = "";
  const el = renderFooter(new El("footer"), BUILD, async (t) => { copied = t; return true; });
  q(el, "footer-copy").click();
  await tick();
  assert.ok(copied.startsWith("Simon Part 7\n") && copied.includes(`Commit: ${SHA}`));
  assert.equal(q(el, "footer-copy-status").textContent, "Build info copied.");
  const failed = renderFooter(new El("footer"), BUILD, async () => false);
  q(failed, "footer-copy").click();
  await tick();
  assert.match(q(failed, "footer-copy-status").textContent, /^Copy did not work/);
});

test("AC-F4 api/version down: 'Version unavailable', links and credit still drawn, nothing thrown", async () => {
  const el = new El("footer");
  assert.equal(await mountFooter(el, async () => { throw new Error("503"); }), false);
  assert.equal(el.hidden, false);
  assert.equal(q(el, "footer-version").textContent, "Version unavailable");
  assert.equal(q(el, "footer-build"), null);
  assert.equal(q(el, "footer-copy"), null);
  assert.ok(q(el, "footer-link-licences") && q(el, "footer-link-data") && q(el, "footer-credit") && q(el, "footer-source") && q(el, "footer-feedback"));
});

test("while api/version is on its way the links show and the version slot is empty", async () => {
  const el = new El("footer");
  let release;
  const done = mountFooter(el, () => new Promise((r) => { release = r; }));
  assert.ok(q(el, "footer-version-pending") && q(el, "footer-link-how"));
  assert.equal(q(el, "footer-version"), null);
  release(BUILD);
  assert.equal(await done, true);
  assert.equal(q(el, "footer-version-pending"), null);
});

test("a missing host element is a no-op", async () => {
  assert.equal(await mountFooter(null, async () => BUILD), false);
});

test("source and feedback are plain text; the only links are app pages and the contact address", () => {
  const el = renderFooter(new El("footer"), BUILD);
  assert.equal(q(el, "footer-source").tag, "p");
  assert.equal(q(el, "footer-source").textContent, "Source: private repository (moalborati/simon-part-7-stitching-app)");
  assert.equal(q(el, "footer-feedback").tag, "p");
  assert.equal(q(el, "footer-link-source"), null);
  assert.equal(q(el, "footer-link-feedback"), null);
  const hrefs = el.querySelectorAll("[href]").map((a) => a.getAttribute("href"));
  // simon.live's footer (2026-11-03): the brand's contact, then the app, company and legal columns
  assert.deepEqual(hrefs, ["mailto:hello@simon.live", "#/", "#/record", "#/impact", "#/architecture", "#/about", "mailto:hello@simon.live",
    "#/me", "privacy", "terms", "accessibility", "#/safety", "api/notices"]);
  // the go-live pages (part7/legal_pages.py) are app paths too
  const app = (x) => x.startsWith("#/") || x.startsWith("api/") || ["privacy", "terms", "accessibility"].includes(x);
  assert.ok(hrefs.every((x) => app(x) || x === "mailto:hello@simon.live"), "negative: no outside link");
  assert.equal(q(el, "footer-copyright").textContent, "© 2026 The Simon team");
});
