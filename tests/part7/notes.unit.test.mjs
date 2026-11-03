// Ask the trainer for a note: pure logic (web/model/notes.js), the views on a fake DOM (web/views/notes.js) and the glue
// (web/notes.js) against an in-memory fake of the routes. TICKET-237.
//   node --test tests/part7/notes.unit.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { El, installDom, all, find, findAll } from "./fake-dom.mjs";

installDom();
Object.defineProperty(El.prototype, "hidden", {
  get() { return "hidden" in this.attrs; },
  set(v) { if (v) this.attrs.hidden = ""; else delete this.attrs.hidden; },
});
Object.defineProperty(El.prototype, "checked", { // a checkbox starts as its attribute says, like a browser
  get() { return this._checked ?? "checked" in this.attrs; },
  set(v) { this._checked = v; },
});
El.prototype.focus = function focus() { globalThis.__focused = this; };
const typed = (el, value) => { el.value = value; el.dispatchEvent(new Event("input")); };

const M = await import("../../web/model/notes.js");
const V = await import("../../web/views/notes.js");
const G = await import("../../web/notes.js");
const T = M.TEXT;
const tick = async () => { for (let i = 0; i < 6; i++) await new Promise((r) => setTimeout(r, 0)); };
const text = (root) => all(root).map((n) => n.textContent ?? "").join(" ");

// ---- words ----
test("every string follows the writer rules: no dash marks, no coach, medical or injury words, no invented numbers", () => {
  const strings = Object.values(T).flatMap((v) => (typeof v === "function" ? [v(3), v("Ada"), v("")] : [v]));
  for (const s of strings) {
    assert.doesNotMatch(String(s), /[\u2013\u2014]| - /, `a dash mark in: ${s}`);
    assert.doesNotMatch(String(s), /coach|medic|injur|rehab|therap|diagnos|clinic|doctor|patient|pain\b/i, `a banned word in: ${s}`);
  }
  assert.match(T.metaNotice, /When they press Run, the note is sent to Meta\./);
});

test("names: a missing or blank name is worded with the neutral line, never invented", () => {
  assert.equal(M.followerLine(null), "A Simon user");
  assert.equal(M.followerLine("  "), "A Simon user");
  assert.equal(M.followerLine("Fred F"), "Fred F");
  assert.equal(M.trainerLine(undefined), "A Simon trainer");
  assert.equal(M.noteView({ name: "Tina T" }, "Soft elbow.", 2.4).heading, "Note from Tina T");
  assert.equal(M.noteView({ name: null }, "x", null).heading, "Note from A Simon trainer");
  assert.equal(M.noteView({}, "x", 2.44).moment, "At 2.4 s");
  assert.equal(M.noteView({}, "x", null).moment, "");
});

test("askBody sends only the ticked keys in a fixed order and always confirms", () => {
  assert.deepEqual(M.askBody({ clip: true, score: true }), { include: ["score", "clip"], confirm: true });
  assert.deepEqual(M.askBody({ score: "yes", faults: 1 }), { include: [], confirm: true }, "only a real true ticks a box");
  assert.deepEqual(M.askBody(null), { include: [], confirm: true });
});

test("the name sentence says exactly what the trainer will see", () => {
  assert.match(M.shownAsLine("Fred F"), /will see you as Fred F\./);
  assert.match(M.shownAsLine(null), /will see you as A Simon user\. Your name shows only if your profile shows it\./);
  assert.equal(M.shownAsLine("Fred F").includes("@"), false);
});

test("followerView: the four modes, defaults with the clip off, the note only when answered", () => {
  const fresh = M.followerView({ can_ask: true, has_clip: true, shown_as: null, include_default: ["score", "faults"], request: null });
  assert.deepEqual(fresh.ticks, { score: true, faults: true, clip: false });
  assert.equal(fresh.mode, "ask");
  assert.equal(fresh.canClip, true);
  const asked = M.followerView({ request: { state: "asked", asked_utc: "2026-11-01T10:00:00Z" } });
  assert.equal(asked.mode, "asked");
  assert.equal(asked.asked, "You asked the trainer on 1 Nov 2026. There is no note yet.");
  const answered = M.followerView({ request: { state: "answered", from: { name: null }, answer: { note: "Soft elbow.", at_s: 7.1 } } });
  assert.deepEqual(answered.note, { heading: "Note from A Simon trainer", moment: "At 7.1 s", text: "Soft elbow." });
  assert.equal(M.followerView({ request: { state: "declined" } }).mode, "declined");
  assert.equal(M.followerView({ request: { state: "answered", answer: null } }).note, null, "negative: no answer, no note");
  assert.equal(M.followerView(null), null);
  assert.equal(M.followerView({ request: { state: "withdrawn" } }).mode, "ask", "a withdrawn request is gone");
});

test("notesList keeps the text, take number and day; drops empty notes", () => {
  const rows = M.notesList({ notes: [{ note: "A", at_s: null, answered_utc: "2026-11-02T00:00:00Z", take: 3, from: { name: "Tina T" } }, { note: "" }, null, { note: "B", take: "x" }] });
  assert.equal(rows.length, 2);
  assert.deepEqual([rows[0].take, rows[0].day, rows[0].heading], ["Take 3", "2 Nov 2026", "Note from Tina T"]);
  assert.equal(rows[1].take, "");
  assert.deepEqual(M.notesList(null), []);
});

test("cardView: counts, links and the quiet case", () => {
  assert.equal(M.cardView({ waiting: 0, received: [] }, { requests: [] }), null, "nothing waiting, nothing new: no card");
  const view = M.cardView(
    { waiting: 2, received: [{ entry_id: "lateral-raise", movement: "Lateral raise", answered_utc: "2026-11-02T00:00:00Z" }] },
    { requests: [{ id: "abc12345", state: "asked", movement: "Squat", asked_utc: "2026-11-01T00:00:00Z", from: { name: null } }, { id: "zzz", state: "answered" }]});
  assert.equal(view.waitingLine, "2 requests waiting for your note");
  assert.equal(view.receivedLine, "1 new note from trainers");
  assert.deepEqual(view.waiting, [{ href: "#/me/notes/abc12345", line: "A Simon user: Squat, 1 Nov 2026" }]);
  assert.deepEqual(view.received, [{ href: "#/me/lateral-raise", line: "Lateral raise, 2 Nov 2026" }]);
  assert.equal(M.cardView({ waiting: 1, received: [] }, null).waitingLine, "1 request waiting for your note");
});

test("trainerView reads only the included parts and never an id of the take", () => {
  const body = { id: "abc12345", state: "asked", asked_utc: "2026-11-01T00:00:00Z", movement: "Squat", from: { name: null }, include: ["score", "faults"],
    score: { value: 81, grade: "B" }, faults: [{ text: "Arm drifts", at_s: 2.4 }, { text: "Late", at_s: null }], clip: null, available: true, note_max: 600,
    job_id: "must-not-be-read", email: "a@b.co" };
  const view = M.trainerView(body);
  assert.equal(view.who, "A Simon user asked about Squat on 1 Nov 2026.");
  assert.equal(view.score, "Score 81, grade B");
  assert.deepEqual(view.faults.map((f) => f.moment), ["At 2.4 s", ""]);
  assert.equal(JSON.stringify(view).includes("must-not-be-read"), false);
  assert.equal(JSON.stringify(view).includes("@"), false);
  assert.equal(view.clipOn, false);
  assert.equal(M.trainerView({ state: "asked" }), null);
});

test("answerBody sends the note as typed and the time only when one is chosen", () => {
  assert.deepEqual(M.answerBody("Hi", null), { note: "Hi" });
  assert.deepEqual(M.answerBody("Hi", 2.4), { note: "Hi", at_s: 2.4 });
  assert.deepEqual(M.answerBody(null, NaN), { note: "" });
  assert.equal(M.counterText(12), "12 of 600");
  assert.equal(M.failureText({ body: { message: "Try tomorrow." } }, "x"), "Try tomorrow.");
  assert.equal(M.failureText({ body: null }, "x"), "x");
});

// ---- views ----
test("view: the ask slot opens a dialog with the defaults, a clip box off, the name sentence and the privacy line", () => {
  const host = new El("div");
  let sent = null;
  const vm = { t: T, ...M.followerView({ can_ask: true, has_clip: true, shown_as: "Fred F", include_default: ["score", "faults"], request: null }) };
  V.renderAsk(host, vm, { send: async (ticks) => { sent = ticks; return { ok: true, text: "" }; }, withdraw: async () => ({ ok: true, text: "" }) });
  assert.equal(find(host, "ask-open").textContent, T.ask);
  assert.equal(find(host, "ask-dialog"), null, "closed until pressed");
  find(host, "ask-open").click();
  assert.ok(find(host, "ask-dialog"));
  assert.equal("checked" in find(host, "ask-include-clip").attrs, false, "the clip box starts off");
  assert.equal("checked" in find(host, "ask-include-score").attrs, true);
  assert.match(find(host, "ask-shown-as").textContent, /will see you as Fred F/);
  assert.match(text(host), /does not see your email, your other takes or any link to your account/);
  find(host, "ask-send").click();
  assert.ok(sent && sent.score === true && sent.faults === true && sent.clip === false);
  find(host, "ask-cancel").click();
  assert.equal(find(host, "ask-dialog"), null);
});

test("view: without a clip the clip box is disabled and says so", () => {
  const host = new El("div");
  V.renderAsk(host, { t: T, ...M.followerView({ can_ask: true, has_clip: false, request: null }) }, {});
  find(host, "ask-open").click();
  assert.equal("disabled" in find(host, "ask-include-clip").attrs, true);
  assert.match(text(host), /no clip to send/);
});

test("view: a refused send keeps the dialog and says why", async () => {
  const host = new El("div");
  V.renderAsk(host, { t: T, ...M.followerView({ can_ask: true, request: null }) }, { send: async () => ({ ok: false, text: "You have 10 requests waiting. Withdraw one or wait for an answer." }) });
  find(host, "ask-open").click();
  find(host, "ask-send").click();
  await tick();
  assert.match(find(host, "ask-status").textContent, /10 requests waiting/);
  assert.equal(find(host, "ask-status").getAttribute("data-tone"), "bad");
  assert.ok(find(host, "ask-dialog"));
  assert.equal("disabled" in find(host, "ask-send").attrs, false, "the button is usable again");
});

test("view: asked shows the date and a Withdraw button; answered shows the note and no button; declined offers to ask again", async () => {
  const asked = new El("div");
  let withdrew = 0;
  V.renderAsk(asked, { t: T, ...M.followerView({ request: { state: "asked", asked_utc: "2026-11-01T10:00:00Z" } }) }, { withdraw: async () => { withdrew++; return { ok: true, text: "" }; } });
  assert.match(find(asked, "ask-asked").textContent, /You asked the trainer on 1 Nov 2026/);
  find(asked, "ask-withdraw").click();
  await tick();
  assert.equal(withdrew, 1);
  const answered = new El("div");
  V.renderAsk(answered, { t: T, ...M.followerView({ request: { state: "answered", from: { name: "Tina T" }, answer: { note: "Soft elbow.", at_s: 2.4 } } }) }, {});
  assert.equal(find(answered, "note-received").querySelector('[data-testid="note-received-text"]').textContent, "Soft elbow.");
  assert.equal(find(answered, "note-received-moment").textContent, "At 2.4 s");
  assert.match(text(answered), /Note from Tina T/);
  assert.equal(find(answered, "ask-open"), null);
  assert.equal(find(answered, "ask-withdraw"), null);
  const declined = new El("div");
  V.renderAsk(declined, { t: T, ...M.followerView({ request: { state: "declined" } }) }, {});
  assert.equal(find(declined, "ask-declined").textContent, T.declined);
  assert.equal(find(declined, "ask-open").textContent, T.askAgain);
});

test("view: the trainer's page shows what was sent, says what was not, and tells them about Meta before Send", () => {
  const host = new El("main");
  const base = { t: T, counter: (n) => M.counterText(n, 600), ...M.trainerView({ id: "abc12345", state: "asked", movement: "Squat", from: { name: null }, include: ["score", "faults"],
    score: { value: 81, grade: "B" }, faults: [{ text: "Arm drifts", at_s: 2.4 }], clip: null, available: true }) };
  const calls = [];
  V.renderRequest(host, base, { send: async (note, at) => { calls.push([note, at]); return { ok: true, text: "" }; }, decline: async () => { calls.push("decline"); return { ok: true, text: "" }; } });
  assert.equal(find(host, "request-score").textContent, "Score 81, grade B");
  assert.match(find(host, "request-fault-0").textContent, /At 2\.4 s: Arm drifts/);
  assert.equal(find(host, "request-clip"), null, "negative: no video element");
  assert.equal(find(host, "request-clip-off").textContent, T.clipOff);
  assert.match(find(host, "request-meta-notice").textContent, /When they press Run, the note is sent to Meta/);
  typed(find(host, "request-note"), "Soft elbow.");
  assert.equal(find(host, "request-count").textContent, "11 of 600");
  find(host, "request-at").value = "2.4";
  find(host, "request-send").click();
  assert.deepEqual(calls, [["Soft elbow.", "2.4"]]);
  find(host, "request-decline").click();
  assert.equal(calls[1], "decline");
  assert.equal(text(host).includes("job"), false);
});

test("view: not included parts read as not included; a closed request shows only the trainer's own note", () => {
  const host = new El("main");
  V.renderRequest(host, { t: T, counter: String, ...M.trainerView({ id: "abc12345", state: "asked", movement: "Squat", include: [], score: null, faults: null, clip: null, available: true }) }, {});
  assert.equal(find(host, "request-score-off").textContent, T.scoreOff);
  assert.equal(find(host, "request-faults-off").textContent, T.faultsOff);
  assert.equal(find(host, "request-at"), null, "no moment list without faults");
  const closed = new El("main");
  V.renderRequest(closed, { t: T, counter: String, ...M.trainerView({ id: "abc12345", state: "answered", movement: "Squat", include: ["score", "faults", "clip"], score: null, faults: null, clip: null,
    answer: { note: "Soft elbow.", at_s: 2.4 } }) }, {});
  assert.equal(find(closed, "request-answer").textContent, "Soft elbow.");
  assert.equal(find(closed, "request-sent"), null, "negative: the take is not shown once it is answered");
  assert.equal(find(closed, "request-form"), null);
});

test("view: the Me card lists links with a spoken name", () => {
  const card = new El("section");
  V.renderCard(card, { t: T, ...M.cardView({ waiting: 1, received: [{ entry_id: "squat", movement: "Squat", answered_utc: "2026-11-02T00:00:00Z" }] },
    { requests: [{ id: "abc12345", state: "asked", movement: "Squat", from: { name: "Fred F" } }] }) });
  assert.equal(find(card, "notes-waiting").textContent, "1 request waiting for your note");
  assert.equal(find(card, "notes-waiting-list-0").getAttribute("href"), "#/me/notes/abc12345");
  assert.match(find(card, "notes-waiting-list-0").getAttribute("aria-label"), /^Open: Fred F: Squat/);
  assert.equal(find(card, "notes-received").textContent, "1 new note from trainers");
});

// ---- the glue against a fake of the routes ----
function fakeServer({ signedIn = true, ask = null, askStatus = 200, postStatus = 201, notices = { waiting: 0, received: [] }, list = { requests: [] }, request = null, requestStatus = 200, notes = { notes: [] } } = {}) {
  const state = { calls: [], ask, request };
  globalThis.fetch = async (url, opts = {}) => {
    const method = opts.method || "GET";
    state.calls.push([method, url, opts.body ? JSON.parse(opts.body) : undefined]);
    const reply = (s, body) => ({ status: s, headers: { get: () => null }, json: async () => body });
    if (url === "api/auth/me") return reply(200, { available: true, signed_in: signedIn, email: "x@example.com", user_id: "u-1", retention: {} });
    if (/\/ask-trainer$/.test(url)) {
      if (method === "GET") return askStatus === 200 ? reply(200, state.ask) : reply(askStatus, { message: "x" });
      if (postStatus !== 201) return reply(postStatus, { message: "You have 10 requests waiting. Withdraw one or wait for an answer." });
      state.ask = { ...state.ask, can_ask: false, request: { state: "asked", asked_utc: "2026-11-01T10:00:00Z", from: { name: null }, answer: null } };
      return reply(201, {});
    }
    if (/\/ask-trainer\/withdraw$/.test(url)) { state.ask = { ...state.ask, can_ask: true, request: null }; return reply(200, { withdrawn: true }); }
    if (url === "api/me/note-notices") return reply(200, notices);
    if (url === "api/me/note-notices/seen") return reply(200, { seen: 1 });
    if (url === "api/me/note-requests") return reply(200, list);
    if (/^api\/me\/note-requests\/[^/]+$/.test(url)) return requestStatus === 200 ? reply(200, state.request) : reply(requestStatus, { message: "x" });
    if (/\/answer$/.test(url)) { state.request = { ...state.request, state: "answered", answer: { note: JSON.parse(opts.body).note, at_s: JSON.parse(opts.body).at_s ?? null } }; return reply(200, { state: "answered" }); }
    if (/\/decline$/.test(url)) { state.request = { ...state.request, state: "declined" }; return reply(200, { state: "declined" }); }
    if (/^api\/me\/notes\?entry=/.test(url)) return reply(200, notes);
    return reply(404, {});
  };
  return state;
}
const ASK = { can_ask: true, has_clip: true, shown_as: null, include_default: ["score", "faults"], request: null };

test("glue: a take that can be sent shows the button; ticking and sending posts the include set, then shows the asked state", async () => {
  const state = fakeServer({ ask: { ...ASK } });
  const slot = new El("div");
  const stop = G.mountAskTrainer(slot, { job: "a1b2c3d4e5f6" });
  await tick();
  find(slot, "ask-open").click();
  find(slot, "ask-include-clip").attrs.checked = "";
  find(slot, "ask-include-clip").checked = true;
  find(slot, "ask-send").click();
  await tick();
  const post = state.calls.find((c) => c[0] === "POST");
  assert.equal(post[1], "api/me/takes/a1b2c3d4e5f6/ask-trainer");
  assert.equal(post[2].confirm, true);
  assert.ok(Array.isArray(post[2].include));
  assert.ok(find(slot, "ask-asked"), "the asked state replaces the button");
  find(slot, "ask-withdraw").click();
  await tick();
  assert.ok(state.calls.some((c) => c[1].endsWith("/withdraw")));
  assert.ok(find(slot, "ask-open"), "after a withdraw the button is back");
  stop();
});

test("glue: not eligible (404), signed out, the example result and a group person leave no trace and ask nothing", async () => {
  const gone = fakeServer({ askStatus: 404 });
  const a = new El("div");
  G.mountAskTrainer(a, { job: "a1b2c3d4e5f6" });
  await tick();
  assert.equal(a.children.length, 0, "404: nothing in the slot");
  const out = fakeServer({ signedIn: false, ask: { ...ASK } });
  const b = new El("div");
  G.mountAskTrainer(b, { job: "a1b2c3d4e5f6" });
  await tick();
  assert.equal(b.children.length, 0);
  assert.equal(out.calls.some((c) => /ask-trainer/.test(c[1])), false, "negative: signed out never asks the route");
  const calls = [];
  for (const ctx of [{ job: "fixture" }, { job: "a1b2c3d4e5f6", pid: "p1" }, {}, null]) {
    assert.equal(G.mountAskTrainer(new El("div"), ctx), undefined);
  }
  assert.equal(gone.calls.filter((c) => /ask-trainer/.test(c[1])).length, 1);
  assert.equal(calls.length, 0);
});

test("glue: a result the viewer does not own (attribution.mine false) asks nothing and shows nothing", async () => {
  const state = fakeServer({ ask: { ...ASK } });
  const slot = new El("div");
  assert.equal(G.mountAskTrainer(slot, { job: "a1b2c3d4e5f6", jobRecord: { attribution: { mine: false } } }), undefined);
  await tick();
  assert.equal(state.calls.filter((c) => /ask-trainer/.test(c[1])).length, 0, "no owner-only request for someone else's take");
  assert.equal(slot.children.length, 0);
  G.mountAskTrainer(new El("div"), { job: "a1b2c3d4e5f6", jobRecord: { attribution: { mine: true } } });
  await tick();
  assert.equal(state.calls.filter((c) => /ask-trainer/.test(c[1])).length, 1, "the owner's result still asks");
});

test("glue: a refused send (429) shows the server's sentence", async () => {
  fakeServer({ ask: { ...ASK }, postStatus: 429 });
  const slot = new El("div");
  G.mountAskTrainer(slot, { job: "a1b2c3d4e5f6" });
  await tick();
  find(slot, "ask-open").click();
  find(slot, "ask-send").click();
  await tick();
  assert.match(find(slot, "ask-status").textContent, /10 requests waiting/);
});

test("glue: the trainer's page loads one request, answers it, then shows only their note", async () => {
  const state = fakeServer({ request: { id: "abc12345", state: "asked", movement: "Squat", from: { name: null }, include: ["score", "faults"], score: { value: 81, grade: "B" },
    faults: [{ text: "Arm drifts", at_s: 2.4 }], clip: null, available: true, note_max: 600, answer: null } });
  const el = new El("main");
  const stop = G.mountNoteRequest(el, "abc12345");
  await tick();
  typed(find(el, "request-note"), "Soft elbow.");
  find(el, "request-send").click();
  await tick();
  const post = state.calls.find((c) => c[0] === "POST");
  assert.equal(post[1], "api/me/note-requests/abc12345/answer");
  assert.deepEqual(post[2], { note: "Soft elbow." });
  assert.equal(find(el, "request-answer").textContent, "Soft elbow.");
  assert.equal(find(el, "request-sent"), null);
  stop();
});

test("glue: the approve button is mounted only when the server says the request allows it (AC-MR-29)", async () => {
  const base = { id: "abc12345", state: "asked", movement: "Squat", from: { name: null }, include: ["score"], score: null, faults: null, clip: null, available: true, note_max: 600, answer: null };
  fakeServer({ request: { ...base, can_approve_reference: true } });
  const open = new El("main");
  const stop = G.mountNoteRequest(open, "abc12345");
  await tick();
  await tick();
  assert.ok(find(open, "approve-reference"), "an open request offers the button");
  stop();
  assert.equal(find(open, "approve-reference"), null, "leaving the page removes it");
  fakeServer({ request: { ...base, state: "answered", can_approve_reference: false, answer: { note: "Soft.", at_s: null } } });
  const closed = new El("main");
  G.mountNoteRequest(closed, "abc12345");
  await tick();
  await tick();
  assert.equal(find(closed, "approve-reference"), null, "a closed request offers none");
  fakeServer({ request: { ...base } });
  const missing = new El("main");
  G.mountNoteRequest(missing, "abc12345");
  await tick();
  assert.equal(find(missing, "approve-reference"), null, "no flag, no button");
});

test("glue: the trainer's page for an unknown or withdrawn request says it is not available", async () => {
  fakeServer({ requestStatus: 404 });
  const el = new El("main");
  G.mountNoteRequest(el, "nope1234");
  await tick();
  assert.ok(find(el, "request-gone"));
  assert.match(text(el), /not available/);
  fakeServer({ requestStatus: 401 });
  const signedOut = new El("main");
  G.mountNoteRequest(signedOut, "nope1234");
  await tick();
  assert.ok(find(signedOut, "request-signed-out"));
});

test("glue: the Me card appears with counts, marks notes seen once, and stays hidden when there is nothing", async () => {
  const state = fakeServer({ notices: { waiting: 1, received: [{ entry_id: "squat", movement: "Squat", answered_utc: "2026-11-02T00:00:00Z" }] },
    list: { requests: [{ id: "abc12345", state: "asked", movement: "Squat", from: { name: null } }] } });
  const parent = new El("main");
  const anchor = new El("div");
  parent.append(anchor);
  const stop = G.mountNotesCard(anchor);
  await tick();
  const card = parent.children[1];
  assert.equal(card.hidden, false);
  assert.equal(find(card, "notes-waiting").textContent, "1 request waiting for your note");
  assert.equal(state.calls.filter((c) => c[1] === "api/me/note-notices/seen").length, 1);
  stop();
  assert.equal(card.parent, null);
  fakeServer();
  const quiet = new El("main");
  const a2 = new El("div");
  quiet.append(a2);
  G.mountNotesCard(a2);
  await tick();
  assert.equal(quiet.children[1].hidden, true, "nothing waiting, nothing new: the card stays hidden");
});

test("glue: the history page lists the notes of the movement, and nothing when there are none", async () => {
  fakeServer({ notes: { notes: [{ note: "Soft elbow.", at_s: 2.4, answered_utc: "2026-11-02T00:00:00Z", take: 2, from: { name: null } }] } });
  const host = new El("main");
  const stop = G.mountTakeNotes(host, "squat");
  await tick();
  assert.match(text(find(host, "history-note-0")), /Take 2, 2 Nov 2026/);
  assert.equal(find(host, "history-note-card-0-text").textContent, "Soft elbow.");
  stop();
  assert.equal(find(host, "history-notes"), null);
  fakeServer();
  const empty = new El("main");
  G.mountTakeNotes(empty, "squat");
  await tick();
  assert.equal(empty.children.length, 0);
});

test("the result page, history page and app hold one hook each for this feature", () => {
  const read = (f) => fs.readFileSync(new URL(`../../web/${f}`, import.meta.url), "utf8");
  assert.match(read("result.js"), /import\("\.\/notes\.js"\)\.then\(\(m\) => m\.mountAskTrainer\)/);
  assert.match(read("history.js"), /m\.mountTakeNotes\(container, entryId\)/);
  assert.match(read("app.js"), /me\\\/notes\\\/\(\[\^\/\]\+\)\$\/, \(el, m\) => mountNoteRequestRoute/);
  assert.match(read("me-page.js"), /notes\.mountNotesCard\(account\)/); // the Me page glue (docs/specs/me-page.md)
  assert.equal(findAll(new El("x"), "y").length, 0);
});

test("view: a free time typed in the take wins over the list, and it is offered even with no faults", async () => {
  const calls = [];
  const on = { send: async (note, at) => { calls.push([note, at]); return { ok: true, text: "" }; }, decline: async () => ({ ok: true, text: "" }) };
  const withFaults = new El("main");
  V.renderRequest(withFaults, { t: T, counter: String, ...M.trainerView({ id: "abc12345", state: "asked", movement: "Squat", include: ["faults"], faults: [{ text: "Arm drifts", at_s: 2.4 }], available: true }) }, on);
  find(withFaults, "request-at").value = "2.4";
  find(withFaults, "request-at-free").value = "5.5";
  find(withFaults, "request-send").click();
  assert.deepEqual(calls[0], ["", "5.5"]);
  const bare = new El("main");
  V.renderRequest(bare, { t: T, counter: String, ...M.trainerView({ id: "abc12345", state: "asked", movement: "Squat", include: [], available: true }) }, on);
  assert.equal(find(bare, "request-at"), null);
  assert.ok(find(bare, "request-at-free"), "a trainer can point at a time even when no fault list was sent");
  assert.equal(M.TEXT.momentFree, "Or a time in the take, in seconds");
});
