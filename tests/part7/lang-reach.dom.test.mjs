// Language reach (TICKET-266, Part 7 UI half): the browser's language, direction, the notes beside a language and the picker's
// accessibility hooks. Pure model plus the view against a tiny fake DOM.
//   node --test tests/part7/lang-reach.dom.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { installDom, El, find, findAll } from "./fake-dom.mjs";

installDom();
const { LANGUAGES, dirOf, fromBrowser, notesFor, NOT_REVIEWED, LICENCE_NOTE } = await import("../../web/model/lang.js");
const { langSelect } = await import("../../web/views/lang-picker.js");

test("the browser's language picks an offered code, and English or an unoffered language picks none", () => {
  assert.equal(fromBrowser({ language: "es-MX" }), "es");
  assert.equal(fromBrowser({ language: "AR-EG" }), "ar");
  assert.equal(fromBrowser({ language: "hi_IN" }), "hi");
  assert.equal(fromBrowser({ language: "de-DE", languages: ["de-DE", "pt-BR"] }), "pt", "the first offered language in the browser's list");
  assert.equal(fromBrowser({ language: "en-GB", languages: ["en-GB", "es"] }), null, "English first: nothing to send");
  for (const bad of [undefined, null, {}, { language: "" }, { language: 5 }, { language: "zz" }]) assert.equal(fromBrowser(bad), null);
});

test("only Arabic among the offered languages is right to left", () => {
  assert.deepEqual(LANGUAGES.filter((l) => dirOf(l.code) === "rtl").map((l) => l.code), ["ar"]);
  assert.equal(dirOf("hi"), "ltr");
  assert.equal(dirOf(undefined), "ltr");
});

test("Arabic and Hindi are marked not reviewed and every spoken language states the voice licence; English shows nothing", () => {
  for (const code of ["es", "fr", "ar", "hi", "pt"]) assert.deepEqual(notesFor(code), [NOT_REVIEWED, LICENCE_NOTE], code);
  assert.deepEqual(notesFor("en"), []);
  assert.deepEqual(notesFor("zz"), []);
  assert.match(LICENCE_NOTE, /CC-BY-NC 4\.0/);
  assert.match(NOT_REVIEWED, /not been reviewed by a native reader/);
});

test("the picker is a labelled native select, each option carries its own language, and the notes follow the choice", () => {
  const { box, select } = langSelect(LANGUAGES, "en", () => {}, notesFor);
  const label = box.querySelector('[for="sv-lang"]');
  assert.ok(label && label.textContent === "Language of the feedback", "a visible label tied to the select");
  assert.equal(select.tag, "select");
  assert.equal(select.getAttribute("aria-describedby"), "sv-lang-notes");
  assert.deepEqual(select.children.map((o) => o.getAttribute("lang")), LANGUAGES.map((l) => l.code));
  const notes = find(box, "lang-notes");
  assert.equal(notes.getAttribute("aria-live"), "polite");
  assert.equal(notes.id ?? notes.getAttribute("id"), "sv-lang-notes");
  assert.equal(findAll(box, "lang-note-0").length, 0, "English: no notes");
  select.value = "ar";
  select.dispatchEvent(new Event("change"));
  assert.equal(find(box, "lang-note-0").textContent, NOT_REVIEWED);
  assert.equal(find(box, "lang-note-1").textContent, LICENCE_NOTE);
  select.value = "en";
  select.dispatchEvent(new Event("change"));
  assert.equal(findAll(box, "lang-note-0").length, 0, "back to English clears them");
});

test("the picker starts with the notes of the language in effect", () => {
  const { box } = langSelect(LANGUAGES, "hi", () => {}, notesFor);
  assert.equal(find(box, "lang-note-0").textContent, NOT_REVIEWED);
  const bare = langSelect(LANGUAGES, "hi", () => {});
  assert.equal(findAll(bare.box, "lang-note-0").length, 0, "no notes function: no notes");
  assert.ok(new El("p"));
});
