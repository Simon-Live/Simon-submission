// The server's legal pages read for the app's theme (web/model/legal-server.js). A made-up page with every feature the
// real pages use: title, "Last updated", sections, links, a Cloudflare-hidden address, bold, code, lists and a table.
import test from "node:test";
import assert from "node:assert/strict";
import { parseLegalHtml, decodeCfEmail, mapHref, SERVER_PAGES, LEGAL_UNAVAILABLE } from "../../web/model/legal-server.js";

const hide = (email, key = 0x5a) => key.toString(16).padStart(2, "0") + [...email].map((c) => (c.charCodeAt(0) ^ key).toString(16).padStart(2, "0")).join("");
const PAGE = `<!doctype html><html><head><title>Example | Simon</title></head><body class="legal">
<header class="legal-head"><a href="./#/">Back to Simon</a></header>
<main id="legal-main" class="legal-main" data-testid="legal-privacy">
<h1>Privacy policy</h1>
<p>Last updated 4 November 2026.</p>
<p>Before any heading.</p>
<h2>Who runs Simon</h2>
<p>Run by Example LLC. Write to <a href="/cdn-cgi/l/email-protection#${hide("hello@simon.live")}"><span class="__cf_email__" data-cfemail="${hide("hello@simon.live")}">[email&#160;protected]</span></a>.</p>
<ul><li><strong>Your video.</strong> Each take&#x27;s video.</li><li>See <a href="sub-processors">Who processes your data</a>.</li></ul>
<h2>Who else receives it</h2>
<table><thead><tr><th>Recipient</th><th>What</th></tr></thead><tbody><tr><td>Modal</td><td>your <code>video.mp4</code></td></tr></tbody></table>
<p>Read <a href="https://example.com/terms">their terms</a>.<script>alert(1)</script></p>
</main></body></html>`;

test("the six server pages are the legal ones", () => {
  assert.deepEqual(SERVER_PAGES, ["privacy", "terms", "accessibility", "biometric", "dmca", "sub-processors"]);
});

test("a Cloudflare-hidden address is decoded; a bad one is empty", () => {
  assert.equal(decodeCfEmail(hide("hello@simon.live")), "hello@simon.live");
  assert.equal(decodeCfEmail("zz"), "");
  assert.equal(decodeCfEmail(undefined), "");
});

test("links go to the app's pages, a decoded mail link or the web; anything else stays text", () => {
  assert.equal(mapHref("sub-processors"), "#/sub-processors");
  assert.equal(mapHref("./terms"), "#/terms");
  assert.equal(mapHref(`/cdn-cgi/l/email-protection#${hide("a@b.co")}`), "mailto:a@b.co");
  assert.equal(mapHref("https://example.com/x"), "https://example.com/x");
  assert.equal(mapHref("javascript:alert(1)"), null, "negative: no script links");
  assert.equal(mapHref("../../etc"), null);
});

test("the page: title, last update, sections, contents, bold, code, lists, a table, links; no script", () => {
  const p = parseLegalHtml(PAGE, "privacy");
  assert.equal(p.title, "Privacy policy");
  assert.equal(p.updated, "Last updated 4 November 2026");
  assert.deepEqual(p.sections.map((s) => s.heading), ["", "Who runs Simon", "Who else receives it"]);
  assert.deepEqual(p.contents.map((c) => c.heading), ["Who runs Simon", "Who else receives it"]);
  const who = p.sections[1].body;
  assert.ok(who[0].some((x) => x.href === "mailto:hello@simon.live" && x.text === "hello@simon.live"), "the hidden address, decoded");
  assert.deepEqual(who[1].list[0][0], { strong: "Your video." });
  assert.ok(who[1].list[0].includes(" Each take's video."), "entities decoded");
  assert.deepEqual(who[1].list[1][1], { text: "Who processes your data", href: "#/sub-processors" });
  const table = p.sections[2].body[0].table;
  assert.equal(table.head.length, 2);
  assert.deepEqual(table.rows[0][1], ["your ", { code: "video.mp4" }]);
  assert.ok(!JSON.stringify(p).includes("alert(1)"), "negative: nothing from a script tag");
});

test("no legal main, or no title: null, and the app says the page did not load", () => {
  assert.equal(parseLegalHtml("<html><body><p>hi</p></body></html>", "terms"), null);
  assert.equal(parseLegalHtml("<main><p>no title</p></main>", "terms"), null);
});

test("the failure words hold no legal text and no dash", () => {
  assert.doesNotMatch(JSON.stringify(LEGAL_UNAVAILABLE), /[\u2013\u2014]| - |privacy|terms|consent/i);
});
