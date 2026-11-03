// Signed-in devices card: pure logic (web/model/devices.js), the view on a fake DOM (web/views/devices.js) and the glue
// (web/devices.js) against an in-memory fake of GET api/me/sessions and the two end routes.
//   node --test tests/part7/devices.unit.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { El, installDom, all, find, findAll } from "./fake-dom.mjs";

installDom();
Object.defineProperty(El.prototype, "hidden", {
  get() { return "hidden" in this.attrs; },
  set(v) { if (v) this.attrs.hidden = ""; else delete this.attrs.hidden; },
});
El.prototype.focus = function focus() { globalThis.__focused = this; };

const M = await import("../../web/model/devices.js");
const V = await import("../../web/views/devices.js");
const G = await import("../../web/devices.js");
const T = M.TEXT;
const tick = () => new Promise((r) => setTimeout(r, 0));
const text = (root) => all(root).map((n) => n.textContent ?? "").join(" ");
const ROWS = [
  { id: "aaaaaaaaaaaa", device: "Firefox on Android", signed_in: "2026-11-01T10:00:00Z", last_active: "2026-11-01T14:00:00Z", current: true },
  { id: "bbbbbbbbbbbb", device: "Chrome on Windows", signed_in: "2026-10-30T09:00:00Z", last_active: "2026-10-31T09:00:00Z", current: false },
  { id: "cccccccccccc", device: "Safari on iPhone", signed_in: "2026-10-29T09:00:00Z", last_active: "2026-10-29T10:00:00Z", current: false },
];

test("normalizeRows keeps the id, the rough name and the two times, and drops a row without an id", () => {
  const rows = M.normalizeRows([...ROWS, { device: "no id" }, null, { id: "dddddddddddd", device: "  ", current: "yes", email: "a@b.co", sid: "secret" }]);
  assert.equal(rows.length, 4);
  assert.deepEqual(Object.keys(rows[0]).sort(), ["current", "device", "id", "label", "lastActive", "line", "signedIn"]);
  assert.equal(rows[3].device, T.unknown, "a blank name reads Unknown browser");
  assert.equal(rows[3].current, false, "only a real true marks this device");
  assert.equal(JSON.stringify(rows).includes("@"), false, "negative: an email in the answer is never read");
  assert.equal(JSON.stringify(rows).includes("secret"), false);
  assert.deepEqual(M.normalizeRows(null), []);
  assert.deepEqual(M.normalizeRows({ id: "x" }), []);
});

test("lines and labels: times to the hour, the spoken button name, the counts", () => {
  const row = M.normalizeRows(ROWS)[1];
  assert.equal(M.rowLine(row, "UTC"), "Signed in around Oct 30, 9 AM. Last active around Oct 31, 9 AM.");
  assert.equal(M.rowLine({ signedIn: "", lastActive: "nope" }, "UTC"), "");
  assert.equal(M.normalizeRows(ROWS)[1].label, "Sign out Chrome on Windows");
  assert.equal(M.signOutLabel("Chrome on Windows"), "Sign out Chrome on Windows");
  assert.equal(M.endedOthers(1), "Signed out 1 device.");
  assert.equal(M.endedOthers(2), "Signed out 2 devices.");
  assert.equal(M.endedOthers(0), T.endedNone);
  assert.equal(M.endUrl("ab/../c"), "api/me/sessions/ab%2F..%2Fc/end");
  assert.equal(M.endFailure(404), T.endGone);
  assert.equal(M.endFailure(500), T.endFailed);
});

test("every string follows the writer rules: no em dash, en dash or spaced hyphen", () => {
  for (const [k, v] of Object.entries(T)) {
    assert.doesNotMatch(v, /[\u2013\u2014]| - /, k);
    assert.ok(v.length > 0, k);
  }
});

test("view: this device is marked and has no button, the others have one each and a sign out everywhere else", () => {
  const host = new El("section");
  V.renderDevices(host, { t: T, rows: M.normalizeRows(ROWS) }, { end: async () => {}, endOthers: async () => {} });
  assert.equal(find(host, "device-current-0").textContent, T.thisDevice);
  assert.equal(find(host, "device-end-0"), null, "negative: this device has no Sign out button");
  assert.equal(find(host, "device-current-1"), null);
  assert.equal(find(host, "device-end-1").getAttribute("aria-label"), "Sign out Chrome on Windows");
  assert.equal(findAll(host, "devices-end-others").length, 1);
  assert.equal(find(host, "devices-end-others").textContent, T.signOutOthers);
  assert.equal(find(host, "devices-note").getAttribute("aria-live"), "polite");
});

test("view: only this device left shows the empty line and no sign out everywhere else", () => {
  const host = new El("section");
  V.renderDevices(host, { t: T, rows: M.normalizeRows(ROWS.slice(0, 1)) }, { end: async () => {}, endOthers: async () => {} });
  assert.equal(find(host, "devices-empty").textContent, T.empty);
  assert.equal(find(host, "devices-end-others"), null);
});

// ---- the glue against a fake of the routes ----
function fakeServer({ status = 200, rows = ROWS.map((r) => ({ ...r })), endStatus = 200 } = {}) {
  const state = { rows, calls: [], listStatus: status };
  globalThis.fetch = async (url, opts = {}) => {
    const method = opts.method || "GET";
    state.calls.push([method, url]);
    const reply = (s, body) => ({ status: s, headers: { get: () => null }, json: async () => body });
    if (url === "api/me/sessions") return state.listStatus === 200 ? reply(200, state.rows) : reply(state.listStatus, { error: "x" });
    if (url === "api/me/sessions/end-others") {
      if (endStatus !== 200) return reply(endStatus, { error: "x" });
      const n = state.rows.filter((r) => !r.current).length;
      state.rows = state.rows.filter((r) => r.current);
      return reply(200, { ended: n });
    }
    const m = /^api\/me\/sessions\/(\w+)\/end$/.exec(url);
    if (m) {
      if (endStatus !== 200) return reply(endStatus, { error: "x" });
      const before = state.rows.length;
      state.rows = state.rows.filter((r) => r.id !== m[1]);
      return state.rows.length < before ? reply(200, { ended: true, current: false }) : reply(404, { error: "x" });
    }
    return reply(404, {});
  };
  return state;
}

const mounted = async (opts) => {
  const state = fakeServer(opts);
  const parent = new El("main");
  const anchor = new El("section");
  parent.append(anchor);
  const stop = G.mountDevices(anchor);
  await tick(); await tick(); await tick();
  const card = parent.children[1];
  return { state, card, stop };
};

test("glue: lists the rows, ends one device with a POST, then shows the list without it", async () => {
  const { state, card, stop } = await mounted();
  assert.ok(find(card, "devices-list"));
  assert.equal(findAll(card, "devices-list")[0].children.length, 3);
  find(card, "device-end-1").click();
  await tick(); await tick(); await tick();
  assert.ok(state.calls.some((c) => c[0] === "POST" && c[1] === "api/me/sessions/bbbbbbbbbbbb/end"));
  assert.equal(findAll(card, "devices-list")[0].children.length, 2);
  assert.equal(find(card, "devices-note").textContent, T.endedOne);
  assert.equal(text(card).includes("Chrome on Windows"), false, "negative: the ended device is gone from the list");
  stop();
});

test("glue: sign out everywhere else ends the others and says how many", async () => {
  const { state, card, stop } = await mounted();
  find(card, "devices-end-others").click();
  await tick(); await tick(); await tick();
  assert.ok(state.calls.some((c) => c[0] === "POST" && c[1] === "api/me/sessions/end-others"));
  assert.equal(find(card, "devices-note").textContent, "Signed out 2 devices.");
  assert.equal(find(card, "devices-end-others"), null);
  assert.equal(find(card, "devices-empty").textContent, T.empty);
  stop();
});

test("glue: a device that is already gone says so and the list refreshes; a failure says to try again", async () => {
  const gone = await mounted();
  gone.state.rows = gone.state.rows.filter((r) => r.id !== "bbbbbbbbbbbb"); // ended elsewhere meanwhile
  find(gone.card, "device-end-1").click();
  await tick(); await tick(); await tick();
  assert.equal(find(gone.card, "devices-note").textContent, T.endGone);
  gone.stop();
  const bad = await mounted({ endStatus: 500 });
  find(bad.card, "device-end-1").click();
  await tick(); await tick(); await tick();
  assert.equal(find(bad.card, "devices-note").textContent, T.endFailed);
  assert.equal(find(bad.card, "devices-note").getAttribute("data-tone"), "bad");
  assert.equal(findAll(bad.card, "devices-list")[0].children.length, 3, "negative: nothing disappears when the call failed");
  bad.stop();
});

test("glue: signed out (401) and sign-in off (404) leave no trace; a server error shows the retry state", async () => {
  for (const status of [401, 404]) {
    const { card, stop } = await mounted({ status });
    assert.equal(card.hidden, true, `${status}: the card is hidden`);
    assert.equal(card.children.length, 0, `${status}: and empty`);
    assert.equal(find(card, "devices-list"), null);
    stop();
  }
  const err = await mounted({ status: 500 });
  assert.ok(find(err.card, "devices-error"));
  assert.equal(err.card.hidden, false);
  err.state.listStatus = 200;
  find(err.card, "devices-retry").click();
  await tick(); await tick(); await tick();
  assert.ok(find(err.card, "devices-list"));
  err.stop();
});

test("glue: cleanup removes the card", async () => {
  const { card, stop } = await mounted();
  stop();
  assert.equal(card.parent, null);
});
