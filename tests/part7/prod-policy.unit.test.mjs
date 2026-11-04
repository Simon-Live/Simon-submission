// The #415 switches in the web, the consent store, captions and the AI label (docs/specs/consent-and-age.md,
// trainer-publish.md, legal-pages.md).   node --test tests/part7/prod-policy.unit.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";

const policy = await import("../../web/policy.js");
const store = await import("../../web/model/consent-store.js");
const text = await import("../../web/model/consent-text.js");
const { toVtt } = await import("../../web/model/captions.js");
const { impactView } = await import("../../web/model/impact.js");
const { AI_LABEL, faultLine } = await import("../../web/model/fault-line.js");

const mem = () => { const m = new Map(); return { getItem: (k) => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)) }; };
const ALL = Object.fromEntries(text.CONSENT_TEXT.items.map((i) => [i.key, true]));
const prodDoc = (over = {}) => ({ prod: true, switches: Object.fromEntries(policy.SWITCHES.map((k) => [k, false])), phrasing_live: false,
  consent: { required: true, version: text.CONSENT_VERSION, items: Object.keys(ALL), header: store.HEADER }, ...over });

test("AC-CA7 before a load every switch is on; a failed load closes every switch and requires consent", async () => {
  policy.resetPolicy();
  assert.ok(policy.SWITCHES.every((s) => policy.policyOn(s)));
  assert.equal(policy.consentPolicy().required, false);
  await policy.loadPolicy(async () => { throw new Error("404"); });
  assert.ok(policy.SWITCHES.every((s) => !policy.policyOn(s)), "fail closed");
  assert.equal(policy.consentPolicy().required, true);
  assert.equal(policy.phrasingLive(), false);
  policy.setPolicy({ junk: 1 });
  assert.equal(policy.policyOn("rehab"), false);
  policy.setPolicy(prodDoc({ switches: { ...prodDoc().switches, rehab: true } }));
  assert.equal(policy.policyOn("rehab"), true);
  assert.equal(policy.policyOn("face_copy"), false);
  assert.equal(policy.policyOn("not-a-switch"), false);
  policy.resetPolicy();
});

test("AC-CA1 the browser counts the age to the month like the server, the birthday month not yet reached", () => {
  const now = new Date("2026-11-02T10:00:00Z");
  assert.equal(store.ageBand(2013, 11, now), "under13");
  assert.equal(store.ageBand(2013, 10, now), "minor");
  assert.equal(store.ageBand(2008, 11, now), "minor");
  assert.equal(store.ageBand(2008, 10, now), "adult");
});

test("AC-CA8 the job fields and the upload header carry a current, complete answer only", () => {
  const s = mem();
  assert.deepEqual(store.consentFields(s), {});
  assert.deepEqual(store.consentHeader(s), {});
  store.saveAge("minor", s);
  assert.deepEqual(store.consentFields(s), {}, "an age answer alone is not consent");
  store.saveConsent(ALL, s, "2026-11-02T10:00:00Z");
  assert.deepEqual(store.consentFields(s), { consent: { version: text.CONSENT_VERSION, items: ALL, at: "2026-11-02T10:00:00Z", account: "" }, age_band: "minor" });
  assert.deepEqual(store.consentHeader(s), { "X-Simon-Consent": text.CONSENT_VERSION });
  s.setItem(store.KEY, JSON.stringify({ ...JSON.parse(s.getItem(store.KEY)), version: "2020-01-01.1" }));
  assert.deepEqual(store.consentFields(s), {}, "a stale version is asked again");
  store.saveAge("under13", s);
  assert.ok(store.isBlocked(store.loadAnswers(s)));
  assert.deepEqual(store.consentFields(s), {});
  assert.deepEqual(store.consentFields({ getItem: () => { throw new Error("blocked"); } }), {});
});

test("AC-CA9 every consent point is its own unticked box; the words name what is taken and where it goes", () => {
  const t = text.CONSENT_TEXT;
  assert.deepEqual(t.items.map((i) => i.key), ["analysis", "biometric", "processors", "people_in_frame"]);
  assert.match(t.extracted.join(" "), /3D body mesh/);
  // a11y-copy B1, B2, B4, B6: the prod facts. No Meta (prod reads no operator model key), every take in Simon's Modal
  // workspace, AI named, a trainer's movement kept until deleted, a public movement shares skeleton and animation.
  const { phrasingLive: _live, metaTitle: _title, metaGoes, metaItem, ...prodWords } = t; // shown only where the Muse switch is on (muse-prod.md)
  const words = JSON.stringify(prodWords);
  assert.doesNotMatch(words, /Meta|Serverless|written out/, "only the optional Meta block names Meta");
  assert.match(metaGoes.join(" "), /no time limit/); assert.match(metaGoes.join(" "), /stays at Meta/); assert.equal(metaItem.key, "meta");
  assert.match(t.goes.join(" "), /every take runs in Simon's Modal workspace/);
  assert.match(t.goes.join(" "), /AI models/);
  assert.match(t.goes[0], /Modal.*write down the speech of a trainer recording/); // privacy PM-R9
  assert.match(text.AGE_TEXT.why, /movement.*on your account/); // PM-R9: where the age answer is kept
  assert.match(t.goes.join(" "), /show to everyone.*skeleton and animation/);
  assert.match(t.goes.join(" "), /show to everyone.*its sound when captions were made.*spoken cues/); // review B1
  assert.match(t.extracted.join(" "), /take is kept on this server for 7 days.*movement you record as a trainer is kept until you delete it/);
  assert.match(t.items.find((i) => i.key === "analysis").label, /with AI in Simon's Modal workspace/);
  assert.ok((words.match(/7 days/g) || []).length <= 2, "no figure repeated more than twice");
  assert.match(t.items.find((i) => i.key === "biometric").label, /biometric data.*consumer health data.*never to identify me/);
  assert.match(t.lede, /Simon Live LLC/); // AC-CA17
  assert.match(t.extracted.join(" "), /points on the face.*head, face and hands/);
  assert.match(t.withdraw, /withdraw.*Delete my data.*privacy@simon\.live/);
  assert.equal(text.allTicked({ ...ALL, processors: false }), false);
  assert.deepEqual(t.policyLinks.map((l) => l.href), ["privacy", "biometric", "terms"]);
  const all = JSON.stringify({ t, a: text.AGE_TEXT });
  assert.ok(!/[\u2013\u2014]| - /.test(all), "no em dash, en dash or spaced hyphen");
  assert.doesNotMatch(text.AGE_TEXT.question + text.AGE_TEXT.why, /13|18|under|over/, "the age question is neutral");
});

test("LEG-M8 captions: WebVTT from the trainer's cues, escaped, in time order; none without cues", () => {
  const vtt = toVtt({ cues: [{ start_s: 3.5, end_s: 4.25, text: "Arms <up> --> now" }, { start_s: 0, end_s: 1, text: "Ready" }, { start_s: 2, end_s: 1, text: "bad" }] });
  assert.equal(vtt, "WEBVTT\n\n1\n00:00:00.000 --> 00:00:01.000\nReady\n\n2\n00:00:03.500 --> 00:00:04.250\nArms &lt;up&gt; --&gt; now\n");
  assert.equal(toVtt({ cues: [] }), null);
  assert.equal(toVtt(null), null);
});

test("LEG-H3 the injury persona leaves the Impact page when rehab is off", () => {
  assert.ok(impactView(null).some((p) => p.id === "home-rehab"));
  assert.ok(!impactView(null, { rehab: false }).some((p) => p.id === "home-rehab"));
});

test("AI output is labelled: a live line gets the AI label, a template line does not", () => {
  const analysis = { faults: [{ text: "Lift the arm." }, { text: "Bend less." }],
    phrasing: { faults: [{ backend: "muse-spark", text: "Raise your left arm higher." }, { backend: "template", text: "x" }] } };
  assert.equal(AI_LABEL, "Worded by AI");
  assert.equal(faultLine(analysis, 0).live, true);
  assert.equal(faultLine(analysis, 1).live, false);
  const result = fs.readFileSync(new URL("../../web/result.js", import.meta.url), "utf8");
  assert.match(result, /if \(line\.live\) meta\.append\(el\("span", \{ class: "sr-chip sr-ai", "data-testid": `fault-\$\{i\}-ai`, text: AI_LABEL \}\)\)/);
});

test("LIC-H5 and LEG-H2: Live check and the fonts load from this site only", async () => {
  const live = await import("../../web/live-check.js").catch(() => null);
  const src = fs.readFileSync(new URL("../../web/live-check.js", import.meta.url), "utf8");
  assert.doesNotMatch(src, /cdn\.jsdelivr|storage\.googleapis/);
  if (live) {
    assert.match(live.VISION, /\/web\/vendor\/mediapipe$/);
    assert.match(live.MODEL, /\/web\/vendor\/mediapipe\/models\/pose_landmarker_lite\.task$/);
  }
  const fonts = fs.readFileSync(new URL("../../web/theme/fonts.css", import.meta.url), "utf8");
  const urls = [...fonts.matchAll(/url\("([^"]+)"\)/g)].map((m) => m[1]);
  assert.equal(urls.length, 10);
  for (const u of urls) assert.ok(fs.existsSync(new URL(`../../web/theme/${u}`, import.meta.url)), u);
});
