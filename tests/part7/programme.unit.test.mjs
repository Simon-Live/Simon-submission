// The trainer's "Home programme" form model (web/model/programme.js, TICKET-283): who sees it, the options, the save body and
// the status line, and the copy scan of AC-3 over its words.
//   node --test tests/part7/programme.unit.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { TEXT, canSave, entryUrl, formModel, listUrl, saveBody, saveRequest, saveResult, showsForm } from "../../web/model/programme.js";
import { installDom, find } from "./fake-dom.mjs";

installDom();
const { programmeForm } = await import("../../web/views/programme-form.js");
import { bannedIn } from "../../web/model/progress-sheet.js";

const LIST = { measures: [{ name: "left_knee_flexion", label: "left knee bend" }, { name: "right_knee_flexion", label: "right knee bend" }, { name: 3 }] };

test("only the entry's author sees the form (negative: another person, signed out, no attribution)", () => {
  assert.equal(showsForm({ mine: true }), true);
  assert.equal(showsForm({ mine: false }), false);
  assert.equal(showsForm(null), false);
  assert.equal(showsForm({ mine: "yes" }), false);
});

test("the options list every measure once, with Not set first and the declared one selected", () => {
  const none = formModel(LIST, null);
  assert.deepEqual(none.options.map((o) => o.value), ["", "left_knee_flexion", "right_knee_flexion"]);
  assert.equal(none.options[0].selected, true);
  assert.equal(none.options[0].disabled, true);
  assert.equal(none.current, "");
  const set = formModel(LIST, { primary_measure: "right_knee_flexion" });
  assert.deepEqual(set.options.filter((o) => o.selected).map((o) => o.text), ["right knee bend"]);
  assert.equal(set.options[0].disabled, false, "with an angle declared, Not set can be picked to clear it");
  assert.deepEqual(formModel(null, null).options.length, 1);
});

test("save sends the measure as JSON to the entry's programme", () => {
  assert.deepEqual(saveBody("left_knee_flexion"), { primary_measure: "left_knee_flexion" });
  assert.equal(entryUrl("sit to stand"), "api/programmes/sit%20to%20stand");
  assert.equal(listUrl, "api/programmes");
});

test("the status line names the saved angle or the reason it was not saved", () => {
  assert.deepEqual(saveResult(200, { label: "left knee bend" }), { ok: true, text: "Saved. Progress sheets of this movement measure the left knee bend." });
  assert.deepEqual(saveResult(401, null), { ok: false, text: TEXT.signedOut });
  assert.deepEqual(saveResult(400, { message: "Pick one of the listed joint angles." }), { ok: false, text: "Pick one of the listed joint angles." });
  assert.deepEqual(saveResult(404, null), { ok: false, text: TEXT.failed });
  assert.deepEqual(saveResult(0, null), { ok: false, text: TEXT.failed });
});

test("AC-3: no advice, judgement or medical word and no dash in the form's words", () => {
  const lines = Object.values(TEXT).map((v) => (typeof v === "function" ? v("left knee bend") : v));
  for (const line of lines) {
    assert.deepEqual(bannedIn(line), [], line);
    assert.equal(/[\u2013\u2014]| - /.test(line), false, line);
  }
});

test("Not set clears the programme with DELETE and an empty JSON body; a measure saves with PUT", () => {
  assert.deepEqual(saveRequest("wall push-up", ""), { method: "DELETE", url: "api/programmes/wall%20push-up", body: {} });
  assert.deepEqual(saveRequest("e1", "left_knee_flexion"), { method: "PUT", url: "api/programmes/e1", body: { primary_measure: "left_knee_flexion" } });
  assert.deepEqual(saveResult(200, { removed: true }), { ok: true, text: TEXT.cleared });
  assert.deepEqual(saveResult(200, { removed: false }), { ok: true, text: TEXT.cleared });
});

test("Save is offered only when the choice differs from what is stored (Not set over a declared angle counts)", () => {
  assert.equal(canSave("", "right_knee_flexion"), true);
  assert.equal(canSave("right_knee_flexion", "right_knee_flexion"), false);
  assert.equal(canSave("left_knee_flexion", "right_knee_flexion"), true);
  assert.equal(canSave("", ""), false, "negative: nothing to clear");
});

test("the form: picking Not set over a declared angle enables Save and sends the empty value (was ignored before)", async () => {
  const vm = { ...formModel(LIST, { primary_measure: "right_knee_flexion" }), canSave };
  const sent = [];
  const form = programmeForm(TEXT, vm, async (m) => { sent.push(m); return { ok: true, text: m ? TEXT.saved("x") : TEXT.cleared }; });
  const select = find(form, "programme-measure");
  const save = find(form, "programme-save");
  find(form, "programme-status").dataset = {}; // the fake DOM has no dataset
  select.value = "right_knee_flexion"; // the fake DOM does not derive value from the selected option
  select.dispatchEvent(new Event("change"));
  assert.equal(save.disabled, true, "nothing changed yet");
  select.value = "";
  select.dispatchEvent(new Event("change"));
  assert.equal(save.disabled, false);
  save.click();
  await new Promise((r) => setTimeout(r, 0));
  assert.deepEqual(sent, [""]);
  assert.equal(find(form, "programme-status").textContent, TEXT.cleared);
  assert.equal(save.disabled, true, "after the clear, Not set is what is stored");
});
