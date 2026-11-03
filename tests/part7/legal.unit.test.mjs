// Unit tests for model/legal.js: About us and Health and safety for simon.live (team, 2026-11-03), beside the
// go-live work's lawyer-reviewed Terms, Privacy and Accessibility pages (part7/legal_pages.py). `node --test`.
import test from "node:test";
import assert from "node:assert/strict";
import { PAGES, LEGAL_ROUTES, legalPage, CONTACT, TEAM, FOOTER_COLUMNS } from "../../web/model/legal.js";

const words = (page) => JSON.stringify(page);
const hrefs = (x, out = []) => {
  if (Array.isArray(x)) x.forEach((y) => hrefs(y, out));
  else if (x && typeof x === "object") { if (typeof x.href === "string") out.push(x.href); Object.values(x).forEach((y) => hrefs(y, out)); }
  return out;
};
const GO_LIVE = ["privacy", "terms", "accessibility"];   // served by part7/legal_pages.py, not hash routes

test("two pages, each with a title, a lead, the last update and its own section ids", () => {
  assert.deepEqual(LEGAL_ROUTES, ["about", "safety"]);
  for (const key of LEGAL_ROUTES) {
    const p = legalPage(key);
    assert.ok(p.title && p.lead && /^Last updated \d{1,2} \w+ \d{4}$/.test(p.updated), key);
    const ids = p.sections.map((s) => s.id);
    assert.equal(new Set(ids).size, ids.length, `${key}: section ids are unique`);
  }
  assert.equal(legalPage("terms"), null, "negative: the Terms are the go-live pages', not ours");
});

test("the team and the one contact address", () => {
  assert.deepEqual(TEAM, ["the team", "Mo Alborati", "Shruti Doshi"]);
  assert.ok(words(PAGES.about).includes("Mo Alborati and Shruti Doshi"));
  const mails = [...new Set(LEGAL_ROUTES.flatMap((k) => hrefs(PAGES[k])).filter((h) => h.startsWith("mailto:")))];
  assert.deepEqual(mails, [`mailto:${CONTACT}`]);
});

test("no legal fact the operator has not confirmed: no governing law, company, address or licence name", () => {
  const all = LEGAL_ROUTES.map((k) => words(PAGES[k])).join(" ");
  for (const never of ["California", "governed by", "LLC", "Inc.\"", "MIT", "Apache", "Street"]) assert.ok(!all.includes(never), never);
  assert.ok(words(PAGES.safety).includes("not medical or professional advice"), "the Terms' own words");
});

test("links stay in the app, go to the go-live pages, or to the one contact address", () => {
  const ok = (h) => h.startsWith("#/") || h.startsWith("api/") || GO_LIVE.includes(h) || h === `mailto:${CONTACT}`;
  for (const key of LEGAL_ROUTES) for (const h of hrefs(PAGES[key])) assert.ok(ok(h), `${key}: ${h}`);
  const links = FOOTER_COLUMNS.flatMap((c) => c.links);
  for (const l of links) assert.ok(ok(l.href), l.href);
  const legal = FOOTER_COLUMNS.find((c) => c.title === "Legal").links;
  assert.deepEqual(legal.slice(0, 3).map((l) => [l.href, l.testid]), GO_LIVE.map((r) => [r, `footer-link-${r}`]), "the go-live three first");
  assert.ok(links.some((l) => l.href === "#/about") && links.some((l) => l.href === "#/safety"));
});
