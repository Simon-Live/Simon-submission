// The consent and age step before the first capture or upload (docs/specs/consent-and-age.md; LEG-C4, LEG-H1).
// When the server requires it (api/policy, web/policy.js) the camera and the file picker are mounted only after a
// neutral age question and one tick box per point. Below the server's minimum age the screen stays closed. Outside a gated build the short
// consent line and its data note show as before (consent.js) and the take flow mounts at once.
import { h } from "./ui.js";
import { consentBlock } from "./consent.js";
import { ageMinimum, consentPolicy, phrasingLive } from "./policy.js";
import { AGE_TEXT, CONFIRM_TEXT, CONSENT_TEXT, MONTHS } from "./model/consent-text.js";
import { ageBand, bandRefused, confirmAnswers, consentFields, consentValid, dropAnswers, loadAnswers, needsConfirm, saveAge, saveConsent, whenAccountKnown } from "./model/consent-store.js";
import { formatUtc } from "./build.js";

const YEARS_SHOWN = 100;

/** The age question: a month and a year, no hint of any limit. Calls `done(band)`. */
export function ageStep(done, now = new Date()) {
  const t = AGE_TEXT;
  const month = h("select", { id: "consent-month", class: "input", "data-testid": "age-month" },
    h("option", { value: "", text: t.month }), ...MONTHS.map((m, i) => h("option", { value: String(i + 1), text: m })));
  const thisYear = now.getUTCFullYear();
  const year = h("select", { id: "consent-year", class: "input", "data-testid": "age-year" },
    h("option", { value: "", text: t.year }),
    ...Array.from({ length: YEARS_SHOWN }, (_, i) => h("option", { value: String(thisYear - i), text: String(thisYear - i) })));
  const error = h("p", { class: "error", role: "alert", "data-testid": "age-error", hidden: true });
  const next = h("button", { type: "button", class: "btn", "data-testid": "age-next", text: t.next, onclick: () => {
    const m = Number(month.value), y = Number(year.value);
    if (!m || !y) { error.textContent = t.missing; error.hidden = false; return; }
    done(ageBand(y, m, now));
  } });
  return h("fieldset", { class: "consent-age", "data-testid": "age-step" },
    h("legend", { text: t.question }),
    h("div", { class: "consent-age-row" },
      h("label", { for: "consent-month", text: t.month }), month,
      h("label", { for: "consent-year", text: t.year }), year),
    h("p", { class: "hint", text: t.why }), error, next);
}

/** N3: the first box still unticked, scrolled clear of the sticky header (`.consent-item` scroll-margin-top) and
 * focused without a second scroll, so it is never hidden under the header (WCAG 2.4.11). */
function showFirst(box) {
  if (typeof box.row.scrollIntoView === "function") box.row.scrollIntoView({ block: "nearest", inline: "nearest" });
  if (typeof box.input.focus === "function") box.input.focus({ preventScroll: true });
}

/** The consent points, each its own unticked box, with what is taken and where it goes. Calls `done(items)`. */
export function consentStep(done, metaOn = Boolean(consentPolicy().meta_item)) {
  const t = CONSENT_TEXT;
  const metaInput = metaOn ? h("input", { type: "checkbox", id: "consent-meta", "data-testid": "consent-item-meta" }) : null;
  const adultsInput = metaOn ? h("input", { type: "checkbox", id: "consent-meta-adults", "data-testid": "consent-item-meta-adults" }) : null;
  const boxes = t.items.map((item) => {
    const id = `consent-${item.key}`;
    const input = h("input", { type: "checkbox", id, "data-testid": `consent-item-${item.key}` });
    return { item, input, row: h("div", { class: "consent-item" }, input, h("label", { for: id, text: item.label })) };
  });
  const error = h("p", { class: "error", role: "alert", "data-testid": "consent-error", hidden: true });
  const agree = h("button", { type: "button", class: "btn", "data-testid": "consent-agree", text: t.agree, onclick: () => {
    const items = Object.fromEntries(boxes.map((b) => [b.item.key, b.input.checked === true]));
    const open = boxes.find((b) => b.input.checked !== true);
    if (open) { error.textContent = t.missing; error.hidden = false; return showFirst(open); }
    if (metaInput && metaInput.checked === true) {
      if (adultsInput.checked !== true) { error.textContent = t.metaItem.adultsMissing; error.hidden = false; return adultsInput.focus?.({ preventScroll: true }); }
      return done({ ...items, meta: true, meta_adults: true });
    }
    done(items);
  } });
  const list = (title, lines, testid) => h("section", { "data-testid": testid },
    h("h3", { text: title }), h("ul", {}, ...lines.map((line) => h("li", { text: line }))));
  return h("fieldset", { class: "consent-step", "data-testid": "consent-step" },
    h("legend", { text: t.title }),
    h("p", { class: "hint", text: t.lede }),
    list(t.extractedTitle, t.extracted, "consent-extracted"),
    list(t.goesTitle, [...t.goes, phrasingLive() ? t.phrasingLive : t.phrasingTemplate], "consent-goes"),
    ...boxes.map((b) => b.row),
    metaOn ? list(t.metaTitle, t.metaGoes, "consent-meta-goes") : null,
    metaOn ? h("div", { class: "consent-item" }, metaInput, h("label", { for: "consent-meta", text: t.metaItem.label })) : null,
    metaOn ? h("div", { class: "consent-item" }, adultsInput, h("label", { for: "consent-meta-adults", text: t.metaItem.adults.label })) : null,
    h("p", { class: "hint", "data-testid": "consent-withdraw", text: t.withdraw }),
    h("p", { class: "consent-links", "data-testid": "consent-links" },
      ...t.policyLinks.flatMap((l, i) => [i ? " " : null, h("a", { href: l.href, target: "_blank", rel: "noopener", text: l.label })])),
    error, agree);
}

/** One confirm step for an answer given signed out: the age and the points shown, one tap to keep them and go on, or answer again. */
export function confirmStep(doc, { onConfirm, onRedo }) {
  const t = CONFIRM_TEXT;
  return h("fieldset", { class: "consent-step", "data-testid": "consent-confirm" },
    h("legend", { text: t.title }),
    h("p", { class: "hint", text: t.lede }),
    h("p", { "data-testid": "consent-confirm-age", text: `${t.ageLabel}: ${t.bands[doc.age_band] || ""}` }),
    h("section", {}, h("h3", { text: t.pointsTitle }),
      h("ul", { "data-testid": "consent-confirm-points" }, ...CONSENT_TEXT.items.map((i) => h("li", { text: i.label })))),
    doc.items && doc.items.meta ? h("p", { class: "hint", text: t.metaDropped }) : null,
    h("button", { type: "button", class: "btn", "data-testid": "consent-confirm-yes", text: t.confirm, onclick: onConfirm }),
    h("button", { type: "button", class: "btn secondary", "data-testid": "consent-confirm-redo", text: t.redo, onclick: onRedo }));
}

/**
 * After a sign-in in the middle of a take: when a signed-out answer is waiting, show the confirm step in `slot` and call `then()` once it is
 * confirmed (or answered again); otherwise call `then()` at once. The take stays where it is. `opts` are for tests.
 */
export function confirmThen(slot, then, opts = {}) {
  if (!needsConfirm(opts.storage)) return then();
  const doc = loadAnswers(opts.storage);
  slot.replaceChildren(confirmStep(doc, {
    onConfirm: () => { confirmAnswers(opts.storage); then(); },
    onRedo: () => { dropAnswers(opts.storage); mountConsentGate(slot, then, opts); },
  }));
}

/**
 * Before a take is sent, after a sign-in or when the page may be stale (another tab signed in): ask api/auth/me (`opts.refresh`) and wait for
 * it, then confirm a waiting signed-out answer, ask again when this account has none, or call `then()` at once. Outside a gated build it just calls `then()`.
 */
export function ensureConsent(box, then, opts = {}) {
  if (!(opts.policy || consentPolicy()).required) return then();
  const go = (info) => {
    if (info && info.unreachable) return (opts.onUnreachable || then)(); // unknown account: nothing is dropped, nothing is decided here
    if (needsConfirm(opts.storage)) return confirmThen(box, then, opts);
    if (Object.keys(consentFields(opts.storage)).length === 0) { mountConsentGate(box, then, opts); return undefined; }
    return then();
  };
  if (!opts.refresh) return go();
  box.replaceChildren(h("p", { role: "status", "data-testid": "consent-checking", text: CONFIRM_TEXT.checking })); // never a blank box while it waits
  opts.refresh().then(go, () => go({ unreachable: true }));
  return undefined;
}

function agreedLine(doc, onReview) {
  const when = formatUtc(doc.at) || doc.at || "";
  return h("p", { class: "hint consent-done", "data-testid": "consent-done" }, CONSENT_TEXT.agreedOn(when), " ",
    h("button", { type: "button", class: "btn secondary", "data-testid": "consent-review", text: CONSENT_TEXT.review, onclick: onReview }));
}

/**
 * Mount the step into `slot`; `onReady()` runs once, when capture and upload may start. `policy` and `storage` are for tests.
 * Returns `{ready: boolean}` as it stands after mounting.
 */
export function mountConsentGate(slot, onReady, opts = {}) {
  let result = { ready: false };
  // The answers belong to the signed-in account: wait for api/auth/me, which drops another account's answers (consent-store setAccount).
  whenAccountKnown(() => { result = mountNow(slot, onReady, opts); });
  return result;
}

function mountNow(slot, onReady, { policy = consentPolicy(), storage, now, minimum = ageMinimum() } = {}) {
  let started = false;
  const ready = () => { if (!started) { started = true; onReady(); } };
  if (!policy.required) {
    slot.replaceChildren(consentBlock());
    ready();
    return { ready: true };
  }
  const blocked = () => slot.replaceChildren(h("p", { class: "consent-blocked", role: "alert", "data-testid": "age-blocked", text: AGE_TEXT.blocked }));
  const showConsent = () => slot.replaceChildren(consentStep((items) => {
    const doc = saveConsent(items, storage);
    slot.replaceChildren(agreedLine(doc, showConsent));
    ready();
  }, Boolean(policy.meta_item)));
  const showAge = () => slot.replaceChildren(h("div", {}, h("h2", { text: AGE_TEXT.title }), ageStep((band) => {
    saveAge(band, storage);
    if (bandRefused(band, minimum)) blocked(); else showConsent();
  }, now)));
  const doc = loadAnswers(storage);
  if (doc && bandRefused(doc.age_band, minimum)) { blocked(); return { ready: false }; }
  if (needsConfirm(storage)) {
    confirmThen(slot, () => { slot.replaceChildren(agreedLine(loadAnswers(storage), showConsent)); ready(); }, { policy, storage, now, minimum });
    return { ready: false };
  }
  if (consentValid(doc) && policy.version === doc.version) {
    slot.replaceChildren(agreedLine(doc, showConsent));
    ready();
    return { ready: true };
  }
  if (doc) showConsent(); else showAge();
  return { ready: false };
}
