// TICKET-368 (docs/specs/models-and-skeleton-data.md AC-D6): each fault row shows Part 5's live line when one was
// written, else the template, and the models card counts only the lines the page shows live.
// Run: node --test tests/part7/fault_line.unit.test.mjs
import test from "node:test";
import assert from "node:assert/strict";

// a tiny fake DOM, as tests/part7/models-used.dom.test.mjs, so the real card view renders in node
class Node {
  constructor() { this.children = []; }
  append(...kids) { this.children.push(...kids.filter((k) => k != null)); }
  replaceChildren(...kids) { this.children = kids; }
}
class El extends Node {
  constructor(tag) { super(); this.tag = tag; this.attrs = {}; }
  setAttribute(k, v) { this.attrs[k] = v; }
  addEventListener() {}
}
class Text extends Node { constructor(t) { super(); this.data = t; } }
globalThis.Node = Node;
globalThis.document = { createElement: (t) => new El(t), createTextNode: (t) => new Text(t) };

const { faultLine, linesShown, withLinesShown } = await import("../../web/model/fault-line.js");
const { withoutRepeatedFiller } = await import("../../web/model/filler.js");
const { modelsPanel } = await import("../../web/model/models-used.js");
const { mountModelsUsed } = await import("../../web/result-wiring.js");

// the shape of staging hero take f7f06d0bc4f3 (schema 1.13.0): faults and phrasing.faults matched by index
const TEMPLATES = ["elbows bent much more than the example at 0.3 s", "arms much too low at 0.2 s",
  "hands too close in at 0.4 s", "right knee bent slightly more than the example at 4.5 s"];
const LIVE = ["At 0.3 s, your elbows are bent much more than the example.", "Your arms are much too low at 0.2 s.",
  "Around 0.4 s your hands are too close in.", "Compared with the recording, your right knee is bent slightly more than the example at 4.5 s."];
const spark = (text) => ({ backend: "muse-spark", model: "meta-models/muse-spark-open-1026", fallback_reason: null, lang: "en", text });
const template = (text, reason) => ({ backend: "template", model: null, fallback_reason: reason, lang: "en", text });
const analysisWith = (per) => ({
  schema_version: "1.13.0",
  faults: TEMPLATES.map((t, i) => ({ text: t.replace(/ at [\d.]+ s$/, ""), text_timed: t, coaching: per[i] ? per[i].text : t, at_s: i })),
  phrasing: { requested: "muse-spark", backend: "muse-spark", model: "meta-models/muse-spark-open-1026", fallback_reason: null, lang: "en", faults: per },
});
// the models document the server wrote for that take (demos/rubric/TICKET-339), inline: the publish leaves demos/ out,
// so a test that read the file failed in CI. Only the rows and fields this test reads; the server said 4 of 4 live.
const HERO_MODELS = Object.freeze({
  job_seconds: 74.2,
  models: [
    { id: "sam31-tracking", model: "SAM 3.1", maker: "Meta", clip: "you", status: "live", seconds: 21.4, facts: { frames: 60 } },
    { id: "spark-phrasing", model: "Muse Spark", maker: "Meta", clip: "you", status: "live", seconds: 6.1,
      facts: { lines: 4, lines_live: 4 } },
  ],
});
const sparkDetail = (doc, analysis) => modelsPanel(withLinesShown(doc, analysis)).items.find((i) => i.id === "spark-phrasing");

const walk = (n, out = []) => { out.push(n); n.children.forEach((c) => walk(c, out)); return out; };
const detailOf = (section, id) => walk(section).find((n) => n.attrs && n.attrs["data-testid"] === `model-${id}-detail`);

test("AC-D6 live phrasing present: each row shows the live sentence and the card counts every one", () => {
  const a = analysisWith(LIVE.map(spark));
  assert.deepEqual(TEMPLATES.map((_, i) => faultLine(a, i).text), LIVE);
  assert.ok(TEMPLATES.every((_, i) => faultLine(a, i).live));
  assert.deepEqual(linesShown(a, "muse-spark"), { lines: 4, lines_live: 4 });
  const row = sparkDetail(HERO_MODELS, a);
  assert.equal(row.status, "live");
  assert.match(row.detail, /\b4 of 4 lines\b/);
});

test("AC-D6 live phrasing missing or fallen back: the row shows the template and the card does not count it", () => {
  const fellBack = analysisWith(LIVE.map((t, i) => template(TEMPLATES[i], "no key")));
  const missing = { ...analysisWith([]), phrasing: undefined };
  const emptyLive = analysisWith(LIVE.map(() => spark("   ")));   // a live backend with no words is not a live line
  const sparkWithReason = analysisWith(LIVE.map((t) => ({ ...spark(t), fallback_reason: "time budget spent" })));
  for (const a of [fellBack, missing, emptyLive, sparkWithReason]) {
    assert.deepEqual(TEMPLATES.map((_, i) => faultLine(a, i).text), TEMPLATES);
    assert.ok(TEMPLATES.every((_, i) => !faultLine(a, i).live && faultLine(a, i).backend === null));
    assert.deepEqual(linesShown(a, "muse-spark"), { lines: 4, lines_live: 0 });
    // negative: the server said live 4 of 4, the page shows none, so the card says the template ran instead
    const row = sparkDetail(HERO_MODELS, a);
    assert.equal(row.status, "fallback");
    assert.equal(row.detail, "Used template wording");
    assert.doesNotMatch(row.detail, /of 4 lines/);
  }
});

test("AC-D6 mixed: the count equals the rows shown live, never more (negative: the server's 4 of 4 is not repeated)", async () => {
  const per = [spark(LIVE[0]), template(TEMPLATES[1], "time budget spent"), spark(LIVE[2])];   // the fourth has no entry
  const a = analysisWith(per);
  const shown = TEMPLATES.map((_, i) => faultLine(a, i));
  assert.deepEqual(shown.map((l) => l.text), [LIVE[0], TEMPLATES[1], LIVE[2], TEMPLATES[3]]);
  const live = shown.filter((l) => l.live).length;
  assert.equal(live, 2);
  assert.deepEqual(linesShown(a, "muse-spark"), { lines: 4, lines_live: live });
  // the real card view, through the result wiring, with the server's document as loaded
  const section = await mountModelsUsed(new El("div"), "f7f06d0bc4f3", async () => HERO_MODELS, null, a);
  const text = detailOf(section, "spark-phrasing").textContent;
  assert.match(text, /\b2 of 4 lines\b/);
  assert.doesNotMatch(text, /\b[34] of 4 lines\b/);
  // a glimmer count is for local-llm lines only: Muse Spark's lines never count toward it
  assert.deepEqual(linesShown(a, "local-llm"), { lines: 4, lines_live: 0 });
});

test("the screen's filler pass works on the line the row shows, and leaves the input alone", () => {
  const a = analysisWith([spark("Bend your elbows less, nice effort."), spark("Raise your arms higher, nice effort.")]);
  const display = withoutRepeatedFiller(a);
  assert.equal(faultLine(display, 0).text, "Bend your elbows less, nice effort.");
  assert.equal(faultLine(display, 1).text, "Raise your arms higher.");
  assert.equal(faultLine(display, 2).text, TEMPLATES[2]);
  assert.equal(a.phrasing.faults[1].text, "Raise your arms higher, nice effort.");
});

test("no analysis, or a document without phrasing rows, leaves the server's models document as it was", async () => {
  assert.equal(withLinesShown(HERO_MODELS, null), HERO_MODELS);
  const other = { models: [{ id: "sam3d-you", model: "SAM 3D Body", status: "live", facts: { frames: 3 } }] };
  assert.deepEqual(withLinesShown(other, analysisWith([])), other);
  const section = await mountModelsUsed(new El("div"), "f7f06d0bc4f3", async () => HERO_MODELS);
  assert.match(detailOf(section, "spark-phrasing").textContent, /\b4 of 4 lines\b/);
});

// release 14: an insight row carries the AI label only when the fault it names (same measure, side and cue) was worded live
const live = (t) => ({ backend: "muse-spark", fallback_reason: null, lang: "en", text: t });
const tmpl = (t) => ({ backend: "template", fallback_reason: null, lang: "en", text: t });
const KNEE = [{ measure: "knee_flexion", side: "left", direction: "more", at_s: 2.0, cue: "Straighten your left knee more" },
  { measure: "knee_flexion", side: "left", direction: "less", at_s: 9.0, cue: "Bend your left knee more" }];

test("insightLine: the live line of the fault an insight names, else null (fixed text carries no label)", async () => {
  const { insightLine } = await import("../../web/model/fault-line.js");
  const faults = [{ measure: "elbow_flexion", side: "both", at_s: 0.0, text: "t0", cue: "c0" }, { measure: "foot_out", side: "both", at_s: 0.0, text: "t1", cue: "c1" }];
  const phrasing = { faults: [{ backend: "muse-spark", text: "Your elbows are far too bent.", fallback_reason: null }, { backend: "template", text: "x" }] };
  const a = { faults, phrasing };
  assert.deepEqual(insightLine(a, { measure: "elbow_flexion", side: "both", at_s: 0.0, cue: "c0" }), { text: "Your elbows are far too bent.", live: true, backend: "muse-spark" });
  assert.equal(insightLine(a, { measure: "foot_out", side: "both", at_s: 0.0, cue: "c1" }), null, "a template line: no label");
  assert.equal(insightLine(a, { measure: "tempo" }), null, "no fault of that measure");
  assert.equal(insightLine({ faults, phrasing: null }, { measure: "elbow_flexion", cue: "c0" }), null);
});

test("insightLine A: the opposite direction's live sentence does not attach", async () => {
  const { insightLine } = await import("../../web/model/fault-line.js");
  const a = { faults: KNEE, phrasing: { faults: [tmpl("x"), live("Your left knee is not bent enough at 9.0 s.")] } };
  assert.equal(insightLine(a, { measure: "knee_flexion", side: "left", at_s: 8.0, cue: "Straighten your left knee more" }), null);
});

test("insightLine B: a live sentence from another fault does not attach to a cue whose own fault was template text", async () => {
  const { insightLine } = await import("../../web/model/fault-line.js");
  const b = { faults: KNEE, phrasing: { faults: [tmpl("x"), live("Your left knee is not bent enough at 9.0 s.")] } };
  assert.equal(insightLine(b, { measure: "knee_flexion", side: "left", at_s: 8.0, cue: "Straighten your left knee more" }), null);
});

test("insightLine C: a cue whose fault was worded live carries the label even when its why is Part 5's retimed clause", async () => {
  const { insightLine } = await import("../../web/model/fault-line.js");
  const c = { faults: KNEE, phrasing: { faults: [live("Your left knee is bent too much at 2.0 s."), tmpl("x")] } };
  const got = insightLine(c, { measure: "knee_flexion", side: "left", at_s: 7.0, cue: "Straighten your left knee more", why: "Your left knee is bent too much at 7.0 s (5 of 5 reps)" });
  assert.equal(got && got.live, true);
  assert.equal(insightLine(c, { measure: "knee_flexion", side: "left", at_s: 7.0, cue: "Bend your left knee more" }), null, "its own fault is template text");
});

test("whyCarriesLive R15: the why is shown only when it holds the live clause, retimed", async () => {
  const { whyCarriesLive } = await import("../../web/model/fault-line.js");
  const liveText = "Your left knee is bent too much at 2.0 s.";
  assert.equal(whyCarriesLive("Your left knee is bent too much at 7.0 s (5 of 5 reps)", liveText), true);
  assert.equal(whyCarriesLive("Right elbow bent more than the example at 0.7 s", "Your right elbow bends far more than the trainer's."), false, "template words");
  assert.equal(whyCarriesLive(undefined, liveText), false);
  assert.equal(whyCarriesLive("anything", ""), false);
});

test("withModelFlags R16: a rep row holding its fault's live sentence exactly is flagged; fixed text and fallbacks are not", async () => {
  const { withModelFlags } = await import("../../web/model/fault-line.js");
  const sentence = "Compared with the recording, your left knee is bent too much at 7.8 s.";
  const mk = (text, cue = "Straighten your left knee more") => ({ measure: "knee_flexion", side: "left", at_s: 7.8, cue, text });
  const a = { faults: KNEE, phrasing: { faults: [live(sentence), tmpl("x")] },
    score: { timeline: [{ t_s: [0, 9], misses: [mk(sentence), mk("left knee bent slightly more than the example at 7.8 s"), mk(sentence, "Bend your left knee more"), mk("knees")] }] } };
  const got = withModelFlags(a).score.timeline[0].misses.map((m) => m.ai === true);
  assert.deepEqual(got, [true, false, false, false], "only the verbatim sentence of the right fault; no short stem matches");
  assert.equal(a.score.timeline[0].misses[0].ai, undefined, "the input is not changed");
  const es = { faults: KNEE, phrasing: { lang: "es", faults: [{ ...live("Su rodilla izquierda esta muy doblada."), lang: "es" }, tmpl("x")] },
    score: { timeline: [{ t_s: [0, 9], misses: [mk("Su rodilla izquierda esta muy doblada.")] }] } };
  assert.equal(withModelFlags(es).score.timeline[0].misses[0].ai, true, "a translated live line is still the model's");
  const fell = { faults: KNEE, phrasing: { faults: [{ ...live(sentence), fallback_reason: "timed out" }, tmpl("x")] }, score: a.score };
  assert.equal(withModelFlags(fell).score.timeline[0].misses[0].ai, undefined, "a fallback is fixed text");
  assert.equal(withModelFlags({ faults: [] }).score, undefined);
});
