// The owner's Share dialog preview (web/views/share.js, docs/specs/share.md "Ticks") against a tiny fake DOM and a
// recorded fetch. QA share-link-take-create on release 20 saw "Your result" and no faults in the dialog while the viewer
// showed the movement name and three faults: the dialog drew a local placeholder first. Now it asks the server on open,
// draws only the server's snapshot, and says loading, server or failed in data-preview.
//   node --test tests/part7/share-preview.dom.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { installDom, El, all, find } from "./fake-dom.mjs";

installDom();
const SNAP = { kind: "take_result", title: "Lateral raise", score: 52, grade: "F", on: "2026-11-02", author: null,
  attribution: { kind: "take", author: null, trainer_credit: null, mine: false }, include: { score: true, faults: true },
  faults: ["right elbow bent more than the example", "arms not raised far enough forward"], clip: null, clip_included: false };
const sent = [];
let answer = () => ({ status: 200, body: SNAP });
let gate = null; // when set, the preview answer waits for gate.open()
globalThis.fetch = async (url, init = {}) => {
  const path = String(url);
  if (path.endsWith("api/auth/me")) return reply(200, { available: true, signed_in: true });
  if (path.endsWith("api/shares/preview")) {
    sent.push(JSON.parse(init.body));
    if (gate) await gate.wait;
    const a = answer(JSON.parse(init.body));
    return reply(a.status, a.body);
  }
  return reply(404, {});
};
function reply(status, body) { return { status, json: async () => body, headers: { get: () => null } }; }
function hold() { let open; const wait = new Promise((r) => { open = r; }); return { wait, open }; }
const { mountShareAction } = await import("../../web/share.js");
const settle = () => new Promise((r) => setTimeout(r, 20));
const texts = (n) => all(n).filter((x) => x instanceof El && x._text !== null).map((x) => x._text);

async function openDialog() {
  const slot = new El("div");
  const stop = mountShareAction(slot, { job: "03636841a269", analysis: { score: { value: 52, grade: "F" } } });
  await settle();
  find(slot, "share-take-open").click();
  return { slot, stop, preview: () => find(slot, "share-preview") };
}

test("on open the dialog asks the server and draws its title, score and faults", async () => {
  sent.length = 0;
  answer = () => ({ status: 200, body: SNAP });
  gate = hold();
  const { preview, stop } = await openDialog();
  assert.equal(sent.length, 1, "the preview is asked for on open, before any tick changes");
  assert.equal(sent[0].kind, "take_result");
  assert.equal(sent[0].item_ref, "03636841a269");
  assert.equal(preview().getAttribute("data-preview"), "loading");
  assert.equal(find(preview(), "shared-title"), null, "negative: no title is drawn before the server answers");
  assert.ok(!texts(preview()).includes("Your result"), "negative: the old placeholder never shows");
  gate.open();
  await settle();
  gate = null;
  assert.equal(preview().getAttribute("data-preview"), "server");
  assert.equal(find(preview(), "shared-title").textContent, "Lateral raise");
  assert.equal(find(preview(), "shared-score").textContent, "52 F");
  assert.deepEqual(find(preview(), "shared-faults").children.map((li) => li.textContent), SNAP.faults);
  assert.ok(!texts(preview()).includes("Your result"), "negative: the placeholder is not drawn after the answer either");
  stop();
});

test("a tick change asks again and draws the new snapshot, never a local one", async () => {
  sent.length = 0;
  answer = (b) => ({ status: 200, body: b.include_faults === false ? { ...SNAP, faults: undefined, include: { score: true, faults: false } } : SNAP });
  const { slot, preview, stop } = await openDialog();
  await settle();
  const faultsBox = find(slot, "share-faults");
  faultsBox.checked = false;
  faultsBox.dispatchEvent(new Event("change"));
  await settle();
  assert.equal(sent.length, 2);
  assert.equal(sent[1].include_faults, false);
  assert.equal(preview().getAttribute("data-preview"), "server");
  assert.equal(find(preview(), "shared-faults"), null, "unticked faults are not in the preview");
  assert.equal(find(preview(), "shared-title").textContent, "Lateral raise", "the title stays the server's");
  stop();
});

test("when the server cannot answer, the preview says so and draws no result", async () => {
  answer = () => ({ status: 500, body: null });
  const { preview, stop } = await openDialog();
  await settle();
  assert.equal(preview().getAttribute("data-preview"), "failed");
  assert.equal(find(preview(), "share-preview-status").textContent, "The preview did not load. Close this and open Share again to see it.");
  assert.equal(find(preview(), "shared-title"), null, "negative: no title of its own");
  assert.equal(find(preview(), "shared-score"), null, "negative: no score of its own");
  stop();
});

test("a refusal shows the server's reason", async () => {
  answer = () => ({ status: 400, body: { ok: false, message: "This take has no kept clip to share." } });
  const { preview, stop } = await openDialog();
  await settle();
  assert.equal(preview().getAttribute("data-preview"), "failed");
  assert.equal(find(preview(), "share-preview-status").textContent, "This take has no kept clip to share.");
  stop();
});
