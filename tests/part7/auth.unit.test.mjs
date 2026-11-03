// Sign-in and Me: pure logic (web/model/auth.js, web/model/me.js) and the views on a fake DOM.
//   node --test tests/part7/auth.unit.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { El, installDom, all, find } from "./fake-dom.mjs";

const web = path.join(path.dirname(fileURLToPath(import.meta.url)), "../../web");
installDom();
const cls = (el) => (el.attrs.class || "").split(/\s+/).filter(Boolean);
Object.defineProperty(El.prototype, "classList", { get() { return { add: (c) => { this.attrs.class = [...new Set([...cls(this), c])].join(" "); } }; } });
Object.defineProperty(El.prototype, "hidden", {
  get() { return "hidden" in this.attrs; },
  set(v) { if (v) this.attrs.hidden = ""; else delete this.attrs.hidden; },
});

const A = await import("../../web/model/auth.js");
const M = await import("../../web/model/me.js");
const V = await import("../../web/views/auth.js");
const W = await import("../../web/views/me.js");

test("email shape: one @, a dotted domain, no spaces, length limits", () => {
  for (const ok of ["a@b.co", " name@example.com ", "first.last+tag@sub.example.org"]) assert.equal(A.isEmail(ok), true, ok);
  for (const bad of ["", "name", "name@", "@example.com", "a@b", "a b@example.com", "a@@b.co", "a@b..co", `${"x".repeat(65)}@example.com`, `a@${"b".repeat(250)}.com`, null, undefined]) {
    assert.equal(A.isEmail(bad), false, String(bad));
  }
});

test("code input takes digits only, at most 6, and accepts a paste of '123 456'", () => {
  assert.equal(A.codeDigits("123 456"), "123456");
  assert.equal(A.codeDigits("12a3-4b5c6"), "123456");
  assert.equal(A.codeDigits("1234567890"), "123456");
  assert.equal(A.codeDigits("abc"), "");
  assert.equal(A.codeDigits(null), "");
  assert.equal(A.isCode("123 456"), true);
  assert.equal(A.isCode("12345"), false);
  assert.equal(A.isCode("12345a"), false);
});

test("the address hash: form, token, and the scrubbed hash never carries the token", () => {
  assert.deepEqual(A.parseSigninHash("#/signin"), { kind: "form" });
  assert.deepEqual(A.parseSigninHash("#/signin/abc_DEF-123"), { kind: "token", token: "abc_DEF-123" });
  assert.deepEqual(A.parseSigninHash("#/signin/a%2Fb"), { kind: "token", token: "a/b" });
  assert.deepEqual(A.parseSigninHash("#/me"), { kind: "none" });
  assert.deepEqual(A.parseSigninHash("#/signin/a/b"), { kind: "none" });
  assert.equal(A.scrubbedHash(), "#/signin");
  assert.equal(A.scrubbedHash("#/signin/secret-token").includes("secret-token"), false);
});

test("the sign-in state machine: email, sending, code, verifying, and each failure", () => {
  let s = A.initialState();
  assert.equal(s.phase, "email");
  s = A.step(s, { type: "email-input", value: "nope" });
  s = A.step(s, { type: "submit-email" });
  assert.equal(s.phase, "email");
  assert.equal(s.error, A.TEXT.emailBad);
  s = A.step(s, { type: "email-input", value: " me@example.com " });
  assert.equal(s.error, "");
  s = A.step(s, { type: "submit-email" });
  assert.deepEqual([s.phase, s.email], ["sending", "me@example.com"]);
  assert.equal(A.step(s, { type: "submit-email" }).phase, "sending", "a second submit while sending does nothing");
  s = A.step(s, { type: "start-failed", status: 429 });
  assert.deepEqual([s.phase, s.error], ["email", A.TEXT.tooMany]);
  s = A.step(A.step(s, { type: "submit-email" }), { type: "started" });
  assert.deepEqual([s.phase, s.code], ["code", ""]);
  s = A.step(s, { type: "code-input", value: "12 3" });
  s = A.step(s, { type: "submit-code" });
  assert.deepEqual([s.phase, s.error], ["code", A.TEXT.codeShort]);
  s = A.step(s, { type: "code-input", value: "123 456" });
  assert.equal(s.code, "123456");
  s = A.step(s, { type: "submit-code" });
  assert.equal(s.phase, "verifying");
  s = A.step(s, { type: "verify-failed", status: 400, fromLink: false });
  assert.deepEqual([s.phase, s.code, s.error], ["code", "", A.TEXT.invalid]);
  s = A.step(s, { type: "other-email" });
  assert.equal(s.phase, "email");
  s = A.step(A.initialState(), { type: "verify-token" });
  assert.equal(s.phase, "verifying");
  s = A.step(s, { type: "verify-failed", status: 400, fromLink: true });
  assert.deepEqual([s.phase, s.error], ["email", A.TEXT.invalid]);
  assert.equal(A.step(A.initialState(), { type: "off" }).phase, "off");
  assert.equal(A.step(s, { type: "unknown" }), s);
});

test("failure words: every refused verify is the one sentence; limits and offline have their own", () => {
  for (const status of [400, 401, 404, 410, 500]) assert.equal(A.verifyError(status), A.TEXT.invalid);
  assert.equal(A.verifyError(429), A.TEXT.tooMany);
  assert.equal(A.verifyError(0), A.TEXT.offline);
  assert.equal(A.startError(429), A.TEXT.tooMany);
  assert.equal(A.startError(400), A.TEXT.startFailed);
  assert.equal(A.startError(0), A.TEXT.offline);
});

test("auth/me: odd answers mean signed out; the header link is invisible when mail is off", () => {
  for (const odd of [null, undefined, "x", 5, {}, { available: "yes" }]) {
    const info = A.meInfo(odd);
    assert.deepEqual([info.available, info.signedIn], [false, false]);
    assert.equal(A.headerLink(info), null);
  }
  assert.equal(A.headerLink(A.meInfo({ available: false, signed_in: true, email: "a@b.co" })), null, "negative: off wins over a stale session");
  assert.deepEqual(A.headerLink(A.meInfo({ available: true, signed_in: false })), { href: "#/signin", label: "Sign in" });
  const on = A.meInfo({ available: true, signed_in: true, user_id: "u-1", email: "a@b.co", retention: { opted_in: true, days: 90, consent_version: "v" } });
  assert.deepEqual([on.email, on.retention.optedIn, on.retention.days, on.retention.version], ["a@b.co", true, 90, "v"]);
  assert.deepEqual(A.headerLink(on), { href: "#/me", label: "Me" });
  // signed out, Me sits beside Sign in (the Me page works signed out); signed in or with sign-in off, no second link
  assert.deepEqual(A.headerMeLink(A.meInfo({ available: true, signed_in: false })), { href: "#/me", label: "Me" });
  assert.equal(A.headerMeLink(on), null);
  assert.equal(A.headerMeLink(A.meInfo({ available: false, signed_in: false })), null);
});

test("me model: claim input, takes rows, delete summary, consent body", () => {
  assert.equal(M.jobIdFrom("job1"), "job1");
  assert.equal(M.jobIdFrom("  https://x.test/app/#/result/job-9?x=1 "), "job-9");
  assert.equal(M.jobIdFrom("#/group/g_2"), "g_2");
  for (const bad of ["", "   ", "a b", "../x", "x".repeat(65), "%E0"]) assert.equal(M.jobIdFrom(bad), "", JSON.stringify(bad));
  assert.match(M.claimError(404), /not found/);
  assert.match(M.claimError(409), /another account/);
  assert.equal(M.claimError(401), "Sign in to see this.");
  const rows = M.takeRows({ takes: [
    { job_id: "a", kind: "follow", entry_id: "e", created_at: "2026-10-31T10:05:00Z", score: 61.4, grade: "D" },
    { job_id: "g", kind: "follow", entry_id: "e", created_at: "bad", score: null, grade: null },
    { job_id: "t", kind: "trainer", entry_id: "e 1" }, null, { kind: "follow" },
  ] });
  assert.deepEqual(rows.map((r) => [r.jobId, r.kind, r.score, r.grade, r.tone, r.href]), [
    ["a", "Follow take", "61", "D", "warn", "#/result/a"],
    ["g", "Follow take", "", "", "warn", "#/result/g"],
    ["t", "Teacher take", "", "", "warn", "#/watch/e%201"],
  ]);
  assert.equal(rows[0].when, "Oct 31, 10:05 AM");
  assert.equal(rows[1].when, "");
  assert.equal(M.holdsTake({ takes: [{ job_id: "a" }] }, "a"), true);
  assert.equal(M.holdsTake({ takes: [{ job_id: "a" }] }, "b"), false);
  assert.equal(M.holdsTake(null, "a"), false);
  assert.equal(M.deletedSummary({ takes_removed: 1, entries_unlinked: 2 }), "1 take removed. 2 movements unlinked.");
  assert.equal(M.deletedSummary({}), "0 takes removed. 0 movements unlinked.");
  assert.deepEqual(M.busyIds({ busy: ["a", 3, "b"] }), ["a", "b"]);
  assert.deepEqual(M.busyIds(null), []);
  assert.deepEqual(M.consentBody(true), { retention: true, version: M.CONSENT_VERSION });
  assert.deepEqual(M.consentBody(0), { retention: false, version: M.CONSENT_VERSION });
});

test("consent text covers the design's requirements and the user-facing words are clean", () => {
  const text = M.CONSENT_LINES.join(" ");
  for (const need of [/optional/, /email address/, /90 days instead of 7/, /progress over weeks/, /Untick/, /delete the copies of your takes and every comparison made from them right away/, /Anyone who holds the link to a take can keep it/, /Delete my data/, /Meta/, /only to send sign-in mail/]) {
    assert.match(text, need);
  }
  const all = JSON.stringify([A.TEXT, M.TEXT, M.CONSENT_LINES, A.sentNotice("a@b.co"), M.TEXT.signedInAs("a@b.co")]);
  assert.doesNotMatch(all, /coach|medical|injury/i);
  assert.doesNotMatch(all, /[\u2013\u2014]/);
  assert.match(M.TEXT.deleteBody, /teacher's movement stays in the catalog/);
});

test("the views use no coach, medical or injury word and no dash characters", () => {
  for (const f of ["views/auth.js", "views/me.js", "auth.js", "model/auth.js", "model/me.js", "theme/auth.css"]) {
    const src = fs.readFileSync(path.join(web, f), "utf8");
    assert.doesNotMatch(src, /coach|medical|injury/i, f);
    assert.doesNotMatch(src, /[\u2013\u2014]/, f);
  }
});

test("the sign-in glue stores nothing in the browser", () => {
  for (const f of ["auth.js", "model/auth.js", "model/me.js", "views/auth.js", "views/me.js"]) {
    assert.doesNotMatch(fs.readFileSync(path.join(web, f), "utf8"), /localStorage|sessionStorage|document\.cookie/, f);
  }
});

const host = () => new El("div");

test("email view: types, submits, shows and updates the error line", () => {
  const el = host();
  const got = { typed: [], submits: 0 };
  const view = V.renderEmail(el, { t: A.TEXT, email: "x@y.co" }, { onInput: (v) => got.typed.push(v), onSubmit: () => { got.submits++; } });
  const input = find(el, "auth-email");
  assert.equal(input.attrs.value, "x@y.co");
  assert.equal(input.attrs.type, "email");
  input.value = "me@example.com";
  input.dispatchEvent(new Event("input"));
  find(el, "auth-email-form").dispatchEvent(Object.assign(new Event("submit"), { preventDefault() {} }));
  assert.deepEqual([got.typed, got.submits], [["me@example.com"], 1]);
  assert.equal(find(el, "auth-error").textContent, "");
  view.setError("Enter an email address like name@example.com.");
  assert.match(find(el, "auth-error").textContent, /name@example/);
});

test("code view: numeric field, notice with the address, the other-email button", () => {
  const el = host();
  let other = 0;
  const view = V.renderCode(el, { t: A.TEXT, notice: A.sentNotice("a@b.co") }, { onInput: A.codeDigits, onSubmit() {}, onOther: () => { other++; } });
  const input = find(el, "auth-code");
  assert.equal(input.attrs.inputmode, "numeric");
  assert.equal(input.attrs.autocomplete, "one-time-code");
  assert.match(find(el, "auth-notice").textContent, /a@b\.co/);
  assert.equal(find(el, "auth-code-title").textContent, "Check your mail");
  input.value = "123 456";
  input.dispatchEvent(new Event("input"));
  assert.equal(input.value, "123456", "a paste is cleaned in the box");
  find(el, "auth-other").click();
  assert.equal(other, 1);
  view.setError(A.TEXT.invalid);
  assert.equal(find(el, "auth-error").textContent, A.TEXT.invalid);
});

test("off view and header link: sign-in leaves no trace when mail is off", () => {
  const el = host();
  V.renderOff(el, { t: A.TEXT });
  assert.equal(find(el, "auth-off") !== null, true);
  const slot = host();
  V.renderAuthLink(slot, null);
  assert.equal(slot.hidden, true);
  assert.equal(find(slot, "auth-link"), null, "negative: no link element");
  assert.equal(slot.children.length, 0);
  V.renderAuthLink(slot, { href: "#/signin", label: "Sign in" });
  assert.equal(slot.hidden, false);
  assert.equal(find(slot, "auth-link").attrs.href, "#/signin");
  V.renderAuthLink(slot, { href: "#/signin", label: "Sign in" }, { href: "#/me", label: "Me" });
  assert.deepEqual(slot.children.map((c) => c.attrs["data-testid"]), ["me-link", "auth-link"], "Me first, Sign in still there");
  assert.equal(find(slot, "me-link").attrs.href, "#/me");
  V.renderAuthLink(slot, null, { href: "#/me", label: "Me" });
  assert.equal(slot.children.length, 0, "negative: sign-in off shows no Me link either");
});

test("me view: who, consent unticked by default, takes, two-step delete, outcomes", async () => {
  const el = host();
  const calls = [];
  const rows = M.takeRows({ takes: [{ job_id: "job1", kind: "follow", score: 61, grade: "D", created_at: "2026-10-31T10:00:00Z" }] });
  const view = W.renderMe(el, { t: M.TEXT, email: "a@b.co", optedIn: false, consentLines: M.CONSENT_LINES, rows }, {
    signOut: () => calls.push("signout"),
    consent: async (on) => { calls.push(["consent", on]); return { ok: true, text: "Saved." }; },
    claim: async (raw) => { calls.push(["claim", raw]); return { ok: false, text: M.claimError(409) }; },
    delete: async () => { calls.push("delete"); return { ok: false, text: M.TEXT.deleteBusy, busy: ["busy1"] }; },
  });
  assert.equal(find(el, "me-email").textContent, "Signed in as a@b.co");
  const box = find(el, "me-retention");
  assert.equal("checked" in box.attrs, false, "negative: the retention box starts unticked");
  assert.equal(find(el, "me-take-0").attrs["data-job"], "job1");
  assert.equal(find(el, "me-takes-empty").hidden, true);
  view.setRows([]);
  assert.equal(find(el, "me-takes-empty").hidden, false);
  assert.equal(find(el, "me-takes").hidden, true);

  box.checked = true;
  box.dispatchEvent(new Event("change"));
  await new Promise((r) => setImmediate(r));
  assert.deepEqual(calls.at(-1), ["consent", true]);
  assert.equal(find(el, "me-consent-note").textContent, "Saved.");

  find(el, "me-claim-input").value = "job2";
  find(el, "me-claim-form").dispatchEvent(Object.assign(new Event("submit"), { preventDefault() {} }));
  await new Promise((r) => setImmediate(r));
  assert.deepEqual(calls.at(-1), ["claim", "job2"]);
  assert.equal(find(el, "me-claim-note").textContent, "This take is kept by another account.");

  assert.equal(find(el, "me-delete-sure").hidden, true);
  find(el, "me-delete").click();
  assert.equal(find(el, "me-delete-sure").hidden, false);
  assert.equal(calls.includes("delete"), false, "negative: the first click deletes nothing");
  find(el, "me-delete-cancel").click();
  assert.equal(find(el, "me-delete-sure").hidden, true);
  find(el, "me-delete").click();
  find(el, "me-delete-confirm").click();
  await new Promise((r) => setImmediate(r));
  assert.equal(calls.at(-1), "delete");
  assert.match(find(el, "me-delete-note").textContent, /Try again when these finish/);
  assert.equal(find(el, "me-busy").textContent, "busy1");
  find(el, "me-signout").click();
  assert.equal(calls.at(-1), "signout");
});

test("keep slot: button claims once, kept state links to Me", async () => {
  const el = host();
  let n = 0;
  W.renderKeep(el, { t: M.TEXT }, { onKeep: async () => { n++; return { ok: false, text: M.claimError(409) }; } });
  find(el, "keep-take").click();
  await new Promise((r) => setImmediate(r));
  assert.equal(n, 1);
  assert.equal(find(el, "keep-note").textContent, "This take is kept by another account.");
  const kept = host();
  W.renderKept(kept, { t: M.TEXT, href: "#/me" });
  assert.equal(find(kept, "keep-kept").textContent, "Kept. See it in Me.");
  assert.equal(find(kept, "keep-open").attrs.href, "#/me");
  assert.equal(find(kept, "keep-take"), null);
});

test("signed-out, error and deleted views", () => {
  for (const [fn, id, arg] of [[W.renderMeSignedOut, "me-signed-out", {}], [W.renderMeError, "me-error", {}], [W.renderDeleted, "me-deleted", { summary: "x" }]]) {
    const el = host();
    fn(el, { t: M.TEXT, ...arg });
    assert.notEqual(find(el, id), null, id);
  }
  assert.equal(all(host()).length, 1);
});

test("TICKET-327 Me: the takes card sits first under the account card, before consent and claims (one tap from home)", () => {
  const el = new El("div");
  W.renderMe(el, { t: M.TEXT, email: "a@b.co", optedIn: false, consentLines: [], rows: M.takeRows({ takes: [{ job_id: "j1", kind: "follow", score: 61, grade: "D" }] }) },
    { signOut() {}, consent: async () => ({}), claim: async () => ({}), delete: async () => ({}) });
  const ids = el.children.map((c) => c.attrs["data-testid"] ?? null);
  assert.ok(ids.indexOf("me-takes-card") > 0 && ids.indexOf("me-takes-card") < ids.indexOf("me-consent"));
  assert.equal(find(el, "me-take-0").children.at(-1).attrs.href, "#/result/j1");
});
