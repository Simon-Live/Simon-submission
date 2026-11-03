// Unit tests for model/legal.js: About us, Health and safety, and the legal stand-ins for simon.live (team,
// 2026-11-03), until the go-live work's lawyer-reviewed pages (part7/legal_pages.py) replace them. `node --test`.
import test from "node:test";
import assert from "node:assert/strict";
import { PAGES, LEGAL_ROUTES, legalPage, CONTACT, TEAM, FOOTER_COLUMNS, STANDIN_NOTICE } from "../../web/model/legal.js";
import { NOTE } from "../../web/consent.js";
import { CONSENT_LINES } from "../../web/model/me.js";

const words = (page) => JSON.stringify(page);
const hrefs = (x, out = []) => {
  if (Array.isArray(x)) x.forEach((y) => hrefs(y, out));
  else if (x && typeof x === "object") { if (typeof x.href === "string") out.push(x.href); Object.values(x).forEach((y) => hrefs(y, out)); }
  return out;
};
const STANDINS = ["privacy", "terms", "accessibility", "biometric", "dmca", "sub-processors"];   // the go-live page names

test("eight pages, each with a title, a lead, the last update and its own section ids", () => {
  assert.deepEqual(LEGAL_ROUTES, ["about", "safety", ...STANDINS]);
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
  for (const key of ["about", "safety"]) assert.equal(legalPage(key).notice, null, key);
});

test("the team in the team's order, and the one contact address", () => {
  assert.deepEqual(TEAM, ["Mo Alborati", "Shruti Doshi"]);
  assert.ok(words(PAGES.about).includes("Mo Alborati and Shruti Doshi"));
  const mails = [...new Set(LEGAL_ROUTES.flatMap((k) => hrefs(PAGES[k])).filter((h) => h.startsWith("mailto:")))];
  assert.deepEqual(mails, [`mailto:${CONTACT}`]);
});

test("no legal fact the operator has not confirmed: no governing law, company, address or licence name", () => {
  const all = LEGAL_ROUTES.map((k) => words(PAGES[k])).join(" ");
  for (const never of ["California", "governed by", "LLC", "MIT", "Apache", "Street", "shall"]) assert.ok(!all.includes(never), never);
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
  for (const key of LEGAL_ROUTES) assert.ok(links.some((l) => l.href === `#/${key}`), `the footer links ${key}`);
  const legal = FOOTER_COLUMNS.find((c) => c.title === "Legal").links;
  assert.deepEqual(legal.slice(0, 3).map((l) => l.testid), ["footer-link-privacy", "footer-link-terms", "footer-link-accessibility"],
    "the go-live pages' test ids first");
});
