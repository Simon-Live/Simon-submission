// One take, one letter, part 2 (docs/specs/one-letter.md L3, L5, L6): a rank follows the shown measure, a capped take is
// never featured, a capped group says why, and the credit's S and E letters have their colours on the share card.
//   node --test tests/part7/one-letter-rank.dom.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { installDom, El, find } from "./fake-dom.mjs";

installDom();
const { shownRow, rankOf } = await import("../../web/model/score-labels.js");
const core = await import("../../web/challenge-core.js");
const actions = await import("../../web/challenge-actions.js");
const group = await import("../../web/group-result.js");
const card = await import("../../web/share-card.js");
const recap = await import("../../web/model/recap.js");

const CREDIT = { letter: "C", figures: "16,239", caption: "of 22,367", unit: "points", capped: false, warning: [], measure: 72.6 };
const CAPPED = { letter: "F", figures: "37", caption: "score out of 100", unit: "score", capped: true, warning: ["low_match"], measure: 37 };
const PLAIN50 = { letter: "F", figures: "50", caption: "out of 100", unit: "score", capped: false, warning: [], measure: 50 };
const entry = (name, score, shown, at = "2026-11-02T10:00:00Z") => ({ name, score, grade: "F", created_at: at, ...(shown ? { shown } : {}) });

test("rankOf: the shown measure, else the score", () => {
  assert.equal(rankOf({ score: 37, shown: CREDIT }), 72.6);
  assert.equal(rankOf({ score: 37, shown: CAPPED }), 37);
  assert.equal(rankOf({ score: 50 }), 50);
  assert.equal(rankOf({ score: null }), null);
  assert.equal(shownRow({ score: 37, shown: CREDIT }).measure, 72.6);
});

test("a 50 F take ranks below a 37 take shown as C at 72%; a capped take by its capped score; ties keep the earlier post", () => {
  assert.deepEqual(core.rankEntries([entry("Fifty", 50, PLAIN50), entry("Credit", 37, CREDIT, "2026-11-02T11:00:00Z")]).map((e) => e.name), ["Credit", "Fifty"]);
  assert.deepEqual(core.rankEntries([entry("Old", 50), entry("Credit", 37, CREDIT, "b")]).map((e) => e.name), ["Credit", "Old"]);
  assert.deepEqual(core.rankEntries([entry("Capped", 37, CAPPED), entry("Forty", 40, { ...PLAIN50, measure: 40 })]).map((e) => e.name), ["Forty", "Capped"]);
  assert.deepEqual(core.rankEntries([entry("Later", 37, CREDIT, "b"), entry("Earlier", 30, CREDIT, "a")]).map((e) => e.name), ["Earlier", "Later"]);
});

test("the featured pick on a share card is the best uncapped take, never a capped one", () => {
  assert.equal(actions.featuredEntry([entry("Fifty", 50, PLAIN50), entry("Credit", 37, CREDIT)]).name, "Credit");
  assert.equal(actions.featuredEntry([entry("Capped", 95, { ...CAPPED, measure: 95 }), entry("Fifty", 50, PLAIN50)]).name, "Fifty");
  assert.equal(actions.featuredEntry([entry("Capped", 37, CAPPED)]), null);
  assert.equal(actions.shareText(null, "Squat"), "Can you beat me on Squat?");   // no score is featured when every take was capped
});

test("a capped group take says why; a group where every take was capped says so once", () => {
  const people = [1, 2].map((id) => ({ id: String(id), score: 37, grade: "F", status_code: "ok", shown: CAPPED }));
  const rows = group.boardRows({ people });
  assert.equal(rows[0].capNote, "Graded F at most: this take does not closely match the trainer's movement.");
  assert.equal(group.groupCapNote(rows), "Every take here is graded F at most: these takes do not closely match the trainer's movement.");
  const mixed = group.boardRows({ people: [...people.slice(0, 1), { id: "3", score: 60, grade: "D", status_code: "ok", shown: { ...PLAIN50, measure: 60 } }] });
  assert.equal(group.groupCapNote(mixed), "");
  assert.equal(mixed[1].capNote, "");
});

test("the group result page shows the cap's reason on each capped row and once for the page", async () => {
  const people = [1, 2].map((id) => ({ id: String(id), label: `Person ${id}`, score: 37, grade: "F", status_code: "ok", faults: 0, shown: CAPPED }));
  const job = { id: "aaaaaaaaaaaa", status: "done", result: { entry_id: "squat", people } };
  const saved = globalThis.fetch;
  globalThis.fetch = async () => ({ ok: true, status: 200, headers: { get: () => "application/json" }, json: async () => job, text: async () => JSON.stringify(job) });
  const root = new El("div");
  const stop = group.mountGroupResult(root, "aaaaaaaaaaaa");
  for (let i = 0; i < 20 && !find(root, "group-board"); i++) await new Promise((r) => setTimeout(r, 5));
  stop();
  globalThis.fetch = saved;
  assert.equal(find(root, "group-cap-note").textContent, "Every take here is graded F at most: these takes do not closely match the trainer's movement.");
  assert.equal(find(root, "group-cap-1").textContent, "Graded F at most: this take does not closely match the trainer's movement.");
});

test("the share card gives the credit's S and E their theme colours", () => {
  const TOK = { "--color-accent": "#c6f35a", "--color-bad": "#ff2d95", "--color-grade-s": "#c6f35b", "--color-grade-e": "#ff2d96" };
  globalThis.document.documentElement = {};
  globalThis.getComputedStyle = () => ({ getPropertyValue: (n) => TOK[n] || "" });
  const measure = (font, text) => String(text).length * 40;
  const pill = (g) => card.layoutCard({ movement: "Squat", score: "16,239", grade: g, challenger: "Ana", url: "https://x" }, measure)
    .find((o) => o.type === "rect" && o.w === 150 && o.h === 150).fill;
  assert.equal(pill("S"), "#c6f35b");
  assert.equal(pill("E"), "#ff2d96");
  assert.equal(pill("A"), "#c6f35a");   // the team's map is unchanged
  delete globalThis.getComputedStyle;
});

test("a month record reads with the shown figures", () => {
  const v = recap.recapView({ recap: { month: "2026-11", label: "November", takes: 2, records: [{ name: "Squat", take: 2, score: 37, shown: CREDIT }] } });
  assert.deepEqual(v.records, ["Squat: new best 16,239 points of 22,367 (take 2)"]);
});
