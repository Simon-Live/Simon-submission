// The Impact and architecture pages' words and view models (docs/specs/impact-page.md AC-I2, AC-I3, AC-I5, AC-A2).
//   node --test tests/part7/impact.unit.test.mjs
import test from "node:test";
import assert from "node:assert/strict";

const { PERSONAS, PAGE, EMPTY, LABEL, impactView } = await import("../../web/model/impact.js");
const { ARCH_PAGE, architectureView, mermaidTheme } = await import("../../web/model/architecture.js");
const { MORE_LINKS } = await import("../../web/hero.js");

const take = (job, extra = {}) => ({ job_id: job, entry_id: "lunge-1", score: 70.6, mode: "rehab",
  clip_source: { url: "https://www.pexels.com/video/1/", licence: "Pexels License" }, why_this_clip: "Legs out of frame.", ...extra });

test("four personas in order, each labelled a demo scenario", () => {
  const cards = impactView(null);
  assert.deepEqual(cards.map((c) => c.id), ["seated", "bodies", "home-rehab", "remote-class"]);
  for (const c of cards) {
    assert.equal(c.label, LABEL);
    assert.equal(c.take, null);
    assert.equal(c.empty, EMPTY.not_listed, `${c.id}: a failed answer still shows the card with its empty line`);
  }
});

test("a persona with a take links its result, scores it and names the clip's licence and source", () => {
  const cards = impactView({ personas: [{ persona: "home-rehab", take: take("a1a1a1a1a1a1"), missing: null }] });
  const c = cards.find((x) => x.id === "home-rehab");
  assert.equal(c.empty, null);
  assert.equal(c.take.href, "#/result/a1a1a1a1a1a1");
  assert.equal(c.take.score, "Scored 71 out of 100 in rehab mode.");
  assert.deepEqual(c.take.clip, { licence: "Pexels License", url: "https://www.pexels.com/video/1/" });
  assert.equal(c.take.why, "Legs out of frame.");
});

test("a take named but not on the server says so; a take without a job id or score is not a take", () => {
  const cards = impactView({ personas: [
    { persona: "seated", take: null, missing: "not_found" },
    { persona: "bodies", take: { job_id: "", score: 70 }, missing: null },
    { persona: "remote-class", take: take("b2b2b2b2b2b2", { score: "70", mode: "dance" }), missing: null },
  ] });
  assert.equal(cards[0].empty, EMPTY.not_found);
  assert.equal(cards[1].take, null);
  assert.equal(cards[3].take, null, "a string score is not shown");
});

test("a clip url that is not https is not linked; an unknown mode is not named", () => {
  const c = impactView({ personas: [{ persona: "bodies", take: take("c3c3c3c3c3c3", { mode: "space", clip_source: { url: "javascript:x", licence: "" } }) }] })[1];
  assert.equal(c.take.clip, null);
  assert.equal(c.take.score, "Scored 71 out of 100.");
});

test("every need figure links an https source; personas without a sourced figure show none", () => {
  for (const p of PERSONAS) {
    if (!p.need) continue;
    assert.match(p.need.url, /^https:\/\/\S+$/, p.id);
    assert.ok(p.need.text && p.need.source, p.id);
  }
  assert.deepEqual(PERSONAS.filter((p) => p.need).map((p) => p.id), ["home-rehab", "remote-class"]);
});

const allCopy = () => [
  ...Object.values(PAGE), ...Object.values(EMPTY), LABEL, ...Object.values(ARCH_PAGE), ...MORE_LINKS.map((l) => l.text),
  ...PERSONAS.flatMap((p) => [p.title, p.serves, p.limits, p.need ? p.need.text : ""]),
];

test("copy scan: no medical, efficacy or coaching claim, and no dash in place of punctuation", () => {
  const claims = /\b(cure[sd]?|heal(s|ing)?|treat(s|ment|ing)?|therap\w*|diagnos\w*|prevent\w*|efficac\w*|effective\w*|clinical\w*|proven|guarantee\w*|coach\w*|recover(y|s|ed)?|injury-free)\b/i;
  for (const s of allCopy()) {
    assert.doesNotMatch(s, claims, s);
    assert.doesNotMatch(s, new RegExp(`${String.fromCharCode(0x2014)}|${String.fromCharCode(0x2013)}| - `), s);
    const medical = s.match(/medical\s+\w+/i);
    if (medical) assert.match(medical[0], /^medical (claim|advice)$/i, `"medical" only in a disclaimer: ${s}`);
  }
  assert.match(PAGE.note, /demo scenarios, not results/);
  assert.match(PERSONAS.find((p) => p.id === "home-rehab").limits, /not medical advice/);
});

test("the architecture view keeps each block with its title and skips empty ones", () => {
  assert.deepEqual(architectureView(null), []);
  const v = architectureView({ diagrams: [{ title: "System", source: "flowchart LR\n a-->b" }, { title: "", source: "  " }, { source: "sequenceDiagram\n A->>B: x" }] });
  assert.deepEqual(v.map((d) => [d.id, d.title]), [["arch-diagram-0", "System"], ["arch-diagram-1", "Diagram 2"]]);
});

test("Mermaid takes its colours from the tokens and runs in strict mode", () => {
  const seen = [];
  const theme = mermaidTheme((name) => { seen.push(name); return name === "--color-accent" ? "#c6f35a" : ""; });
  assert.equal(theme.securityLevel, "strict");
  assert.equal(theme.startOnLoad, false);
  assert.deepEqual([theme.flowchart.useMaxWidth, theme.sequence.useMaxWidth], [false, false], "full size, scrolled in its box");
  assert.equal(theme.themeVariables.primaryBorderColor, "#c6f35a");
  assert.equal(theme.themeVariables.primaryColor, undefined, "an unset token leaves Mermaid's own value");
  assert.ok(seen.every((n) => n.startsWith("--")));
});

test("Home's judge view links both pages", () => {
  assert.deepEqual(MORE_LINKS.map((l) => l.href), ["#/impact", "#/architecture"]);
});
