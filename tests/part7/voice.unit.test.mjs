// Voice slots, second-opinion badges and moments (docs/specs/voice.md AC-V1..V9).   node --test tests/part7/voice.unit.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { El, installDom, find, findAll } from "./fake-dom.mjs";

const dom = installDom();
const { mountVoiceSlots, lineOf, langOf, voiceOn, VOICE_KEY } = await import("../../web/voice.js");
const fixture = (n) => JSON.parse(fs.readFileSync(new URL(`./fixtures/analysis/${n}.analysis.json`, import.meta.url), "utf8"));
const ES = fixture("contract-c1-es");
const EN = fixture("contract-c1-en-no-opinion");
const tick = () => new Promise((r) => setTimeout(r, 0));

class Video extends EventTarget {
  constructor() { super(); this.currentTime = 0; }
  at(t) { this.currentTime = t; this.dispatchEvent(new Event("timeupdate")); }
}
const played = [];
const spoken = [];
class FakeAudio {
  constructor(url) { this.url = url; }
  async play() { played.push(this.url); }
  pause() {}
}
globalThis.Audio = FakeAudio;
globalThis.SpeechSynthesisUtterance = class { constructor(text) { this.text = text; } };
globalThis.speechSynthesis = { speak: (u) => spoken.push(u), cancel() {} };

function rows(analysis) {
  const root = new El("section");
  analysis.faults.forEach((f, i) => {
    const row = new El("div");
    const slot = new El("div");
    slot.setAttribute("data-testid", "voice-slot");
    slot.setAttribute("data-fault-index", i);
    slot.setAttribute("data-at-s", f.at_s);
    row.append(slot);
    root.append(row);
  });
  return root;
}
function setup(analysis, { server = 200, voice = false } = {}) {
  played.length = 0; spoken.length = 0; dom.store.clear();
  if (voice) dom.store.set(VOICE_KEY, "on");
  globalThis.fetch = async (url) => {
    setup.urls.push(String(url));
    if (server === "throw") throw new TypeError("offline");
    return { status: server, blob: async () => new Blob([new Uint8Array([82, 73, 70, 70])]) };
  };
  setup.urls = [];
  const root = rows(analysis);
  const video = new Video();
  const m = mountVoiceSlots(root, { jobId: "abcdef012345", analysis, video, seek: () => {} });
  return { root, video, m };
}
setup.urls = [];

test("AC-V1 each slot gets a hear button and the lines come from phrasing.faults", () => {
  const { root } = setup(ES);
  assert.equal(findAll(root, "voice-play").length, 2);
  assert.equal(lineOf(ES, 0), "El codo derecho está más doblado que en el ejemplo.");
  assert.equal(langOf(ES), "es");
  assert.equal(langOf({}), "en");
  assert.equal(lineOf({ faults: [{ text: " plain " }] }, 0), "plain");
  assert.equal(lineOf({ faults: [] }, 3), "");
});

test("AC-V2 voice is off by default and the toggle persists in simon.voice", () => {
  const { root } = setup(ES);
  const t = find(root, "voice-toggle");
  assert.equal(voiceOn(), false);
  assert.equal(t.getAttribute("aria-pressed"), "false");
  t.click();
  assert.equal(dom.store.get(VOICE_KEY), "on");
  assert.equal(t.getAttribute("aria-pressed"), "true");
  assert.equal(t.textContent, "Voice on");
  t.click();
  assert.equal(dom.store.get(VOICE_KEY), "off");
});

test("AC-V3 the toggle goes into voice-controls when present, else on top of the root", () => {
  const withControls = rows(ES);
  const controls = new El("div");
  controls.setAttribute("data-testid", "voice-controls");
  withControls.prepend(controls);
  mountVoiceSlots(withControls, { jobId: "abcdef012345", analysis: ES, video: new Video(), seek() {} });
  assert.equal(controls.children.length, 1);
  assert.equal(findAll(withControls, "voice-controls").length, 1);
  const { root } = setup(ES);
  assert.equal(root.children[0].getAttribute("data-testid"), "voice-controls");
  assert.ok(find(root.children[0], "voice-toggle"));
});

test("AC-V4 the badge shows the model's verdict, its name and a not-scored label; the note is visible", () => {
  const { root } = setup(ES);
  const [a, b] = findAll(root, "verdict-badge");
  assert.equal(a.getAttribute("data-verdict"), "agrees");
  assert.equal(a.textContent, "muse-spark-1.3 agrees");
  assert.equal(b.getAttribute("data-verdict"), "disagrees");
  const notes = findAll(root, "verdict-note").map((n) => n.textContent);
  assert.match(notes[1], /alineados/);
  assert.match(root.textContent, /model's opinion, not scored/);
});

test("AC-V5 no second_opinion, or a status other than ok, adds no badge", () => {
  assert.equal(findAll(setup(EN).root, "verdict-badge").length, 0);
  const fallback = structuredClone(ES);
  fallback.second_opinion.status = "fallback";
  assert.equal(findAll(setup(fallback).root, "verdict-badge").length, 0);
  assert.equal(findAll(setup(fallback).root, "voice-play").length, 2);
});

test("AC-V6 a voiced pass speaks the line once at its moment, only when voice is on", async () => {
  const off = setup(ES);
  off.video.at(0.0); off.video.at(0.5);
  await tick();
  assert.equal(played.length + spoken.length, 0);
  const on = setup(ES, { voice: true });
  on.video.at(0.0); on.video.at(0.5); // crosses the 0.4 s moment (fault 1)
  await tick();
  assert.equal(played.length, 1);
  assert.match(setup.urls[0], /speech\/1\.wav$/);
  assert.equal(findAll(on.root, "voice-slot")[1].getAttribute("data-source"), "mms");
  on.video.at(0.6);
  on.video.at(0.65);
  await tick();
  assert.equal(played.length, 1, "once per pass");
  on.video.at(0.0);
  on.video.at(0.5);
  await tick();
  assert.equal(played.length, 2, "spoken again after a seek back");
});

test("AC-V6b a seek far past the moment does not speak it", async () => {
  const { video } = setup(ES, { voice: true });
  video.at(0.0);
  video.at(2.5);
  await tick();
  assert.equal(played.length, 0);
});

test("AC-V7 audio comes from the speech route; a 404 falls back to the browser voice in the line's language", async () => {
  const ok = setup(ES);
  findAll(ok.root, "voice-play")[1].click();
  await tick();
  assert.deepEqual(setup.urls, ["api/jobs/abcdef012345/speech/1.wav"]);
  assert.equal(played.length, 1);
  const miss = setup(ES, { server: 404 });
  findAll(miss.root, "voice-play")[0].click();
  await tick();
  assert.equal(played.length, 0);
  assert.equal(spoken.length, 1);
  assert.equal(spoken[0].lang, "es");
  assert.match(spoken[0].text, /codo derecho/);
  assert.equal(findAll(miss.root, "voice-play")[0].getAttribute("data-source"), "browser");
});

test("AC-V8 offline: the fetch throws, the browser voice speaks; with no speech at all nothing throws", async () => {
  const off = setup(ES, { server: "throw" });
  findAll(off.root, "voice-play")[0].click();
  await tick();
  assert.equal(spoken.length, 1);
  const saved = globalThis.speechSynthesis;
  globalThis.speechSynthesis = undefined;
  findAll(off.root, "voice-play")[0].click();
  await tick();
  assert.equal(findAll(off.root, "voice-play")[0].getAttribute("data-source"), "none");
  globalThis.speechSynthesis = saved;
});

test("AC-V9 mounting twice on one root keeps one toggle and one handle; no slot or no root is null; destroy lets it mount again", () => {
  const { root, m } = setup(ES);
  const again = mountVoiceSlots(root, { jobId: "abcdef012345", analysis: ES, video: new Video(), seek() {} });
  assert.equal(again, m);
  assert.equal(findAll(root, "voice-toggle").length, 1);
  assert.equal(findAll(root, "voice-play").length, 2); // negative: no second button in a slot
  assert.equal(mountVoiceSlots(new El("div"), { analysis: ES }), null);
  assert.equal(mountVoiceSlots(null, {}), null);
  m.destroy();
  assert.ok(mountVoiceSlots(root, { jobId: "abcdef012345", analysis: ES, video: new Video(), seek() {} }));
});

test("AC-V9b a repaint brings new slots: the second call fills them and the old toggle and listener stay single", () => {
  const { root, video, m } = setup(ES);
  const before = findAll(root, "voice-slot");
  root.querySelector('[data-testid="voice-slot"]').remove(); // the summary discarded one slot and painted a new one
  const fresh = new El("div");
  fresh.setAttribute("data-testid", "voice-slot");
  fresh.setAttribute("data-fault-index", "0");
  fresh.setAttribute("data-at-s", "1");
  before[1].parent.append(fresh);
  assert.equal(mountVoiceSlots(root, { jobId: "abcdef012345", analysis: ES, video, seek() {} }), m);
  assert.equal(findAll(fresh, "voice-play").length, 1);
  assert.equal(findAll(root, "voice-toggle").length, 1);
  assert.equal(findAll(before[1], "voice-play").length, 1); // the slot that was already filled is not filled twice
});

const REAL = JSON.parse(fs.readFileSync(new URL("./fixtures/analysis/real-part5-1.9.0-es-live.analysis.json", import.meta.url), "utf8"));

test("AC-V10 the browser voice uses the line's own language, so an English fallback line is not read in Spanish", async () => {
  const a = structuredClone(ES);
  a.phrasing.faults[0].lang = "en";
  a.phrasing.faults[1].lang = "es";
  const { root } = setup(a, { server: 404 });
  findAll(root, "voice-play")[0].click();
  await tick();
  assert.equal(spoken[0].lang, "en");
  findAll(root, "voice-play")[1].click();
  await tick();
  assert.equal(spoken[1].lang, "es");
  const { lineLang } = await import("../../web/voice.js");
  assert.equal(lineLang({ phrasing: { lang: "fr", faults: [{ text: "Bonjour." }] } }, 0), "fr");
  assert.equal(lineLang({}, 0), "en");
});

test("AC-V11 real Part 5 output: Spanish lines, the real model name, and a null model falls back to a plain name", () => {
  const { root } = setup(REAL);
  assert.equal(findAll(root, "voice-play").length, 5);
  assert.equal(findAll(root, "verdict-badge")[1].getAttribute("data-verdict"), "disagrees");
  assert.match(findAll(root, "verdict-badge")[0].textContent, /^muse-spark-1\.3 agrees/);
  const noModel = structuredClone(REAL);
  noModel.second_opinion.model = null;
  assert.match(findAll(setup(noModel).root, "verdict-badge")[0].textContent, /^The model agrees/);
});

test("R8 a slow fetch that resolves after stop() neither plays nor falls back, and stop() aborts it", async () => {
  const { makeSpeaker } = await import("../../web/voice.js");
  played.length = 0; spoken.length = 0;
  let release, signal;
  globalThis.fetch = (url, opts) => {
    signal = opts && opts.signal;
    return new Promise((r) => { release = () => r({ status: 200, blob: async () => new Blob([new Uint8Array([1])]) }); });
  };
  const sp = makeSpeaker({ jobId: "abcdef012345", analysis: ES });
  const pending = sp.speak(0);
  sp.stop();
  assert.equal(signal.aborted, true);
  release();
  assert.equal(await pending, "stopped");
  assert.equal(played.length + spoken.length, 0);
  // a newer line wins over an older slow one
  const first = sp.speak(0);
  const releaseFirst = release;
  globalThis.fetch = async () => ({ status: 200, blob: async () => new Blob([new Uint8Array([1])]) });
  const second = sp.speak(1);
  releaseFirst();
  assert.equal(await first, "stopped");
  assert.equal(await second, "mms");
  assert.equal(played.length, 1);
});

test("R9 a line that fell back to faults[i] (the English template) is spoken in en, not in phrasing.lang", async () => {
  const { lineLang } = await import("../../web/voice.js");
  const a = structuredClone(ES);
  delete a.phrasing.faults[0].text;
  a.faults[0].text = "Right elbow bent more than the example.";
  assert.equal(lineOf(a, 0), "Right elbow bent more than the example.");
  assert.equal(lineLang(a, 0), "en");
  a.phrasing.faults[0].lang = "es";
  assert.equal(lineLang(a, 0), "en", "its own lang does not apply to text from another source");
  assert.equal(lineLang(a, 1), "es");
  const { root } = setup(a, { server: 404 });
  findAll(root, "voice-play")[0].click();
  await tick();
  assert.equal(spoken[0].lang, "en");
});

test("a slot whose fault has no line gets no button", () => {
  const a = structuredClone(ES);
  a.phrasing.faults[1].text = "";
  a.faults[1].text = "";
  assert.equal(findAll(setup(a).root, "voice-play").length, 1);
});
