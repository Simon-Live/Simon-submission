// Unit tests for model/legal.js: About us, Mission and Health and safety for simon.live (team,
// 2026-11-03); the legal pages come from part7/legal_pages.py. `node --test`.
import test from "node:test";
import assert from "node:assert/strict";
import { PAGES, LEGAL_ROUTES, legalPage, CONTACT, TEAM, OPERATOR, FOOTER_COLUMNS } from "../../web/model/legal.js";

const words = (page) => JSON.stringify(page);
const hrefs = (x, out = []) => {
  if (Array.isArray(x)) x.forEach((y) => hrefs(y, out));
  else if (x && typeof x === "object") { if (typeof x.href === "string") out.push(x.href); Object.values(x).forEach((y) => hrefs(y, out)); }
  return out;
};
const GO_LIVE = ["privacy", "terms", "accessibility", "biometric", "dmca", "sub-processors"];   // served by part7/legal_pages.py

test("five pages, each with a title, a lead, the last update and its own section ids", () => {
  assert.deepEqual(LEGAL_ROUTES, ["about", "mission", "guide", "architecture", "safety"]);
  for (const key of LEGAL_ROUTES) {
    const p = legalPage(key);
    assert.ok(p.title && p.lead && /^Last updated \d{1,2} \w+ \d{4}$/.test(p.updated), key);
    const ids = p.sections.map((s) => s.id);
    assert.equal(new Set(ids).size, ids.length, `${key}: section ids are unique`);
  }
  assert.equal(legalPage("nope"), null, "negative: an unknown page");
});

test("the go-live legal pages are not in this model: they are served from docs/legal/, and no page carries a stand-in notice", () => {
  for (const key of GO_LIVE) assert.equal(legalPage(key), null, key);
  assert.doesNotMatch(words(PAGES), /stand-in|Summary for now/i);
});

test("the team in the team's order, and the one contact address", () => {
  assert.equal(OPERATOR, "Simon Live LLC");
  assert.deepEqual(TEAM, ["Mo Alborati", "Shruti Doshi"]);
  assert.ok(words(PAGES.about).includes("Mo Alborati and Shruti Doshi"));
  const mails = [...new Set(LEGAL_ROUTES.flatMap((k) => hrefs(PAGES[k])).filter((h) => h.startsWith("mailto:")))];
  assert.deepEqual(mails, [`mailto:${CONTACT}`]);
});

test("About says what prod does: sign in to make a take, and only the models a take runs", () => {
  const about = words(PAGES.about);
  assert.ok(about.includes("You sign in with your email address to make a take"));
  for (const name of ["SAM 2.1", "SAM 3D Body", "MHR"]) assert.ok(about.includes(name), name);
  for (const never of ["no account", "SAM 3.1"]) assert.ok(!about.includes(never), never);
  assert.ok(about.includes("Muse Spark Open, on Baseten"), "muse-prod.md: About names who phrases the feedback");
});

test("no legal fact the operator has not confirmed: no governing law, address or licence name", () => {
  const all = LEGAL_ROUTES.map((k) => words(PAGES[k])).join(" ");
  for (const never of ["California", "governed by", "MIT", "Apache", "Street", "shall"]) assert.ok(!all.includes(never), never);
  assert.ok(words(PAGES.safety).includes("not medical or professional advice"));
});

test("links stay in the app or go to the one contact address; the footer opens every legal page", () => {
  const ok = (h) => h.startsWith("#/") || h.startsWith("api/") || GO_LIVE.includes(h) || h === `mailto:${CONTACT}`;
  for (const key of LEGAL_ROUTES) for (const h of hrefs(PAGES[key])) assert.ok(ok(h), `${key}: ${h}`);
  const links = FOOTER_COLUMNS.flatMap((c) => c.links);
  for (const l of links) assert.ok(ok(l.href), l.href);
  for (const key of [...LEGAL_ROUTES, "whitepaper", "notices"]) assert.ok(links.some((l) => l.href === `#/${key}`), `the footer links ${key}`);
  for (const key of GO_LIVE) assert.ok(links.some((l) => l.href === `#/${key}`), `the footer links ${key}`);
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

test("How Simon works is a public page: the eleven Meta models, how they work together, what each part does; no diagrams", () => {
  const p = legalPage("architecture");
  assert.equal(p.title, "How Simon works");
  assert.deepEqual(p.sections.map((s) => s.id), ["steps", "models", "together", "parts", "more"]);
  const models = p.sections.find((s) => s.id === "models").body.find((b) => b && b.list).list;
  assert.equal(models.length, 11);
  for (const name of ["SAM 3.1", "SAM 3D Body", "MHR", "SAM 3D Objects", "Muse Spark ", "Muse Spark Open", "Muse Glimmer", "Muse Wonder", "Muse Image", "Muse Voice Transcribe", "MMS-TTS"]) {
    assert.ok(models.some((m) => m.startsWith(name)), name);
  }
  assert.equal(p.sections.find((s) => s.id === "parts").body.find((b) => b && b.list).list.length, 7);
  const text = JSON.stringify(p);
  assert.doesNotMatch(text, /flowchart|mermaid|\.py\b|part7\//i, "negative: no diagrams or code names on a public page");
});

test("the public pages say only what prod runs: nothing off is claimed as on (licence_gates.py, DRAW_ENABLED, prod_check.py)", () => {
  const about = words(PAGES.about);
  assert.ok(about.includes("You sign in with your email address") && about.includes("YOLOX and Meta's SAM 2.1"));
  assert.ok(!about.includes("no account") && !about.includes("SAM 3.1"), "negative: About");
  const how = words(PAGES.architecture);
  assert.ok(!how.includes("SAM 3.1 finds"), "negative: SAM 3.1 does not find the people in a take");
  for (const name of ["Muse Glimmer", "Muse Image", "Muse Voice Transcribe", "MMS-TTS"]) {
    const line = PAGES.architecture.sections.find((s) => s.id === "models").body.find((b) => b && b.list).list.find((m) => m.startsWith(name));
    assert.match(line, /off on simon\.live/, name);
  }
});
