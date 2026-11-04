// The consent and age step, the trainer publish opt-in, the landing pause and the captions track on a fake DOM
// (docs/specs/consent-and-age.md AC-CA10 to AC-CA13, trainer-publish.md AC-TP4).   node --test tests/part7/consent-gate.dom.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { installDom, find } from "./fake-dom.mjs";

const { store } = installDom();
const gate = await import("../../web/consent-gate.js");
const { mountConsentGate, confirmThen } = gate;
const { CONSENT_VERSION, CONSENT_TEXT } = await import("../../web/model/consent-text.js");
const consentStore = await import("../../web/model/consent-store.js");
const policy = await import("../../web/policy.js");
const { trainerPublishBox } = await import("../../web/trainer-publish.js");
const { wirePause, TEXT: PAUSE } = await import("../../web/landing.js");
const { attachCaptions } = await import("../../web/captions.js");

const REQUIRED = { required: true, version: CONSENT_VERSION };
const NOW = new Date("2026-11-02T10:00:00Z");
const slotEl = () => document.createElement("div");
const pick = (root, testid, value) => { find(root, testid).value = value; };
const tickAll = (root) => { for (const i of CONSENT_TEXT.items) find(root, `consent-item-${i.key}`).checked = true; };

test("AC-CA10 outside a gated build the short consent line shows and the take flow mounts at once", () => {
  store.clear();
  const slot = slotEl();
  let ready = 0;
  assert.deepEqual(mountConsentGate(slot, () => ready++, { policy: { required: false } }), { ready: true });
  assert.equal(ready, 1);
  assert.ok(find(slot, "consent-line") && find(slot, "consent-policy-links"));
  assert.equal(find(slot, "age-step"), null);
});

test("AC-CA16 where the server's minimum is 18, a 13 to 17 answer never mounts, stored or new; at 13 it does", () => {
  store.clear();
  const slot = slotEl();
  let ready = 0;
  mountConsentGate(slot, () => ready++, { policy: REQUIRED, now: NOW, minimum: 18 });
  pick(slot, "age-month", "1");
  pick(slot, "age-year", "2010");
  find(slot, "age-next").click();
  assert.ok(find(slot, "age-blocked"));
  const again = slotEl();
  assert.deepEqual(mountConsentGate(again, () => ready++, { policy: REQUIRED, now: NOW, minimum: 18 }), { ready: false });
  assert.ok(find(again, "age-blocked"));
  assert.equal(ready, 0);
  const opened = slotEl();
  mountConsentGate(opened, () => ready++, { policy: REQUIRED, now: NOW, minimum: 13 });
  assert.equal(find(opened, "age-blocked"), null);
  assert.ok(find(opened, "consent-step"));
  store.clear();
});

test("AC-CA11 gated: age first, then one box per point; nothing mounts until every box is ticked", () => {
  store.clear();
  const slot = slotEl();
  let ready = 0;
  assert.deepEqual(mountConsentGate(slot, () => ready++, { policy: REQUIRED, now: NOW }), { ready: false });
  assert.ok(find(slot, "age-step"));
  find(slot, "age-next").click();
  assert.equal(find(slot, "age-error").hidden, false, "no answer, no step on");
  pick(slot, "age-month", "1");
  pick(slot, "age-year", "1990");
  find(slot, "age-next").click();
  assert.ok(find(slot, "consent-step"));
  for (const i of CONSENT_TEXT.items) assert.equal(find(slot, `consent-item-${i.key}`).checked, undefined, `${i.key} starts unticked`);
  find(slot, "consent-agree").click();
  assert.equal(ready, 0);
  assert.equal(find(slot, "consent-error").hidden, false);
  tickAll(slot);
  find(slot, "consent-agree").click();
  assert.equal(ready, 1);
  assert.ok(find(slot, "consent-done"));
  assert.equal(consentStore.consentFields().age_band, "adult");
  assert.equal(consentStore.consentFields().consent.version, CONSENT_VERSION);
});

test("AC-CA12 a stored current answer mounts at once; a stale one asks the consent points again, not the age", () => {
  const slot = slotEl();
  let ready = 0;
  mountConsentGate(slot, () => ready++, { policy: REQUIRED, now: NOW });
  assert.equal(ready, 1);
  assert.ok(find(slot, "consent-done"));
  const doc = JSON.parse(store.get(consentStore.KEY));
  store.set(consentStore.KEY, JSON.stringify({ ...doc, version: "2020-01-01.1" }));
  const again = slotEl();
  mountConsentGate(again, () => ready++, { policy: REQUIRED, now: NOW });
  assert.equal(ready, 1);
  assert.ok(find(again, "consent-step") && !find(again, "age-step"));
});

test("AC-MP5 the Meta tick is shown only with the gate open, is optional, and is kept only when ticked", () => {
  for (const [tick, want] of [[false, undefined], [true, true]]) {
    store.clear();
    consentStore.saveAge("adult", undefined);
    const slot = slotEl();
    let ready = 0;
    mountConsentGate(slot, () => ready++, { policy: { ...REQUIRED, meta_item: "meta" }, now: NOW });
    assert.match(find(slot, "consent-meta-goes").textContent, /no time limit/);
    tickAll(slot);
    find(slot, "consent-item-meta").checked = tick;
    find(slot, "consent-item-meta-adults").checked = tick;
    find(slot, "consent-agree").click();
    assert.equal(ready, 1, "the required boxes alone are enough");
    assert.equal(consentStore.loadAnswers(undefined).items.meta, want);
    assert.equal(consentStore.loadAnswers(undefined).items.meta_adults, want);
  }
  store.clear();
  consentStore.saveAge("adult", undefined);
  const closed = slotEl();
  mountConsentGate(closed, () => {}, { policy: REQUIRED, now: NOW });
  assert.equal(find(closed, "consent-item-meta"), null, "no box while the gate is closed");
});

test("AC-CA13 under 13 closes the screen and stays closed in this browser; the take flow never mounts", () => {
  store.clear();
  const slot = slotEl();
  let ready = 0;
  mountConsentGate(slot, () => ready++, { policy: REQUIRED, now: NOW });
  pick(slot, "age-month", "6");
  pick(slot, "age-year", "2016");
  find(slot, "age-next").click();
  assert.ok(find(slot, "age-blocked"));
  assert.equal(find(slot, "consent-step"), null);
  const later = slotEl();
  assert.deepEqual(mountConsentGate(later, () => ready++, { policy: REQUIRED, now: NOW }), { ready: false });
  assert.ok(find(later, "age-blocked"));
  assert.equal(ready, 0);
});

test("AC-TP4 trainer publish: nothing outside prod, an unticked opt-in in prod, none for a minor", () => {
  store.clear();
  policy.resetPolicy();
  assert.deepEqual(trainerPublishBox().extra(), {});
  assert.equal(trainerPublishBox().el, null);
  policy.setPolicy({ switches: { trainer_public: false }, consent: REQUIRED });
  assert.equal(trainerPublishBox().el, null, "no box before the age answer exists (private-default D2)");
  consentStore.saveAge("adult");
  const box = trainerPublishBox();
  assert.deepEqual(box.extra(), {}, "private unless ticked");
  find(box.el, "publish-public").checked = true;
  assert.deepEqual(box.extra(), {}, "PM-B3: still private without the statement");
  find(box.el, "publish-statement").checked = true;
  assert.deepEqual(box.extra(), { public: true, nobody_under_18: true });
  consentStore.saveAge("minor");
  const minor = trainerPublishBox();
  assert.ok(find(minor.el, "publish-minor") || minor.el.getAttribute("data-testid") === "publish-minor");
  assert.deepEqual(minor.extra(), {});
  assert.deepEqual(box.extra(), {}, "an opt-in ticked before the minor answer does not count");
  policy.resetPolicy();
});

test("LEG-M8 landing: the loop plays unless reduced motion is asked for, and the button pauses and plays it", async () => {
  const video = { paused: true, play() { this.paused = false; return Promise.resolve(); }, pause() { this.paused = true; } };
  const button = document.createElement("button");
  button.hidden = true;
  const toggle = wirePause(video, button, false);
  await new Promise((r) => setTimeout(r, 0));
  assert.equal(button.hidden, false);
  assert.equal(video.paused, false);
  assert.equal(button.textContent, PAUSE.pause);
  await toggle();
  assert.equal(video.paused, true);
  assert.equal(button.getAttribute("aria-pressed"), "true");
  const still = { paused: true, play() { this.paused = false; return Promise.resolve(); }, pause() {} };
  wirePause(still, document.createElement("button"), true);
  assert.equal(still.paused, true, "reduced motion: no autoplay");
});

test("LEG-M8 captions: a track joins the trainer video only when there are cues", async () => {
  const video = document.createElement("video");
  const added = await attachCaptions(video, "squat", { load: async () => ({ cues: [{ start_s: 0, end_s: 1, text: "Down" }] }), makeUrl: () => "blob:x" });
  assert.equal(added, true);
  const track = find(video, "trainer-captions");
  assert.equal(track.getAttribute("kind"), "captions");
  assert.equal(track.getAttribute("src"), "blob:x");
  const bare = document.createElement("video");
  assert.equal(await attachCaptions(bare, "squat", { load: async () => null }), false);
  assert.equal(bare.children.length, 0);
});

test("B3 the Meta tick needs the 18 statement: without it nothing goes on and the person is told", () => {
  store.clear();
  consentStore.saveAge("adult", undefined);
  const slot = slotEl();
  let ready = 0;
  mountConsentGate(slot, () => ready++, { policy: { ...REQUIRED, meta_item: "meta" }, now: NOW });
  tickAll(slot);
  find(slot, "consent-item-meta").checked = true;
  find(slot, "consent-agree").click();
  assert.equal(ready, 0);
  assert.equal(find(slot, "consent-error").textContent, CONSENT_TEXT.metaItem.adultsMissing);
  assert.equal(consentStore.loadAnswers(undefined).items, undefined, "nothing was saved");
  find(slot, "consent-item-meta").checked = false;
  find(slot, "consent-item-meta-adults").checked = true;
  find(slot, "consent-agree").click();
  assert.equal(ready, 1, "the statement alone is not a Meta tick");
  assert.equal(consentStore.loadAnswers(undefined).items.meta, undefined);
  assert.equal(consentStore.loadAnswers(undefined).items.meta_adults, undefined);
});

test("B2 the consent answers belong to the account: another account, a sign-out or a signed-out visit is asked again", () => {
  const ALL = { analysis: true, biometric: true, processors: true, people_in_frame: true, meta: true, meta_adults: true };
  const give = (id) => {
    store.clear();
    consentStore.setAccount(id, undefined);
    consentStore.saveAge("adult", undefined);
    consentStore.saveConsent(ALL, undefined);
  };
  give("user-a");
  assert.equal(consentStore.consentFields().consent.items.meta, true, "account A sends its own tick");
  assert.equal(consentStore.consentFields().consent.account, "user-a");
  consentStore.setAccount("user-b", undefined);
  assert.equal(consentStore.loadAnswers(undefined), null, "account B finds no answer: age, points and tick are gone");
  assert.deepEqual(consentStore.consentFields(), {});
  const slot = slotEl();
  let ready = 0;
  mountConsentGate(slot, () => ready++, { policy: REQUIRED, now: NOW });
  assert.ok(find(slot, "age-step") && ready === 0, "B is asked the age question again");
  give("user-a");
  consentStore.forgetAccount(undefined);
  assert.equal(consentStore.loadAnswers(undefined), null, "sign-out drops the answers");
  give("user-a");
  consentStore.setAccount("", undefined);
  assert.equal(consentStore.loadAnswers(undefined), null, "signed out drops them too");
  store.clear();
  consentStore.saveAge("under13", undefined);
  consentStore.setAccount("user-c", undefined);
  assert.equal(consentStore.loadAnswers(undefined).age_band, "under13", "a closed screen is not cleared by changing account");
});

test("B2 the gate waits for api/auth/me, then reads the answers of the account that came back", () => {
  store.clear();
  consentStore.setAccount("user-a", undefined);
  consentStore.saveAge("adult", undefined);
  consentStore.saveConsent({ analysis: true, biometric: true, processors: true, people_in_frame: true }, undefined);
  consentStore.beginAccountCheck();
  const slot = slotEl();
  let ready = 0;
  mountConsentGate(slot, () => ready++, { policy: REQUIRED, now: NOW });
  assert.equal(ready, 0, "nothing is read while the account is unknown");
  consentStore.setAccount("user-b", undefined);
  assert.ok(find(slot, "age-step"));
  assert.equal(ready, 0);
});

test("B2 a signed-out answer followed into sign-in waits for the new person: nothing is sent or stamped until they confirm", () => {
  const signedOutAnswer = () => {
    store.clear();
    consentStore.forgetAccount(undefined);
    consentStore.setAccount("", undefined);
    consentStore.saveAge("adult", undefined);
    consentStore.saveConsent({ analysis: true, biometric: true, processors: true, people_in_frame: true, meta: true, meta_adults: true }, undefined);
    consentStore.setAccount("user-d", undefined);
  };
  signedOutAnswer();
  assert.equal(consentStore.loadAnswers(undefined).account, "", "not stamped yet");
  assert.deepEqual(consentStore.consentFields(), {}, "no consent is sent before the confirm");
  assert.deepEqual(consentStore.consentHeader(), {}, "no upload header either");
  const slot = slotEl();
  let ready = 0;
  mountConsentGate(slot, () => ready++, { policy: REQUIRED, now: NOW });
  assert.ok(find(slot, "consent-confirm") && ready === 0, "one confirm step, the take flow waits");
  assert.match(find(slot, "consent-confirm-age").textContent, /18 or older/);
  assert.equal(find(slot, "consent-confirm-points").children.length, CONSENT_TEXT.items.length, "the points are shown");
  find(slot, "consent-confirm-yes").click();
  assert.equal(ready, 1);
  const doc = consentStore.loadAnswers(undefined);
  assert.equal(doc.account, "user-d");
  assert.equal(doc.items.meta, undefined, "the Meta tick stays dropped");
  assert.equal(consentStore.consentFields().consent.account, "user-d");
  assert.ok(find(slot, "consent-done"));
  signedOutAnswer(); // a different person: answers again, and their answers count
  const other = slotEl();
  let again = 0;
  mountConsentGate(other, () => again++, { policy: REQUIRED, now: NOW });
  find(other, "consent-confirm-redo").click();
  assert.ok(find(other, "age-step") && again === 0, "asked from the start");
  assert.equal(consentStore.loadAnswers(undefined), null);
});

test("B2 confirmThen: a sign-in in the middle of a take asks once, then goes on; with no waiting answer it goes on at once", () => {
  store.clear();
  consentStore.forgetAccount(undefined);
  consentStore.setAccount("user-h", undefined);
  let went = 0;
  confirmThen(slotEl(), () => went++);
  assert.equal(went, 1);
  store.clear();
  consentStore.setAccount("", undefined);
  consentStore.saveAge("adult", undefined);
  consentStore.saveConsent({ analysis: true, biometric: true, processors: true, people_in_frame: true }, undefined);
  consentStore.setAccount("user-i", undefined);
  const slot = slotEl();
  confirmThen(slot, () => went++);
  assert.equal(went, 1, "waits");
  find(slot, "consent-confirm-yes").click();
  assert.equal(went, 2);
  assert.equal(consentStore.consentFields().consent.account, "user-i");
});

test("AC-CA16 a refused 13 to 17 answer survives an account change where the minimum is 18; at 13 it does not", () => {
  policy.setPolicy({ prod: true, switches: {}, consent: { required: true }, age: { minimum: 18, adult: 18 } });
  store.clear();
  consentStore.setAccount("user-e", undefined);
  consentStore.saveAge("minor", undefined);
  consentStore.setAccount("user-f", undefined);
  assert.equal(consentStore.loadAnswers(undefined).age_band, "minor", "kept: the screen stays closed");
  policy.resetPolicy();
  consentStore.setAccount("user-g", undefined);
  assert.equal(consentStore.loadAnswers(undefined), null, "where 13 to 17 is served the answer is asked again");
});

const ITEMS4 = { analysis: true, biometric: true, processors: true, people_in_frame: true };
const putDoc = (d) => globalThis.localStorage.setItem(consentStore.KEY, JSON.stringify(d));

test("blocker 1 a signed-out age-only or stale answer, legacy included, never skips the age question for the next person", () => {
  const cases = {
    "age only": () => { consentStore.setAccount("", undefined); consentStore.saveAge("adult", undefined); },
    "stale legacy": () => putDoc({ age_band: "adult", version: "2026-01-01", items: ITEMS4, at: "2026-01-01T00:00:00Z" }),
  };
  for (const [name, make] of Object.entries(cases)) {
    store.clear();
    consentStore.forgetAccount(undefined);
    make();
    consentStore.setAccount("user-y", undefined);
    const slot = slotEl();
    mountConsentGate(slot, () => {}, { policy: REQUIRED, now: NOW, minimum: 18 });
    assert.ok(find(slot, "age-step"), `${name}: Y is asked the age`);
    assert.equal(find(slot, "consent-step"), null, `${name}: not just the points`);
    assert.deepEqual(consentStore.consentFields(), {}, `${name}: nothing of X's goes with Y's job`);
  }
});

test("blocker 2 ensureConsent waits for api/auth/me, then asks once; nothing runs while it is pending", async () => {
  store.clear();
  consentStore.forgetAccount(undefined);
  consentStore.setAccount("", undefined);
  consentStore.saveAge("adult", undefined);
  consentStore.saveConsent(ITEMS4, undefined);
  let release;
  const refresh = () => new Promise((r) => { release = r; }).then(() => consentStore.setAccount("user-z", undefined));
  const slot = slotEl();
  let went = 0;
  gate.ensureConsent(slot, () => went++, { policy: REQUIRED, refresh });
  assert.equal(went, 0, "pending: nothing goes on");
  assert.equal(find(slot, "consent-confirm"), null);
  release();
  await new Promise((r) => setTimeout(r, 0));
  assert.ok(find(slot, "consent-confirm"), "the confirm shows once the account is known");
  assert.equal(went, 0);
  find(slot, "consent-confirm-yes").click();
  assert.equal(went, 1);
});

test("blocker 3 a sign-in in another tab after the gate passed: send asks again instead of posting an empty answer", async () => {
  store.clear();
  consentStore.forgetAccount(undefined);
  consentStore.setAccount("", undefined);
  consentStore.saveAge("adult", undefined);
  consentStore.saveConsent(ITEMS4, undefined);
  const slot = slotEl();
  let went = 0;
  gate.ensureConsent(slot, () => went++, { policy: REQUIRED, refresh: async () => consentStore.setAccount("user-w", undefined) });
  await new Promise((r) => setTimeout(r, 0));
  assert.ok(find(slot, "consent-confirm") && went === 0, "confirm, not a 400");
  store.clear(); // the other tab was a different account altogether: this account has no answer
  consentStore.forgetAccount(undefined);
  consentStore.setAccount("", undefined);
  const again = slotEl();
  gate.ensureConsent(again, () => went++, { policy: REQUIRED, now: NOW, refresh: async () => consentStore.setAccount("user-v", undefined) });
  await new Promise((r) => setTimeout(r, 0));
  assert.ok(find(again, "age-step") && went === 0, "asked from the start");
  store.clear();
  consentStore.forgetAccount(undefined);
  consentStore.setAccount("user-u", undefined);
  consentStore.saveAge("adult", undefined);
  consentStore.saveConsent(ITEMS4, undefined);
  gate.ensureConsent(slotEl(), () => went++, { policy: REQUIRED, refresh: async () => consentStore.setAccount("user-u", undefined) });
  await new Promise((r) => setTimeout(r, 0));
  assert.equal(went, 1, "an answer of this account goes on at once");
  gate.ensureConsent(slotEl(), () => went++, { policy: { required: false } });
  assert.equal(went, 2, "outside a gated build it just goes on");
});

test("blocker 4 the confirm step says the Meta box was not carried over only when there was a tick", () => {
  const withTick = gate.confirmStep({ age_band: "adult", items: { ...ITEMS4, meta: true, meta_adults: true } }, { onConfirm() {}, onRedo() {} });
  const without = gate.confirmStep({ age_band: "adult", items: ITEMS4 }, { onConfirm() {}, onRedo() {} });
  assert.match(withTick.textContent, /Meta box is not carried over/);
  assert.doesNotMatch(without.textContent, /Meta box/);
});

globalThis.window ||= globalThis;
const { fetchMe } = await import("../../web/auth.js");
consentStore.setAccountLoader(null); // the DOM tests mount the gate by hand: no automatic api/auth/me
const pendingMod = await import("../../web/pending.js");
const reply = (status, body) => async () => ({ status, json: async () => body, headers: { get: () => null } });
const stampedFor = (id) => {
  store.clear();
  consentStore.forgetAccount(undefined);
  consentStore.setAccount(id, undefined);
  consentStore.saveAge("adult", undefined);
  consentStore.saveConsent(ITEMS4, undefined);
};

test("item 1 api/auth/me unreachable is unknown: nothing is dropped and the send goes to the saved path; a real signed-out answer still clears", async () => {
  policy.setPolicy({ switches: {}, consent: { required: true, version: CONSENT_VERSION, items: [] }, age: { minimum: 18, adult: 18 } });
  stampedFor("user-x");
  globalThis.fetch = async () => { throw new TypeError("offline"); };
  const info = await fetchMe();
  assert.equal(info.unreachable, true);
  assert.equal(consentStore.loadAnswers(undefined).account, "user-x", "kept");
  let went = 0;
  let offline = 0;
  const slot = slotEl();
  gate.ensureConsent(slot, () => went++, { refresh: fetchMe, onUnreachable: () => offline++ });
  await new Promise((r) => setTimeout(r, 5));
  assert.deepEqual([went, offline, find(slot, "age-step")], [0, 1, null], "no age step, no send: the caller takes the offline path");
  globalThis.fetch = reply(500, {});
  assert.equal((await fetchMe()).unreachable, true, "a server fault is unknown too");
  assert.equal(consentStore.loadAnswers(undefined).account, "user-x");
  globalThis.fetch = reply(401, {});
  assert.equal((await fetchMe()).unreachable, undefined);
  assert.equal(consentStore.loadAnswers(undefined), null, "a real signed-out answer clears the stamped answer");
});

test("item 2 a check in progress shows a status, and a hung check ends as unreachable through the call timeout", async () => {
  stampedFor("user-x");
  let signal;
  globalThis.fetch = (url, init) => new Promise((_, reject) => { signal = init && init.signal; if (signal) signal.addEventListener("abort", () => reject(new Error("timeout"))); });
  const slot = slotEl();
  let offline = 0;
  gate.ensureConsent(slot, () => {}, { refresh: fetchMe, onUnreachable: () => offline++ });
  assert.ok(find(slot, "consent-checking"), "not a blank box");
  assert.ok(signal, "the call carries a timeout signal");
  assert.equal(offline, 0);
  const real = AbortSignal.timeout;
  signal.dispatchEvent(new Event("abort")); // the timer firing
  await new Promise((r) => setTimeout(r, 5));
  assert.equal(offline, 1, "the hung check ends as unreachable");
  assert.ok(real);
});

test("item 4 a take sent with no consent answer to send is marked for the person and sends nothing by itself", async () => {
  const calls = [];
  const api = { upload: async () => { calls.push("upload"); return { upload_id: "u" }; }, createPeopleJobFor: async () => ({ job: "p" }),
    getJob: async () => ({ status: "done", result: {} }), submitJob: async () => ({ job: "j" }), health: async () => ({}) };
  const db = new Map();
  const idb = { all: async () => [...db.values()], get: async (i) => db.get(i), put: async (r) => db.set(r.id, r), delete: async (i) => db.delete(i) };
  let needs = true;
  const p = pendingMod.createPending({ store: idb, api, buildRequest: () => ({}), lock: pendingMod.createLock({}), uuid: () => "t1", setTimer: () => 0,
    clearTimer: () => {}, needsAnswer: () => needs });
  const { record } = await p.begin({ source: "recording", blob: { size: 10, type: "video/webm" }, role: "follow", trim: { start_ms: 0, end_ms: 1 } });
  p.release(record);
  await p.tick({ source: "online" });
  let r = await p.get("t1");
  assert.deepEqual(calls, [], "no video went");
  assert.equal(r.last_error.kind, "held");
  assert.match(r.last_error.detail, /Agree to each point/);
  await p.tick({ source: "timer" });
  assert.deepEqual(calls, [], "and the held take is left alone until the person acts");
  needs = false; // the person answered
  await p.sendNow("t1");
  assert.deepEqual(calls, ["upload"], "Send now goes once the answer exists");
  r = await p.get("t1");
  assert.ok(r);
});

test("the pending page: Send now opens the consent step on the page when an answer is needed, and sends once it is given", async () => {
  const { sendNowButton } = await import("../../web/pending-ui.js");
  stampedFor("");
  consentStore.setAccount("", undefined);
  consentStore.saveAge("adult", undefined);
  consentStore.saveConsent(ITEMS4, undefined);
  consentStore.setAccount("user-q", undefined); // someone signed in since: the signed-out answer waits for them
  const sent = [];
  const box = slotEl();
  const button = sendNowButton({ sendNow: (id) => sent.push(id) }, "t9", box, { refresh: async () => {} });
  button.click();
  await new Promise((r) => setTimeout(r, 0));
  assert.deepEqual(sent, [], "nothing goes before the answer");
  assert.ok(find(box, "consent-confirm"), "the step is on the page, not a dead end");
  find(box, "consent-confirm-yes").click();
  assert.deepEqual(sent, ["t9"]);
  const plain = sendNowButton({ sendNow: (id) => sent.push(id) }, "t8", slotEl(), { refresh: async () => {} });
  plain.click();
  await new Promise((r) => setTimeout(r, 0));
  assert.deepEqual(sent, ["t9", "t8"], "with an answer of this account it sends at once");
});

test("residual 1 only a real signed-out answer drops the stored answer: 403, 429, a fault and a non-JSON 200 do not", async () => {
  const nonJson = async () => ({ status: 200, json: async () => { throw new SyntaxError("not json"); }, headers: { get: () => null } });
  for (const [name, f] of [["403", reply(403, {})], ["429", reply(429, {})], ["502", reply(502, {})], ["200 not JSON", nonJson]]) {
    stampedFor("user-x");
    globalThis.fetch = f;
    const info = await fetchMe();
    assert.equal(info.unreachable, true, name);
    assert.equal(consentStore.loadAnswers(undefined).account, "user-x", `${name}: the answer stays`);
  }
  stampedFor("user-x");
  globalThis.fetch = reply(200, { available: true, signed_in: false });
  await fetchMe();
  assert.equal(consentStore.loadAnswers(undefined), null, "a 200 that says nobody is signed in clears it");
  stampedFor("user-x");
  globalThis.fetch = reply(404, {});
  await fetchMe();
  assert.equal(consentStore.loadAnswers(undefined), null, "a 404 (sign-in off) clears it");
});

test("residual 2 the step box of a row is the same element across repaints", async () => {
  const { stepFor } = await import("../../web/pending-ui.js");
  const steps = new Map();
  const first = stepFor(steps, "t1");
  first.append(document.createElement("div"));
  assert.equal(stepFor(steps, "t1"), first);
  assert.equal(stepFor(steps, "t1").children.length, 1, "what the person is answering is still there");
  assert.notEqual(stepFor(steps, "t2"), first);
});

test("residual 4 no upload starts until api/auth/me has answered; the take is kept and tried again", async () => {
  const calls = [];
  const api = { upload: async () => { calls.push("upload"); return { upload_id: "u" }; }, createPeopleJobFor: async () => ({ job: "p" }),
    getJob: async () => ({ status: "done", result: {} }), submitJob: async () => ({ job: "j" }), health: async () => ({}) };
  const db = new Map();
  const idb = { all: async () => [...db.values()], get: async (i) => db.get(i), put: async (r) => db.set(r.id, r), delete: async (i) => db.delete(i) };
  let known = false;
  const p = pendingMod.createPending({ store: idb, api, buildRequest: () => ({}), lock: pendingMod.createLock({}), uuid: () => "t1", setTimer: () => 0,
    clearTimer: () => {}, ensureAccount: async () => known });
  const { record } = await p.begin({ source: "recording", blob: { size: 10, type: "video/webm" }, role: "follow", trim: { start_ms: 0, end_ms: 1 } });
  p.release(record);
  await p.tick({ source: "online" });
  assert.deepEqual(calls, [], "no byte goes while who is signed in is unknown");
  const r = await p.get("t1");
  assert.ok(r, "the saved take is kept");
  assert.notEqual(r.last_error && r.last_error.kind, "held", "and not parked as held: it is retried");
  known = true;
  await p.tick({ source: "online", force: true });
  assert.deepEqual(calls, ["upload"], "once the check has an answer the upload goes");
});
