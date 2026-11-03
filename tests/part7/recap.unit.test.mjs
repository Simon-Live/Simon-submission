// Pure logic of across my movements, the recap and the plan (docs/specs/history-all.md). SEEDED answers. `node --test`.
import test from "node:test";
import assert from "node:assert/strict";
import { acrossView, joinNames, listExtras, modelView, planUrl, planView, recapUrl, recapView } from "../../web/model/recap.js";
import { buildLadder, focusIndex, loadProgress, saveProgress } from "../../web/practice.js";

const memory = () => { const d = {}; return { getItem: (k) => (k in d ? d[k] : null), setItem: (k, v) => { d[k] = String(v); }, d }; };
const cell = (id, name, takes) => ({ entry_id: id, name, status: "persistent", takes, first: { take: 1, at_s: 2, magnitude: -20.4 }, last: { take: 2, at_s: 2, magnitude: 14 } });

test("names join in plain words and urls are encoded", () => {
  assert.equal(joinNames(["Squat"]), "Squat");
  assert.equal(joinNames(["Squat", "Dance"]), "Squat and Dance");
  assert.equal(joinNames(["Squat", "Dance", "Salsa"]), "Squat, Dance and Salsa");
  assert.equal(recapUrl("2026-10"), "api/me/history/recap?month=2026-10");
  assert.equal(planUrl("a b", "00000000000a"), "api/me/history/a%20b/plan?job=00000000000a");
});

test("the across view words a row as what came up and hides single-movement rows", () => {
  const view = acrossView({ can_read: true, report: "none", entries: [{ entry_id: "a", name: "Squat", takes: 3, rehab_takes: 1, left_out: false }],
    table: [{ measure: "knee_valgus", side: "left", across: 2, entries: [cell("a", "Squat", [1, 2]), cell("b", "Dance", [1])] },
      { measure: "trunk_lean_forward", side: "center", across: 1, entries: [cell("a", "Squat", [1])] }] });
  assert.equal(view.rows.length, 1);
  assert.equal(view.rows[0].text, "Came up in Squat and Dance.");
  assert.equal(view.rows[0].cells[0].size, "20° to 14°");
  assert.equal(view.movements[0].line, "3 takes, 1 other take counted only");
  assert.equal(acrossView(null).canRead, false);
});

test("a model part shows its cites with movement names and says it failed softly", () => {
  const doc = { status: "ok", entries: [{ entry_id: "a", name: "Squat" }, { entry_id: "b", name: "Dance" }],
    observations: [{ text: "x", cites: [{ entry: "a", take: 1, at_s: 2 }, { entry: "b", take: 3, at_s: 1.25 }] }], next_focus: null };
  assert.deepEqual(modelView(doc).observations[0].cites, ["Squat, take 1 at 2 s", "Dance, take 3 at 1.3 s"]);
  assert.match(modelView({ ...doc, status: "fallback" }).reason, /only the measured table/);
  assert.equal(modelView(null), null);
});

test("the recap view for a month, an empty month and the offer", () => {
  const r = recapView({ model_state: "none", recap: { month: "2026-10", label: "October 2026", days: 4, takes: 5, movements: [{ name: "A" }, { name: "B" }], rehab_takes: 2,
    records: [{ name: "A", take: 2, score: 75 }], faults_gone: [{ name: "A", measure: "trunk_lean_forward", side: "center", take: 3 }],
    next_focus: { measure: "knee_valgus", side: "left", movements: 2, source: "fact_table" }, entries: [] } });
  assert.deepEqual(r.stats.map((s) => s.value), ["4", "5", "2"]);
  assert.equal(r.rehab, "2 more takes counted, not read.");
  assert.equal(r.focus.line, "Came up in 2 movements and is still there.");
  assert.equal(recapView({ recap: { takes: 0, month: "2025-02" } }).empty, true);
  assert.deepEqual(listExtras({ across: true, recap_offer: { month: "2026-10", label: "October 2026", takes: 1 } }),
    { across: true, recap: { href: "#/me/recap?month=2026-10", label: "Your October 2026 recap", line: "1 take" } });
  assert.deepEqual(listExtras({ across: false, recap_offer: null }), { across: false, recap: null });
});

test("the plan view and its practise step; no plan gives null", () => {
  const vm = planView({ plan: { spacing: "Come back tomorrow.", based_on: { take: 2 }, items: [{ kind: "cue", text: "a" }, { kind: "section", step: "s2@slow", text: "b" }] } }, "e1");
  assert.deepEqual(vm.practice, { entryId: "e1", step: "s2@slow" });
  assert.equal(vm.basedOn, "Based on take 2.");
  assert.equal(planView({ plan: { items: [{ kind: "cue", text: "a" }] } }, "e1").practice, null);
  assert.equal(planView({ plan: null }, "e1"), null);
});

test("progress keeps the practise focus and the ladder opens at that step", () => {
  const store = memory();
  saveProgress("e1", { v: 1, on: true, best: {}, pending: null, focus: "s2@slow" }, store);
  const progress = loadProgress("e1", store);
  assert.equal(progress.focus, "s2@slow");
  const steps = buildLadder([1, 2, 3].map((i) => ({ index: i })), 0.75);
  assert.equal(steps[focusIndex(steps, progress)].key, "s2@slow");
  assert.equal(focusIndex(steps, { ...progress, focus: "s9@full" }), -1);
  assert.equal(focusIndex(steps, { ...progress, focus: undefined }), -1);
  assert.equal("focus" in loadProgress("none", store), false);
});

test("a model result with no observations says so plainly, and one with observations does not", () => {
  const base = { status: "ok", kind: "all", entries: [{ entry_id: "a", name: "Squat" }], observations: [], next_focus: null };
  assert.equal(modelView(base).nothing, "Simon found nothing it could cite across these movements.");
  assert.equal(modelView({ ...base, kind: "recap" }).nothing, "Simon found nothing it could cite in this month's takes.");
  assert.equal(modelView({ ...base, observations: [{ text: "x", cites: [] }] }).nothing, "");
  assert.equal(modelView({ ...base, status: "fallback" }).nothing, "", "a failed call has its own fallback line");
});

test("the across view carries the server's reason when the read is off", () => {
  const off = acrossView({ can_read: false, blocked: "Nothing has come up in two movements yet, so there is nothing to read across.", entries: [], table: [] });
  assert.equal(off.canRead, false);
  assert.match(off.blocked, /nothing to read across/);
  assert.equal(acrossView({ can_read: true, blocked: null, entries: [], table: [] }).blocked, "");
});
