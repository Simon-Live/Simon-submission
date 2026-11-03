// Profile page: pure logic (web/model/profile.js), the view on a fake DOM (web/views/profile.js) and the glue
// (web/profile.js) against an in-memory fake of the profile routes (GET/PUT/DELETE api/me/profile, GET api/avatars).
//   node --test tests/part7/profile.unit.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { El, installDom, all, find, findAll } from "./fake-dom.mjs";

installDom();
globalThis.window = new EventTarget(); // the header link listens for sign-in changes
const cls = (el) => (el.attrs.class || "").split(/\s+/).filter(Boolean);
Object.defineProperty(El.prototype, "classList", { get() { return { add: (c) => { this.attrs.class = [...new Set([...cls(this), c])].join(" "); } }; } });
Object.defineProperty(El.prototype, "hidden", {
  get() { return "hidden" in this.attrs; },
  set(v) { if (v) this.attrs.hidden = ""; else delete this.attrs.hidden; },
});
El.prototype.focus = function focus() { globalThis.__focused = this; };
El.prototype.after = function after(...kids) { (globalThis.__after ||= []).push(...kids); };

const M = await import("../../web/model/profile.js");
const V = await import("../../web/views/profile.js");
const G = await import("../../web/profile.js");
const T = M.TEXT;
const tick = () => new Promise((r) => setTimeout(r, 0));
const text = (root) => all(root).map((n) => n.textContent ?? "").join(" ");

test("normalizeProfile reads either wire shape and never an email", () => {
  const flat = M.normalizeProfile({ public_name: "Sam", avatar_key: "fox", modes: ["dance"], goals: ["g"], show_name: true, credit_me_as_trainer: true, email: "sam@example.com" });
  assert.deepEqual([flat.name, flat.avatar, flat.modes, flat.showName, flat.creditTrainer], ["Sam", "fox", ["dance"], true, true]);
  const nested = M.normalizeProfile({ display_name: "Sam", avatar: "owl", privacy: { public_name: true, credit_me_as_trainer: false } });
  assert.deepEqual([nested.name, nested.avatar, nested.showName, nested.creditTrainer], ["Sam", "owl", true, false]);
  assert.equal(JSON.stringify(flat).includes("@"), false, "negative: no email in the normalized profile");
  assert.equal(M.normalizeProfile({ display_name: "a@b.co" }).name, "", "a name with an @ is dropped");
});

test("a fresh profile has every privacy choice off and shows You", () => {
  const p = M.normalizeProfile({});
  assert.deepEqual([p.showName, p.creditTrainer, p.name, p.avatar, p.modes, p.goals], [false, false, "", "", [], []]);
  assert.equal(M.shownName(p), "You");
  assert.equal(M.normalizeProfile(null).showName, false);
});

test("checkName: NFKC trim, 1 to 40, no control character, no @, empty allowed", () => {
  assert.deepEqual(M.checkName("  Sam  "), { ok: true, name: "Sam" });
  assert.deepEqual(M.checkName("   "), { ok: true, name: "" });
  assert.equal(M.checkName("Ｓam").name, "Sam", "full-width letters fold to plain ones");
  assert.equal(M.checkName("x".repeat(40)).ok, true);
  for (const bad of ["x".repeat(41), "a@b", "tab\there", "bell\u0007"]) assert.equal(M.checkName(bad).ok, false, bad);
  assert.equal(M.checkName("a@b").error, T.nameBad);
});

test("toWire sends the six keys; empty name and avatar become null", () => {
  const body = M.toWire({ name: " ", avatar: "", modes: ["dance"], goals: [], showName: 1, creditTrainer: 0 });
  assert.deepEqual(body, { public_name: null, avatar: null, modes: ["dance"], goals: [], show_name: true, credit_me_as_trainer: false });
  assert.equal(M.toWire({ name: "Sam", avatar: "fox", modes: [], goals: [], showName: false, creditTrainer: false }).public_name, "Sam");
});

test("isDirty compares the wire forms; toggled keeps the option order", () => {
  const p = M.normalizeProfile({ public_name: "Sam" });
  assert.equal(M.isDirty(M.draftFrom(p), p), false);
  assert.equal(M.isDirty({ ...M.draftFrom(p), showName: true }, p), true);
  const opts = M.optionList(["a", "b", "c"], []);
  assert.deepEqual(M.toggled(["c"], "a", opts), ["a", "c"]);
  assert.deepEqual(M.toggled(["a", "c"], "a", opts), ["c"]);
});

test("optionList and avatarList: strings or objects, fallback when empty, stable tone", () => {
  assert.deepEqual(M.optionList(["learn the moves"], []), [{ id: "learn the moves", label: "Learn the moves" }]);
  assert.deepEqual(M.optionList([{ key: "fox", name: "Fox" }, null, {}], []), [{ id: "fox", label: "Fox" }]);
  assert.deepEqual(M.optionList([], ["dance"]).map((o) => o.id), ["dance"]);
  const list = M.avatarList({ avatars: ["fox", "owl"] });
  assert.equal(list.length, 2);
  assert.ok(list.every((a) => a.tone >= 0 && a.tone <= 3));
  assert.equal(M.avatarTone("fox"), M.avatarTone("fox"));
  assert.deepEqual(M.avatarList(null), []);
  assert.equal(M.avatarInitial("fox"), "F");
});

test("movementRows, entryRows and summaryLines: profile answer first, history list as the fallback", () => {
  const history = { entries: [{ entry_id: "lateral-raise", name: "Lateral raise", takes: 3, latest: { at: "2026-10-31T10:00:00Z" } }] };
  const rows = M.movementRows({}, history);
  assert.equal(rows[0].href, "#/me/lateral-raise");
  assert.match(rows[0].line, /3 takes, last Oct 31/);
  const own = M.movementRows({ movements: [{ entry_id: "x", name: "X", count: 1, last_at: "2026-10-30T09:00:00Z" }] }, history);
  assert.equal(own.length, 1);
  assert.match(own[0].line, /^1 take, last Oct 30/);
  assert.deepEqual(M.entryRows({}), []);
  assert.equal(M.entryRows({ entries: [{ entry_id: "mine", name: "Mine", count: 2 }] })[0].href, "#/watch/mine");
  assert.deepEqual(M.summaryLines({}, history), ["3 takes kept across 1 movement."]);
  assert.deepEqual(M.summaryLines({}, { entries: [] }), [], "nothing kept: no zeros are made up");
  assert.deepEqual(M.summaryLines({ summary: { lines: ["Kept 2 takes.", "a@b.co"] } }, history), ["Kept 2 takes."]);
  assert.deepEqual(M.summaryLines({ summary: "Nothing was kept." }, history), ["Nothing was kept."]);
});

test("failureText: 400 is a refusal, anything else the fallback", () => {
  assert.equal(M.failureText(400, "x"), T.saveRefused);
  assert.equal(M.failureText(500, "x"), "x");
});

test("copy: no em dash, en dash or spaced hyphen; the email is not promised anywhere", () => {
  for (const [k, v] of Object.entries(T)) {
    assert.doesNotMatch(v, /[\u2013\u2014]| - /, k);
  }
});

// ---- the view ----
const vm = (over = {}) => ({
  t: T, fn: M, profile: M.normalizeProfile({}), avatars: M.avatarList({ avatars: ["fox", "owl"] }),
  modes: M.optionList(null, M.FALLBACK_MODES), goals: M.optionList(null, M.FALLBACK_GOALS),
  movements: [], entries: [], summary: [], ...over,
});

test("view: empty account shows empty states, You, privacy off, and no email", () => {
  const host = new El("div");
  V.renderProfile(host, vm(), { save: async () => ({ ok: true, text: "" }), remove: async () => ({ ok: true, text: "" }) });
  assert.equal(find(host, "profile-who").textContent, "You");
  for (const id of ["profile-movements-empty", "profile-entries-empty", "profile-summary-empty"]) assert.ok(find(host, id), id);
  assert.equal(find(host, "profile-show-name").checked, false);
  assert.equal(find(host, "profile-credit").checked, false);
  assert.doesNotMatch(text(host), /\S+@\S+\.\S+/, "negative: nothing in the page looks like an email");
  assert.ok(find(host, "profile-avatar-fox") && find(host, "profile-avatar-none"));
  assert.ok(find(host, "profile-mode-2") && find(host, "profile-goal-2"), "three modes and three goals");
});

test("view: every field has a label; the name field is described by its hint and error", () => {
  const host = new El("div");
  V.renderProfile(host, vm(), { save: async () => ({ ok: true }), remove: async () => ({ ok: true }) });
  const ids = all(host).filter((n) => n instanceof El && ["input"].includes(n.tag)).map((n) => n.attrs.id);
  const labelled = new Set(all(host).filter((n) => n instanceof El && n.tag === "label").map((n) => n.attrs.for));
  for (const id of ids) assert.ok(labelled.has(id), `input ${id} has a label`);
  assert.match(find(host, "profile-name").attrs["aria-describedby"], /pf-name-hint/);
  assert.ok(all(host).some((n) => n.attrs?.id === "pf-name-hint"));
});

test("view: a bad name is refused on the page and nothing is saved", async () => {
  const host = new El("div");
  let saved = 0;
  V.renderProfile(host, vm(), { save: async () => { saved++; return { ok: true }; }, remove: async () => ({ ok: true }) });
  const name = find(host, "profile-name");
  name.value = "sam@example.com";
  name.dispatchEvent(new Event("input"));
  find(host, "profile-form").dispatchEvent(new Event("submit"));
  await tick();
  assert.equal(saved, 0);
  assert.equal(find(host, "profile-name-error").textContent, T.nameBad);
  assert.equal(name.attrs["aria-invalid"], "true");
  assert.equal(globalThis.__focused, name, "focus goes to the field with the error");
});

test("view: save sends the draft, shows the answer, and the delete asks first", async () => {
  const host = new El("div");
  const sent = [];
  const view = V.renderProfile(host, vm(), {
    save: async (d) => { sent.push(d); return { ok: true, text: T.saved, profile: M.normalizeProfile({ public_name: "Sam", avatar: "owl", modes: ["dance"], show_name: false }) }; },
    remove: async () => ({ ok: true, text: T.deleted, profile: M.normalizeProfile({}) }),
  });
  const name = find(host, "profile-name");
  name.value = " Sam ";
  name.dispatchEvent(new Event("input"));
  const owl = find(host, "profile-avatar-owl");
  owl.checked = true;
  owl.dispatchEvent(new Event("change"));
  const mode = find(host, "profile-mode-0");
  mode.checked = true;
  mode.dispatchEvent(new Event("change"));
  find(host, "profile-form").dispatchEvent(new Event("submit"));
  await tick();
  assert.deepEqual(sent[0], { name: "Sam", avatar: "owl", modes: ["dance"], goals: [], showName: false, creditTrainer: false });
  assert.equal(find(host, "profile-save-note").textContent, T.saved);
  assert.equal(find(host, "profile-who").textContent.endsWith("Sam"), true);
  assert.ok(view.devicesAnchor.attrs.hidden !== undefined, "the devices anchor itself shows nothing");
  // delete: hidden confirmation first, "Keep them" takes focus, "Yes" deletes and the form returns to defaults
  const sure = find(host, "profile-delete-sure");
  assert.ok("hidden" in sure.attrs);
  find(host, "profile-delete").click();
  assert.equal("hidden" in sure.attrs, false);
  assert.equal(globalThis.__focused, find(host, "profile-delete-no"));
  find(host, "profile-delete-no").click();
  assert.ok("hidden" in sure.attrs);
  find(host, "profile-delete").click();
  find(host, "profile-delete-yes").click();
  await tick();
  assert.equal(find(host, "profile-delete-note").textContent, T.deleted);
  assert.equal(find(host, "profile-name").value, "");
  assert.equal(find(host, "profile-who").textContent, "You");
});

test("view: a failed save keeps the form and says so", async () => {
  const host = new El("div");
  V.renderProfile(host, vm(), { save: async () => ({ ok: false, text: T.saveFailed }), remove: async () => ({ ok: false, text: T.deleteFailed }) });
  find(host, "profile-form").dispatchEvent(new Event("submit"));
  await tick();
  assert.equal(find(host, "profile-save-note").textContent, T.saveFailed);
  assert.equal(find(host, "profile-save-note").attrs["data-tone"], "bad");
  assert.equal(find(host, "profile-save").attrs.disabled, undefined);
});

test("view: signed-out and error states", () => {
  const a = new El("div");
  V.renderProfileSignedOut(a, { t: T });
  assert.ok(find(a, "profile-signed-out") && find(a, "profile-signin"));
  const b = new El("div");
  let retried = 0;
  V.renderProfileError(b, { t: T }, () => { retried++; });
  find(b, "profile-retry").click();
  assert.equal(retried, 1);
});

test("view: the section title is an h2 (the Me page holds the one h1) and the view mounts no share list", () => {
  const host = new El("div");
  const view = V.renderProfile(host, vm(), { save: async () => ({ ok: true }), remove: async () => ({ ok: true }) });
  assert.equal(find(host, "profile-title").tag, "h2");
  assert.equal(all(host).filter((n) => n.tag === "h1").length, 0, "negative: no h1 in the section");
  assert.equal(find(host, "share-list"), null, "negative: the Me page mounts the share list, not this view");
  assert.equal(V.mountProfileExtras, undefined, "negative: the old share hook is gone");
  assert.ok("hidden" in view.devicesAnchor.attrs && view.devicesAnchor.children.length === 0, "the devices anchor is empty and hidden");
});

// ---- the glue against a fake of the routes ----
function fakeServer({ available = true, signedIn = true, profile = { public_name: null, avatar: null, modes: [], goals: [], show_name: false, credit_me_as_trainer: false }, profileStatus = 200 } = {}) {
  const state = { profile: { ...profile }, calls: [] };
  globalThis.fetch = async (url, opts = {}) => {
    const method = opts.method || "GET";
    state.calls.push([method, url, opts.body ? JSON.parse(opts.body) : undefined]);
    const reply = (status, body) => ({ status, headers: { get: () => null }, json: async () => body });
    if (url === "api/auth/me") return reply(200, available ? { available: true, signed_in: signedIn, ...(signedIn ? { email: "sam@example.com", retention: { opted_in: false } } : {}) } : { available: false, signed_in: false });
    if (url === "api/avatars") return reply(200, { avatars: ["fox", "owl"] });
    if (url === "api/me/history") return reply(200, { entries: [{ entry_id: "lateral-raise", name: "Lateral raise", takes: 2 }] });
    if (url === "api/me/profile") {
      if (profileStatus !== 200) return reply(profileStatus, { error: "x" });
      if (method === "PUT") { state.profile = { ...JSON.parse(opts.body) }; return reply(200, state.profile); }
      if (method === "DELETE") { state.profile = { public_name: null, avatar: null, modes: [], goals: [], show_name: false, credit_me_as_trainer: false }; return reply(200, state.profile); }
      return reply(200, state.profile);
    }
    return reply(404, {});
  };
  return state;
}

const mounted = async (opts) => {
  const state = fakeServer(opts);
  const el = new El("main");
  const stop = G.mountProfile(el);
  await tick(); await tick(); await tick(); await tick();
  return { state, el, stop };
};

test("glue: loads profile, avatars and history, saves with PUT, deletes with DELETE", async () => {
  const { state, el, stop } = await mounted();
  assert.ok(find(el, "profile-form"));
  assert.equal(find(el, "profile-movements-0").textContent.includes("Lateral raise"), true);
  assert.equal(find(el, "profile-summary").textContent, "2 takes kept across 1 movement.");
  const name = find(el, "profile-name");
  name.value = "Sam";
  name.dispatchEvent(new Event("input"));
  find(el, "profile-form").dispatchEvent(new Event("submit"));
  await tick(); await tick();
  const put = state.calls.find((c) => c[0] === "PUT");
  assert.equal(put[1], "api/me/profile");
  assert.equal(put[2].public_name, "Sam");
  assert.equal(put[2].show_name, false, "privacy stays off unless the person switches it");
  assert.equal(find(el, "profile-save-note").textContent, T.saved);
  find(el, "profile-delete").click();
  find(el, "profile-delete-yes").click();
  await tick(); await tick();
  assert.ok(state.calls.some((c) => c[0] === "DELETE" && c[1] === "api/me/profile"));
  assert.equal(find(el, "profile-who").textContent, "You");
  assert.equal(JSON.stringify(state.calls).includes("sam@example.com"), false, "negative: the email is never sent back");
  assert.equal(text(el).includes("sam@example.com"), false, "negative: the email is not on the page");
  stop();
});

test("glue: signed out, sign-in off and a failing server each have their own state", async () => {
  assert.ok(find((await mounted({ signedIn: false })).el, "profile-signed-out"));
  const off = (await mounted({ available: false })).el;
  assert.equal(find(off, "profile-form"), null);
  assert.equal(find(off, "profile-signed-out"), null, "off shows no sign-in prompt");
  assert.ok(find((await mounted({ profileStatus: 401 })).el, "profile-signed-out"), "a 401 on the profile is signed out");
  assert.ok(find((await mounted({ profileStatus: 500 })).el, "profile-error"));
});

test("glue: a refused save (400) says the choice was not accepted", async () => {
  const { state, el } = await mounted();
  const real = globalThis.fetch;
  globalThis.fetch = async (url, opts = {}) => (opts.method === "PUT" ? { status: 400, headers: { get: () => null }, json: async () => ({ error: "bad" }) } : real(url, opts));
  find(el, "profile-form").dispatchEvent(new Event("submit"));
  await tick(); await tick();
  assert.equal(find(el, "profile-save-note").textContent, T.saveRefused);
  assert.ok(state);
});

test("one entry point: the glue has no header link of its own; a delete tells the page", async () => {
  assert.equal(G.mountProfileLink, undefined, "negative: no Profile link beside the Me link");
  assert.equal("headerLink" in T, false);
  const { el } = await mounted();
  let heard = 0;
  window.addEventListener("profile-deleted", () => { heard++; });
  find(el, "profile-delete").click();
  find(el, "profile-delete-yes").click();
  await tick(); await tick();
  assert.equal(heard, 1, "My 3D model hears that the default was cleared");
});
