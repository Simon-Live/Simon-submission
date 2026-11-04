// The go-live fix lane "a11y" (docs/specs/a11y-go-live.md; docs/prod-verify/a11y-copy.md B11, B13, R1 to R4, R6, R9;
// byok-ui.md D1, D3; reels 3.10). Runs the real modules on the shared fake DOM, with focus tracked on `document`.
//   node --test tests/part7/a11y-go-live.dom.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { installDom, El, find } from "./fake-dom.mjs";

installDom();
// What these modules touch beyond the shared fake DOM: style, dataset, classList, focus, media calls and the clock.
Object.defineProperty(El.prototype, "style", { get() { return (this._style ||= { setProperty() {} }); } });
Object.defineProperty(El.prototype, "dataset", { get() { return (this._data ||= {}); } });
Object.defineProperty(El.prototype, "classList", { get() { return (this._cl ||= { add() {}, remove() {}, toggle() {}, contains: () => false }); } });
Object.defineProperty(El.prototype, "tagName", { get() { return this.tag.toUpperCase(); } });
Object.assign(El.prototype, {
  focus() { globalThis.document.activeElement = this; }, pause() {}, load() {}, play() { return Promise.resolve(); },
  setPointerCapture() {}, getBoundingClientRect() { return { left: 0, right: 300, width: 300 }; }, clientWidth: 300, clientHeight: 40,
});
document.getElementById = () => null;
document.body = new El("body");
globalThis.window = { devicePixelRatio: 1 };
globalThis.requestAnimationFrame = () => 0;
globalThis.cancelAnimationFrame = () => {};
globalThis.location = { hash: "" };
globalThis.BroadcastChannel = undefined; // Node's own would keep the process alive once the failed job page loads pending-app.js
const settle = (ms = 30) => new Promise((r) => setTimeout(r, ms));
const key = (k) => Object.assign(new Event("keydown"), { key: k, preventDefault() {} });

let respond = () => ({ status: 200, body: {} });
const fetched = [];
globalThis.fetch = async (url, init = {}) => {
  fetched.push(String(url));
  const { status, body } = respond(String(url), init);
  return { ok: status >= 200 && status < 300, status, json: async () => body, headers: { get: () => null } };
};

const { h, focusOn } = await import("../../web/ui.js");

test("B11, R1: focusOn gives a non-control tabindex -1 and focus; a control keeps its own tab stop", () => {
  const p = h("p", { text: "Refused." });
  assert.equal(focusOn(p), p);
  assert.equal(p.getAttribute("tabindex"), "-1");
  assert.equal(document.activeElement, p);
  const b = h("button", { type: "button" });
  focusOn(b);
  assert.equal(b.getAttribute("tabindex"), null, "a button is not given tabindex");
  assert.equal(document.activeElement, b);
  assert.equal(focusOn(null), null, "nothing to focus is not an error");
});

test("R1: Delete my data moves focus with each step; Cancel and Escape give it back to the button", async () => {
  const { renderMe } = await import("../../web/views/me.js");
  const { TEXT } = await import("../../web/model/me.js");
  const host = new El("div");
  renderMe(host, { t: TEXT, email: "a@b.co", optedIn: false, consentLines: [], rows: [] },
    { signOut() {}, consent: async () => ({ ok: true }), claim: async () => ({ ok: true }), delete: async () => ({ ok: false, text: TEXT.deleteFailed }) });
  const ask = find(host, "me-delete");
  ask.click();
  assert.equal(document.activeElement, find(host, "me-delete-warn"), "the warning takes focus when the button hides");
  find(host, "me-delete-cancel").click();
  assert.equal(document.activeElement, ask);
  ask.click();
  find(host, "me-delete-sure").dispatchEvent(key("Escape"));
  assert.equal(document.activeElement, ask, "Escape cancels");
  assert.equal(find(host, "me-delete-sure").hidden, true);
  ask.click();
  find(host, "me-delete-confirm").click();
  await settle();
  assert.equal(document.activeElement, ask, "a failed delete returns focus to the button, beside its error");
  assert.equal(find(host, "me-delete-note").textContent, TEXT.deleteFailed);
});

test("R2 (WCAG 2.5.3): the catalog thumbnail is a pointer shortcut with no name to mismatch; the name link stays", async () => {
  const { card: drawCard } = await import("../../web/views/browse.js");
  const root = new El("div");
  const card = { id: "squat", name: "Squat", hasVideo: true, videoUrl: "v.mp4", duration: "0:10", watchHref: "#/watch/squat", followHref: "#/follow/squat", testId: "entry-squat", meta: "" };
  root.append(drawCard(card));
  const thumb = find(root, "entry-squat");
  assert.ok(thumb, "the thumbnail is drawn");
  assert.equal(thumb.getAttribute("aria-label"), null);
  assert.equal(thumb.getAttribute("tabindex"), "-1");
  assert.equal(thumb.getAttribute("aria-hidden"), "true");
  const names = root.querySelectorAll('[href="#/watch/squat"]').filter((a) => a.getAttribute("aria-hidden") !== "true");
  assert.equal(names.length, 1, "one named link to the movement remains in the tab order");
  assert.equal(names[0].textContent, "Squat");
});

test("AC-G19 (WCAG 2.5.3): a second-opinion row is named by its visible text; the tap hint is a description", async () => {
  const { observationsPanel, SO_HINT_ID } = await import("../../web/views/second-opinion.js");
  const root = new El("div");
  root.append(...observationsPanel("Model", [{ at_s: 3, text: "Knees in" }], () => {}));
  const row = find(root, "second-opinion-0");
  assert.equal(row.getAttribute("aria-label"), null, "no label that hides the visible words");
  assert.equal(row.getAttribute("aria-describedby"), SO_HINT_ID);
  assert.match(row.textContent, /^3\.0 s Knees in model's opinion$/);
  const hint = root.querySelector(`#${SO_HINT_ID}`) || root.children[1].children.find((c) => c.getAttribute("id") === SO_HINT_ID);
  assert.equal(hint.getAttribute("hidden"), "");
  assert.equal(hint.textContent, "Moves the video to this moment.");
});

test("R3: trim handles are sliders with their value in seconds; Home and End reach the clip's ends", async () => {
  const { openTrimEditor } = await import("../../web/trim.js");
  const root = new El("div");
  openTrimEditor(root, { blob: new Blob(["x"]), source: "upload" });
  const video = root.querySelectorAll("[class]").find((n) => n.tag === "video");
  video.duration = 12;
  video.dispatchEvent(new Event("durationchange"));
  await settle();
  const start = find(root, "trim-start");
  const end = find(root, "trim-end");
  for (const el of [start, end]) {
    assert.equal(el.tag, "div");
    assert.equal(el.getAttribute("role"), "slider");
    assert.equal(el.getAttribute("tabindex"), "0");
    assert.equal(el.getAttribute("aria-valuemin"), "0");
    assert.equal(el.getAttribute("aria-valuemax"), "12.0");
    assert.equal(el.getAttribute("aria-describedby"), "trim-keys");
  }
  assert.equal(start.getAttribute("aria-label"), "Start of the movement");
  assert.equal(end.getAttribute("aria-valuenow"), "12.0");
  start.dispatchEvent(key("PageUp"));
  assert.equal(start.getAttribute("aria-valuenow"), "1.0");
  assert.equal(start.getAttribute("aria-valuetext"), "1.0 s");
  start.dispatchEvent(key("Home"));
  assert.equal(start.getAttribute("aria-valuenow"), "0.0");
  end.dispatchEvent(key("PageDown"));
  end.dispatchEvent(key("End"));
  assert.equal(end.getAttribute("aria-valuenow"), "12.0");
  start.dispatchEvent(key("a"));
  assert.equal(start.getAttribute("aria-valuenow"), "0.0", "other keys do nothing");
});

test("R4: a refused Save links its error to both fields and marks them invalid; a good Save clears it", async () => {
  const { mountModalCreds } = await import("../../web/modal-creds.js");
  const refusal = "Those do not look like Modal tokens. Copy the ID and the secret again.";
  respond = (url, init) => (init.method === "PUT"
    ? { status: 400, body: { message: refusal } } : { status: 200, body: { set: false, token_id_hint: null, check: null } });
  const slot = new El("div");
  mountModalCreds(slot, { wait: () => Promise.resolve() });
  await settle();
  find(slot, "modal-save").click();
  await settle();
  const error = find(slot, "modal-token-error");
  assert.equal(error.hidden, false);
  assert.equal(error.textContent, refusal);
  assert.equal(error.getAttribute("id"), "modal-token-error");
  for (const id of ["modal-token-id", "modal-token-secret"]) {
    assert.equal(find(slot, id).getAttribute("aria-invalid"), "true", id);
    assert.equal(find(slot, id).getAttribute("aria-describedby"), "modal-token-error", id);
  }
  assert.equal(find(slot, "modal-note").textContent, "", "the status line does not repeat it");
  respond = (url, init) => (init.method === "PUT"
    ? { status: 200, body: { set: true, token_id_hint: "ak-…AB12", check: null } } : { status: 200, body: { set: false } });
  find(slot, "modal-save").click();
  await settle();
  assert.equal(error.hidden, true);
  assert.equal(find(slot, "modal-token-id").getAttribute("aria-invalid"), null);
  assert.equal(find(slot, "modal-token-id").getAttribute("aria-describedby"), null);
});

test("compute contract: key_unavailable shows the server-fault line, never 'No token is set'", async () => {
  const { mountModalCreds, TEXT } = await import("../../web/modal-creds.js");
  respond = () => ({ status: 200, body: { set: true, token_id_hint: "ak-…AB12", check: null, key_unavailable: true } });
  const slot = new El("div");
  mountModalCreds(slot, { wait: () => Promise.resolve() });
  await settle();
  assert.equal(find(slot, "modal-status").textContent, TEXT.keyDown);
  assert.match(TEXT.keyDown, /fault on the server, not your token/);
  respond = () => ({ status: 200, body: { set: false, token_id_hint: null, check: null, key_unavailable: false } });
  const other = new El("div");
  mountModalCreds(other, { wait: () => Promise.resolve() });
  await settle();
  assert.equal(find(other, "modal-status").textContent, TEXT.notSet, "negative: false keeps the usual line");
});

test("R6: a 429 says the server's own reason and retries soon; no line says tomorrow", async () => {
  const { messageFor } = await import("../../web/api.js");
  const { classifyFailure, failureText, TEXT } = await import("../../web/pending.js");
  const said = "Too many tries. Wait a little, then try again.";
  assert.equal(messageFor(429, { error: said }), said);
  assert.doesNotMatch(messageFor(429, null), /tomorrow|today/);
  const sorted = classifyFailure({ status: 429, detail: said });
  assert.deepEqual(sorted, { kind: "auto", status: 429 });
  assert.equal(failureText(sorted.kind, sorted.status), TEXT.busy);
});

test("R9: the result slider names read as English", async () => {
  const { TEXT: words } = await import("../../web/model/result-stage.js");
  assert.equal(words.progress("you"), "Position in your video");
  assert.equal(words.progress("reference"), "Position in the reference video");
});

test("B13: the countdown gives Cancel focus as Record hides", async () => {
  const { runCountdown } = await import("../../web/countdown.js");
  const stage = new El("div");
  const c = runCountdown(stage, 3, { tickMs: 1e6 });
  assert.equal(document.activeElement, find(stage, "countdown-cancel"));
  c.cancel();
  assert.equal(await c.done, false);
});

/** Focus options and scrollIntoView calls of the elements focused and scrolled while `fn` runs. */
function scrolling(fn) {
  const seen = { focus: [], scroll: [] };
  const focus = El.prototype.focus;
  El.prototype.focus = function (opts) { seen.focus.push([this, opts]); focus.call(this); };
  El.prototype.scrollIntoView = function (opts) { seen.scroll.push([this, opts]); };
  try { fn(); } finally { El.prototype.focus = focus; delete El.prototype.scrollIntoView; }
  return seen;
}

test("N7: Cancel takes focus without scrolling, and the countdown digit is centred clear of the sticky header", async () => {
  const { runCountdown } = await import("../../web/countdown.js");
  const stage = new El("div");
  let c;
  const seen = scrolling(() => { c = runCountdown(stage, 3, { tickMs: 1e6 }); });
  const [cancel, digit] = [find(stage, "countdown-cancel"), find(stage, "countdown")];
  assert.deepEqual(seen.focus, [[cancel, { preventScroll: true }]], "focus alone scrolled the digit under the header");
  assert.deepEqual(seen.scroll, [[digit, { block: "center", inline: "nearest" }]]);
  assert.notDeepEqual(seen.scroll.map(([el]) => el), [cancel], "the button, not the digit, was scrolled to");
  c.cancel();
  await c.done;
});

test("N3: Agree with a box unticked scrolls the first unticked box below the header and focuses it", async () => {
  const { consentStep } = await import("../../web/consent-gate.js");
  const { CONSENT_TEXT } = await import("../../web/model/consent-text.js");
  let agreed = 0;
  const step = consentStep(() => agreed++);
  const [first, second] = CONSENT_TEXT.items.map((i) => find(step, `consent-item-${i.key}`));
  first.checked = true;
  const seen = scrolling(() => find(step, "consent-agree").click());
  assert.equal(agreed, 0);
  assert.equal(find(step, "consent-error").hidden, false);
  assert.deepEqual(seen.scroll, [[second.parent, { block: "nearest", inline: "nearest" }]], "its row, under scroll-margin-top");
  assert.deepEqual(seen.focus, [[second, { preventScroll: true }]]);
  assert.equal(document.activeElement, second);
  for (const i of CONSENT_TEXT.items) find(step, `consent-item-${i.key}`).checked = true;
  const after = scrolling(() => find(step, "consent-agree").click());
  assert.equal(agreed, 1);
  assert.deepEqual(after.scroll, [], "nothing scrolls once every box is ticked");
});

test("D1: a failed job shows its reason; a Modal token refusal links to the Me page and the line says Stopped", async () => {
  const { failedText, needsMe, sentence } = await import("../../web/model/job-reason.js");
  const refused = "Modal did not accept your token. Make a new one in your Modal settings, add it on the Me page, then try again";
  assert.equal(failedText({ reason: refused, note: null }, "x"), `${refused}.`);
  assert.equal(failedText({ reason: "the GPU is busy, try again later" }, "x"), "The GPU is busy, try again later.");
  assert.equal(failedText({ note: "Stopped by the operator." }, "x"), "Stopped by the operator.");
  assert.equal(failedText({}, "The fallback."), "The fallback.");
  assert.equal(sentence("  "), "");
  assert.ok(needsMe(refused) && !needsMe("The GPU is busy."));

  const { mountJob } = await import("../../web/job.js");
  respond = (url) => (url.includes("api/jobs/")
    ? { status: 200, body: { id: "abcdefabcdef", kind: "follow", entry_id: "squat", status: "failed", stage: "pose", stages: [], note: null, reason: refused } }
    : { status: 200, body: {} });
  const root = new El("div");
  const stop = mountJob(root, "abcdefabcdef");
  await settle();
  stop();
  assert.equal(find(root, "job-note").textContent, `${refused}.`);
  const me = find(root, "open-me");
  assert.ok(me, "the Me page link is shown");
  assert.equal(me.getAttribute("href"), "#/me");
  assert.match(me.className, /primary/);
  assert.match(find(root, "retry").className, /secondary/);
  assert.equal(find(root, "progress-text").textContent, "Stopped");

  respond = (url) => (url.includes("api/jobs/")
    ? { status: 200, body: { id: "abcdefabcdef", kind: "follow", entry_id: "squat", status: "failed", stage: "pose", stages: [], note: null, reason: "the 3D step is not available" } }
    : { status: 200, body: {} });
  const other = new El("div");
  const stop2 = mountJob(other, "abcdefabcdef");
  await settle();
  stop2();
  assert.equal(find(other, "job-note").textContent, "The 3D step is not available.");
  assert.equal(find(other, "open-me"), null, "negative: no Me link for a failure the Me page cannot fix");
});

test("D1: the people picker shows the refusal, links to the Me page and gives the reason focus", async () => {
  const { openPeoplePicker } = await import("../../web/people.js");
  const refused = "This server runs takes on your own Modal account. Add your Modal token on the Me page, then try again.";
  respond = (url) => (url.includes("api/jobs/") ? { status: 200, body: { id: "p1", status: "failed", note: null, reason: refused } } : { status: 200, body: {} });
  const root = new El("div");
  openPeoplePicker(root, { peopleJob: "p1", pollMs: 5 });
  await settle(60);
  const err = find(root, "people-error");
  assert.equal(err.textContent, refused);
  assert.notEqual(find(root, "people-open-me").hidden, true);
  assert.equal(document.activeElement, err);
  assert.doesNotMatch(err.textContent, /Record again/);
});

test("D3: in prod the model preview asks nothing of api/fixture-result", async () => {
  const { loadMotion } = await import("../../web/model-preview.js");
  fetched.length = 0;
  const motion = await loadMotion({ prod: () => true });
  assert.equal(motion.source, "rest", "TICKET-389: the figure is posed at rest, not hidden");
  assert.deepEqual(fetched, [], "no request at all");
});

test("reels 3.10: both Ask views read the crisis answer as its own kind and show its fixed words", async () => {
  const { answerView } = await import("../../web/model/ask.js");
  const { takeAnswerView } = await import("../../web/model/take-ask.js");
  const body = { status: "crisis", text: null, message: "Fixed words. [OPERATOR: crisis line per country]", usage: null };
  for (const view of [answerView(body), takeAnswerView(body)]) {
    assert.equal(view.kind, "crisis");
    assert.equal(view.message, body.message);
    assert.equal(view.receipt, "", "no receipt: nothing was sent to a model");
  }
});
