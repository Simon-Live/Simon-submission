// Round 13 board fixes (docs/specs/challenges.md "Round 13", board-visibility.md, score-consistency.md S9, home-browse.md):
// named people never land on a reused public board, no literal "null" text, the board order line only on a credit-scale
// board, the default sort stays out of the address, the leader alone is named.
//   node --test tests/part7/board-r13.dom.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { installDom, find, all, Node } from "./fake-dom.mjs";

installDom();
globalThis.location = { origin: "http://h", pathname: "/", hash: "" };
const sent = [];
const routes = [];
globalThis.fetch = async (url, init = {}) => {
  sent.push({ url: String(url), method: init.method || "GET", body: init.body ? JSON.parse(init.body) : null });
  const hit = routes.find((r) => String(url).startsWith(r.prefix) && (r.method || "GET") === (init.method || "GET"));
  const body = hit ? await hit.reply() : {};
  return { ok: true, status: 200, headers: { get: () => "application/json" }, json: async () => body, text: async () => JSON.stringify(body) };
};
const { mountChallengeActions } = await import("../../web/challenge-actions.js");
const { mountChallenge } = await import("../../web/challenge.js");
const core = await import("../../web/challenge-core.js");
const flush = async () => { for (let i = 0; i < 12; i += 1) await new Promise((r) => setTimeout(r, 0)); };
const texts = (root) => all(root).filter((n) => n.tag).map((n) => n.textContent).join("|");
const nullText = (root) => all(root).some((n) => n.data === "null" || n.attrs?.text === "null");

const CREDIT = { letter: "B", figures: "80%", unit: "percent", measure: 80, partial: false };
const PARTIAL = { ...CREDIT, figures: "70%", measure: 70, partial: true };
const entry = (name, score, shown, at) => ({ name, score, grade: "B", created_at: at, ...(shown ? { shown } : {}) });

function route(prefix, reply, method) { routes.push({ prefix, reply, method }); }

test("H2: named people get a new private board even when the maker has an open public one; a public choice still reuses it", async () => {
  routes.length = 0; sent.length = 0;
  route("api/auth/me", () => ({ available: true, signed_in: true, email: "o@x.org", user_id: "u1" }));
  route("catalog/api/entries/squat", () => ({ id: "squat", name: "Squat" }));
  route("api/movements/squat/boards", () => ({ boards: [{ id: "pub1", mine: true, ended: false, kind: "friend", visibility: "public", title: "Beat my Squat" }] }));
  route("api/challenges/pub1/entries", () => ({ added: [], id: "pub1", title: "Beat my Squat" }), "POST");
  route("api/challenges", () => ({ id: "priv1", title: "Beat my Squat", added: [], access: { visibility: "invited", invites: [], mail: [] } }), "POST");
  const slot = document.createElement("div");
  await mountChallengeActions(slot, { job: "aaaaaaaaaaaa", jobRecord: { entry_id: "squat", mode: "fitness" }, analysis: { status: { code: "ok" }, score: { value: 70 } } });
  find(slot, "challenge-name").value = "Sam";
  find(slot, "access-invited").checked = true;
  find(slot, "access-emails").value = "ann@example.com";
  find(slot, "challenge-create").click();
  await flush();
  const made = sent.filter((s) => s.method === "POST");
  assert.equal(made.length, 1, "one post");
  assert.equal(made[0].url, "api/challenges", "a new board, not the old public one");
  assert.equal(made[0].body.visibility, "invited");
  assert.deepEqual(made[0].body.invites, ["ann@example.com"]);
  assert.match(find(slot, "challenge-link").textContent, /priv1$/);
  assert.equal(nullText(slot), false, "no literal null in the Challenge ready panel");

  sent.length = 0;
  const slot2 = document.createElement("div");
  await mountChallengeActions(slot2, { job: "aaaaaaaaaaaa", jobRecord: { entry_id: "squat", mode: "fitness" }, analysis: { status: { code: "ok" }, score: { value: 70 } } });
  find(slot2, "challenge-name").value = "Sam";
  find(slot2, "challenge-create").click();
  await flush();
  assert.equal(sent.filter((s) => s.method === "POST")[0].url, "api/challenges/pub1/entries", "public choice reuses the public board");
});

// R14b B3: a public choice reuses only a board that is public; a private or unmarked card gets a new public board
for (const [label, card] of [["private", { visibility: "private" }], ["invited", { visibility: "invited" }], ["no visibility field", {}]]) {
  test(`B3: a ${label} card is not reused for a Public choice`, async () => {
    routes.length = 0; sent.length = 0;
    route("api/auth/me", () => ({ available: true, signed_in: true, email: "o@x.org", user_id: "u1" }));
    route("catalog/api/entries/squat", () => ({ id: "squat", name: "Squat" }));
    route("api/movements/squat/boards", () => ({ boards: [{ id: "old1", mine: true, ended: false, kind: "friend", title: "Beat my Squat", ...card }] }));
    route("api/challenges/old1/entries", () => ({ added: [], id: "old1", title: "Beat my Squat" }), "POST");
    route("api/challenges", () => ({ id: "new1", title: "Beat my Squat", added: [] }), "POST");
    const slot = document.createElement("div");
    await mountChallengeActions(slot, { job: "aaaaaaaaaaaa", jobRecord: { entry_id: "squat", mode: "fitness" }, analysis: { status: { code: "ok" }, score: { value: 70 } } });
    find(slot, "challenge-name").value = "Sam";
    find(slot, "challenge-create").click();
    await flush();
    const made = sent.filter((s) => s.method === "POST");
    assert.equal(made.length, 1);
    assert.equal(made[0].url, "api/challenges", "a new board, not the maker's old one");
  });
}

function board(entries, extra = {}) {
  routes.length = 0;
  route("api/challenges/b1", () => ({ id: "b1", entry_id: "squat", title: "Beat my Squat", kind: "friend", creator_name: "Sam", you: "guest", entries, ...extra }));
  route("catalog/api/entries/squat", () => ({ id: "squat", name: "Squat" }));
  const root = document.createElement("div");
  const stop = mountChallenge(root, "b1");
  return { root, stop };
}

test("R1: the order line and a row reason show only when every row is on the credit scale", async () => {
  const mixed = board([entry("A", 80, CREDIT, "1"), entry("B", 70, PARTIAL, "2"), entry("Old", 90, null, "3")]);
  await flush();
  assert.equal(find(mixed.root, "board-order"), null, "an old-scale row: no order line");
  assert.equal(find(mixed.root, "board-partial-2"), null, "an old-scale row: no row reason");
  mixed.stop();
  const credit = board([entry("A", 80, CREDIT, "1"), entry("B", 70, PARTIAL, "2")]);
  await flush();
  assert.equal(find(credit.root, "board-order").textContent, core.BOARD_ORDER);
  assert.ok(find(credit.root, "board-partial-2"));
  credit.stop();
  const one = board([entry("A", 80, CREDIT, "1")]);
  await flush();
  assert.equal(find(one.root, "board-order"), null, "negative: a one-row board has no order line");
  one.stop();
});

test("Low: a card names the leader alone", async () => {
  const { leadingText } = await import("../../web/boards-list-core.js");
  assert.equal(leadingText({ top: [{ name: "QA B" }, { name: "QA A" }] }), "Leading: QA B");
  assert.equal(leadingText({ top: [] }), "");
});

test("Low: the default sort is left out of the address (the click is driven in board-r14.browser.mjs)", async () => {
  const { paramsOf, DEFAULTS, effectiveSort } = await import("../../web/model/browse.js");
  const state = { ...DEFAULTS };
  assert.equal(effectiveSort(state), "newest");
  assert.equal(paramsOf({ ...state, sort: DEFAULTS.sort }).toString(), "");
});

test("B2: an invite that was not mailed shows its line and buttons without the text null", async () => {
  // a real browser turns append(null) into the text "null"; the fake would throw, so give it the browser's rule
  const real = Node.prototype.append;
  Node.prototype.append = function (...kids) { return real.apply(this, kids.map((k) => (k instanceof Node ? k : document.createTextNode(String(k))))); };
  try {
    const { renderMailResults } = await import("../../web/challenge-access.js");
    const box = document.createElement("div");
    renderMailResults(box, { link: "http://h/#/c/x", mail: [{ email: "a@x.org", state: "not_mailed" }, { email: "b@x.org", state: "failed", failure_id: "f1" }] }, { title: "T", retry: () => {} });
    assert.equal(nullText(box), false, "no literal null in a mail result row");
    assert.match(find(box, "mail-result-1").textContent, /^Not mailed to a@x\.org\./);
    assert.equal(find(find(box, "mail-result-1"), "mail-retry"), null, "negative: a not-mailed row has no Try again");
    assert.ok(find(find(box, "mail-result-2"), "mail-retry"), "a failed row keeps Try again");
  } finally { Node.prototype.append = real; }
});
