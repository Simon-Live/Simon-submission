import test from "node:test";
import assert from "node:assert/strict";
import { createBody, expirySentence, viewModel, stateWord, DEFAULT_DAYS, TEXT } from "../../web/model/share.js";

test("a new share has name and clip off, 7 days and the confirm flag", () => {
  assert.deepEqual(createBody({ kind: "take_result", itemRef: "abc" }), { kind: "take_result", item_ref: "abc", show_name: false, show_clip: false, days: DEFAULT_DAYS, confirm: true });
});

test("a share body never asks for a clip and never unticks score or faults", () => {
  for (const kind of ["history_report", "take_result"]) {
    const body = createBody({ kind, itemRef: "x", showClip: true, includeScore: false, includeFaults: false });
    assert.equal(body.show_clip, false);
    assert.equal("include_score" in body || "include_faults" in body, false);
  }
});

test("the expiry sentence names the date", () => {
  assert.match(expirySentence("2026-11-08T10:00:00Z"), /^Anyone with this link can see this until 8 Nov 2026 or until you revoke it\.$/);
});

test("the view model hides a missing name and survives odd input", () => {
  assert.equal(viewModel({ kind: "take_result", score: 80, grade: "B" }).byline, TEXT.anonymous);
  assert.equal(viewModel({ kind: "take_result", author: "Ada" }).byline, "Shared by Ada");
  const both = viewModel({ kind: "take_result", author: "Ada", attribution: { author: { name: "Ada" } } });
  assert.equal(both.byline, TEXT.anonymous, "with an author line the byline does not repeat the name");
  const odd = viewModel({ faults: [1, "a"], takes: [{ take: 1, score: 5 }], trends: "x" });
  assert.deepEqual(odd.faults, ["a"]);
  assert.deepEqual(odd.trends, []);
  assert.equal(viewModel(null).score, null);
});

test("the preview is the server's snapshot or nothing, and the placeholder word is gone", async () => {
  const { previewSnapshot } = await import("../../web/model/share.js");
  const snap = { title: "Lateral raise", score: 52, faults: ["a"] };
  assert.equal(previewSnapshot({ ok: true, body: snap }), snap);
  for (const out of [null, { ok: false, body: snap }, { ok: true, body: null }, { ok: true, body: [] }, { ok: true, body: "x" }]) assert.equal(previewSnapshot(out), null);
  assert.equal(Object.values(TEXT).includes("Your result"), false, "negative: no placeholder title to draw");
});

test("list states read plainly", () => {
  assert.equal(stateWord({ state: "revoked" }), "Revoked");
  assert.equal(stateWord({ state: "expired" }), "Expired");
  assert.match(stateWord({ state: "active", expires_utc: "2026-11-08T10:00:00Z" }), /^Works until 8 Nov 2026$/);
});

test("the viewer model carries the attribution field for the author line, and null without one", async () => {
  const { bylines } = await import("../../web/model/attribution.js");
  const att = { kind: "take", author: { name: "Ada" }, trainer_credit: { name: "Tess" }, mine: false };
  assert.deepEqual(bylines(viewModel({ attribution: att }).attribution), { author: "Take by Ada", trainer: "Following Tess" });
  assert.deepEqual(bylines(viewModel({ author: "Ada" }).attribution), { author: null, trainer: null });
});
