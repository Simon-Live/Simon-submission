// The observations list and the language picker (docs/specs/voice.md AC-S1..S4, AC-L1..L4).
//   node --test tests/part7/second-opinion.unit.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { El, installDom, find, findAll, all } from "./fake-dom.mjs";

const dom = installDom();
const { mountSecondOpinion, observationsOf, opinionOf, verdictFor } = await import("../../web/second-opinion.js");
const { mountLangPicker, currentLang, KEY, LANGUAGES } = await import("../../web/lang-picker.js");
const ES = JSON.parse(fs.readFileSync(new URL("./fixtures/analysis/contract-c1-es.analysis.json", import.meta.url), "utf8"));

test("AC-S1 two observations render with their times and the model's name, labelled as its own view", () => {
  const sec = new El("section");
  mountSecondOpinion(sec, { analysis: ES, seek() {} });
  const items = findAll(sec, "second-opinion-0").concat(findAll(sec, "second-opinion-1"));
  assert.equal(items.length, 2);
  assert.match(items[0].textContent, /^1\.9 s/);
  assert.match(items[0].textContent, /La cabeza baja/);
  assert.match(sec.textContent, /A second opinion/);
  assert.match(sec.textContent, /muse-spark-1\.3 looked at the clip on its own/);
  assert.match(sec.textContent, /does not change your score/);
});

test("AC-S2 tapping an observation seeks to its time", () => {
  const sec = new El("section");
  const seeks = [];
  mountSecondOpinion(sec, { analysis: ES, seek: (t) => seeks.push(t) });
  find(sec, "second-opinion-1").click();
  assert.deepEqual(seeks, [0.9]);
});

test("AC-S3 absent, fallback and skipped second opinions render nothing", () => {
  for (const mutate of [(a) => delete a.second_opinion, (a) => { a.second_opinion.status = "fallback"; }, (a) => { a.second_opinion.status = "skipped"; }]) {
    const a = structuredClone(ES);
    mutate(a);
    const sec = new El("section");
    sec.append(new El("p"));
    assert.equal(mountSecondOpinion(sec, { analysis: a, seek() {} }), null);
    assert.equal(sec.children.length, 0);
  }
  assert.equal(mountSecondOpinion(null, {}), null);
});

test("AC-S4 at most two observations, and bad entries are dropped", () => {
  const a = structuredClone(ES);
  a.second_opinion.observations.push({ at_s: 2.0, text: "third" }, { at_s: "x", text: "bad" });
  assert.equal(observationsOf(a).length, 2);
  a.second_opinion.observations = [{ at_s: "x", text: "bad" }, { at_s: 1, text: " " }, { at_s: 1.2, text: "good" }];
  assert.deepEqual(observationsOf(a).map((o) => o.text), ["good"]);
  assert.equal(opinionOf({}), null);
  assert.deepEqual(verdictFor(ES, 1), { agrees: false, note: ES.second_opinion.verdicts[1].note });
  assert.equal(verdictFor(ES, 5), null);
});

test("AC-L1 the picker offers exactly the six languages MMS can speak and the writer can write", () => {
  assert.deepEqual(LANGUAGES.map((l) => l.code), ["en", "es", "fr", "ar", "hi", "pt"]);
  const box = new El("div");
  const select = mountLangPicker(box);
  assert.equal(findAll(select, "x").length, 0);
  assert.equal(select.children.length, 6);
  assert.ok(find(box, "lang-picker"));
});

test("AC-L2 nothing chosen preselects the browser's offered language (TICKET-266 AC-3), stores nothing, and sends it", async () => {
  dom.store.clear();
  const { langExtra } = await import("../../web/follow-lang.js");
  const cfg = { part5: { lang: true } };
  Object.defineProperty(globalThis, "navigator", { value: { language: "es-MX", languages: ["de-DE", "es-MX"] }, configurable: true });
  assert.equal(currentLang(), "es");
  const select = mountLangPicker(new El("div"));
  assert.equal(select.value, "es");
  assert.equal(select.children[0].textContent, "English", "a browser language is offered, so English is not the default");
  assert.equal(dom.store.get(KEY), undefined, "showing the browser's language stores nothing");
  assert.deepEqual(langExtra(cfg), { lang: "es" });
  assert.deepEqual(langExtra({ part5: { lang: false } }), {}, "negative: Part 5 cannot write it, nothing is sent");
  dom.store.set(KEY, "fr");
  assert.deepEqual(langExtra(cfg), { lang: "fr" }, "negative: a stored pick wins over the browser");
  dom.store.clear();
  for (const language of ["en-US", "de-DE", "xx", ""]) {  // English, a language not offered, junk: English (default), no lang sent
    Object.defineProperty(globalThis, "navigator", { value: { language }, configurable: true });
    const plain = mountLangPicker(new El("div"));
    assert.equal(plain.value, "en");
    assert.equal(plain.children[0].textContent, "English (default)");
    assert.deepEqual(langExtra(cfg), {}, `${language || "empty"}: nothing sent`);
  }
  Object.defineProperty(globalThis, "navigator", { value: undefined, configurable: true });
  assert.equal(currentLang(), "en");
});

test("AC-L3 a change is stored in simon.lang and is what the follow screen sends", async () => {
  dom.store.clear();
  Object.defineProperty(globalThis, "navigator", { value: { language: "de-DE" }, configurable: true });
  const select = mountLangPicker(new El("div"));
  assert.equal(select.value, "en");
  select.value = "hi";
  select.dispatchEvent(new Event("change"));
  assert.equal(dom.store.get(KEY), "hi");
  assert.equal(currentLang(), "hi");
  const { langExtra } = await import("../../web/follow-lang.js");
  assert.deepEqual(langExtra({ part5: { lang: true } }), { lang: "hi" }, "the picker value is the value sent");
  dom.store.set(KEY, "xx");
  assert.equal(currentLang(), "en", "an unsupported stored value is ignored");
  assert.deepEqual(langExtra({ part5: { lang: true } }), {});
});

test("AC-L4 blocked storage does not throw", () => {
  const saved = globalThis.localStorage;
  globalThis.localStorage = { getItem() { throw new Error("blocked"); }, setItem() { throw new Error("blocked"); } };
  const select = mountLangPicker(new El("div"));
  select.value = "fr";
  select.dispatchEvent(new Event("change"));
  assert.ok(currentLang());
  globalThis.localStorage = saved;
  assert.ok(all(new El("a")).length === 1);
});
