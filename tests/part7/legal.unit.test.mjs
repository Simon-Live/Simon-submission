// Unit tests for model/legal.js: About us, Health and safety, and the legal stand-ins for simon.live (team,
// 2026-11-03), until the go-live work's lawyer-reviewed pages (part7/legal_pages.py) replace them. `node --test`.
import test from "node:test";
import assert from "node:assert/strict";
import { PAGES, LEGAL_ROUTES, legalPage, CONTACT, TEAM, FOOTER_COLUMNS, STANDIN_NOTICE, OPERATOR, COPYRIGHT } from "../../web/model/legal.js";
import { NOTE } from "../../web/consent.js";
import { CONSENT_LINES } from "../../web/model/me.js";

const words = (page) => JSON.stringify(page);
const hrefs = (x, out = []) => {
  if (Array.isArray(x)) x.forEach((y) => hrefs(y, out));
  else if (x && typeof x === "object") { if (typeof x.href === "string") out.push(x.href); Object.values(x).forEach((y) => hrefs(y, out)); }
  return out;
};
const STANDINS = ["privacy", "terms", "accessibility", "biometric", "dmca", "sub-processors"];   // the go-live page names

test("ten pages, each with a title, a lead, the last update and its own section ids", () => {
  assert.deepEqual(LEGAL_ROUTES, ["about", "mission", "guide", "safety", ...STANDINS]);
  for (const key of LEGAL_ROUTES) {
    const p = legalPage(key);
    assert.ok(p.title && p.lead && /^Last updated \d{1,2} \w+ \d{4}$/.test(p.updated), key);
    const ids = p.sections.map((s) => s.id);
    assert.equal(new Set(ids).size, ids.length, `${key}: section ids are unique`);
  }
  assert.equal(legalPage("nope"), null, "negative: an unknown page");
});

test("the legal pages are stand-ins that say so; About and Health and safety are not", () => {
  for (const key of STANDINS) assert.equal(legalPage(key).notice, STANDIN_NOTICE, key);
  for (const key of ["about", "mission", "guide", "safety"]) assert.equal(legalPage(key).notice, null, key);
});

test("the team in the team's order, and the one contact address", () => {
  assert.deepEqual(TEAM, ["Mo Alborati", "Shruti Doshi"]);
  assert.ok(words(PAGES.about).includes("Mo Alborati and Shruti Doshi"));
  assert.equal(OPERATOR, "Simon Live LLC");
  assert.equal(COPYRIGHT, "© 2026 Simon Live LLC");
  const mails = [...new Set(LEGAL_ROUTES.flatMap((k) => hrefs(PAGES[k])).filter((h) => h.startsWith("mailto:")))];
  assert.deepEqual(mails, [`mailto:${CONTACT}`]);
});

test("only the legal facts the team confirmed: New York law in the Terms, Simon Live LLC; no address or licence name", () => {
  const all = LEGAL_ROUTES.map((k) => words(PAGES[k])).join(" ");
  for (const never of ["California", "MIT", "Apache", "Street", "shall"]) assert.ok(!all.includes(never), never);
  // New York law, confirmed by the team (2026-11-04), is stated once: in the Terms
  const law = LEGAL_ROUTES.filter((k) => words(PAGES[k]).includes("governed by"));
  assert.deepEqual(law, ["terms"]);
  assert.match(words(PAGES.terms), /laws of the State of New York/);
  // the one company name is the operator the team confirmed (2026-11-04)
  assert.deepEqual([...new Set(all.match(/(?:\b[A-Z]\w* )+LLC\b/g) || [])], ["Simon Live LLC"]);
  assert.ok(words(PAGES.safety).includes("not medical or professional advice"));
});

test("the stand-ins say what the app says: 7 days, 90 days kept, Meta's API, Delete my data", () => {
  const app = [...NOTE, ...CONSENT_LINES].join(" ");
  for (const fact of ["7 days", "90 days", "Meta's", "Delete my data", "cannot undo"]) assert.ok(app.includes(fact), `the app says ${fact}`);
  const privacy = words(PAGES.privacy);
  for (const fact of ["7 days", "90 days", "Meta's Model API", "Delete my data", "cannot undo"]) assert.ok(privacy.includes(fact), fact);
  assert.ok(words(PAGES.terms).includes("16 and older"));
  assert.ok(words(PAGES["sub-processors"]).includes("Baseten"));
});

test("links stay in the app or go to the one contact address; the footer opens every legal page", () => {
  const ok = (h) => h.startsWith("#/") || h.startsWith("api/") || h === `mailto:${CONTACT}`;
  for (const key of LEGAL_ROUTES) for (const h of hrefs(PAGES[key])) assert.ok(ok(h), `${key}: ${h}`);
  const links = FOOTER_COLUMNS.flatMap((c) => c.links);
  for (const l of links) assert.ok(ok(l.href), l.href);
  for (const key of [...LEGAL_ROUTES, "whitepaper", "notices"]) assert.ok(links.some((l) => l.href === `#/${key}`), `the footer links ${key}`);
  assert.ok(!links.some((l) => l.label === "Your data"), "negative: no Your data link (team, 2026-11-03)");
  const legal = FOOTER_COLUMNS.find((c) => c.title === "Legal").links;
  assert.deepEqual(legal.slice(0, 3).map((l) => l.testid), ["footer-link-privacy", "footer-link-terms", "footer-link-accessibility"],
    "the go-live pages' test ids first");
});

test("the how-to guide: a follower's 14 steps and a trainer's 7, numbered, and the footer links to it", () => {
  const g = legalPage("guide");
  assert.equal(g.title, "How to use Simon");
  const steps = (id) => g.sections.find((s) => s.id === id).body.find((b) => b && b.steps).steps;
  assert.equal(steps("follow").length, 14);
  assert.equal(steps("trainer").length, 7);
  assert.match(steps("follow").join(" "), /Use routine.*Live check.*Learn in sections.*Analyse my take.*Retry set.*Delete this take/);
  assert.match(steps("trainer").at(-1), /class handout with a QR code/);
  assert.ok(FOOTER_COLUMNS[0].links.some((l) => l.href === "#/guide" && l.label === "How to use"));
});
