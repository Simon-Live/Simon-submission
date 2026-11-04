// The consent and age answers kept in this browser (docs/specs/consent-and-age.md). Pure apart from `storage`
// (localStorage by default). The server keeps the same record with each take (part7/consent_record.py).
import { CONSENT_VERSION, allTicked, consentRecord } from "./consent-text.js";
import { ageMinimum, consentPolicy } from "../policy.js";

export const KEY = "simon.consent";
export const HEADER = "X-Simon-Consent";
export const MIN_AGE = 13;
export const ADULT_AGE = 18;

const store = (storage) => storage || globalThis.localStorage;

// The Meta tick belongs to the signed-in account (a shared browser must not carry it to the next person). `account` is the
// user id from api/auth/me ("" signed out) and null until that answer is in. The server checks the same stamp (consent_record.parse).
let account = null;

/** Drop the whole stored answer (age, points and tick): the next person is asked again. An age answer this build refuses (under 13,
 * and 13 to 17 where the minimum is 18) stays, so a child cannot clear the closed screen by changing account (AC-CA16; the
 * server keeps the same mark on the account). */
export function dropAnswers(storage) {
  const doc = loadAnswers(storage);
  if (!doc || bandRefused(doc.age_band, ageMinimum())) return;
  try { store(storage).removeItem(KEY); } catch { /* blocked storage: nothing was kept */ }
}

let pending = false; // a api/auth/me answer is on its way: the gate waits for it, so it never reads another account's answer
let waiting = [];

/** Called when api/auth/me is asked. */
export function beginAccountCheck() { pending = true; }

let loader = null;

/** The app registers the function that asks api/auth/me (web/auth.js fetchMe); unit tests register none. */
export function setAccountLoader(fn) { loader = fn; }

/** Runs `fn` at once when the account is known, else when api/auth/me answers (asked here if nobody has yet). */
export function whenAccountKnown(fn) {
  if (account === null && !pending && loader) loader().catch(() => {}); // fetchMe sets `pending` before it awaits
  if (pending) waiting.push(fn); else fn();
}

/** True when a complete answer given signed out is on this browser and someone has signed in since: it may be another person's, so
 * nothing is sent or stamped until they confirm it (`confirmAnswers`) or answer again. */
export function needsConfirm(storage) {
  const doc = loadAnswers(storage);
  return Boolean(account && doc && !doc.account && consentValid(doc));
}

/** The person who signed in confirms the signed-out answer as theirs: it is stamped for the account, without the Meta tick (a
 * signed-out tick was never an account's). Returns the stamped doc, or null when there is nothing to confirm. */
export function confirmAnswers(storage) {
  const doc = loadAnswers(storage);
  if (!needsConfirm(storage)) return null;
  const { meta, meta_adults: adults, ...rest } = doc.items; // eslint-disable-line no-unused-vars
  return save({ ...doc, items: rest, account }, storage);
}

/** Tell the store who is signed in ("" for nobody). An answer made under another account is dropped, so the person is asked again. */
export function setAccount(id, storage) {
  account = typeof id === "string" ? id : "";
  const doc = loadAnswers(storage);
  // Only a complete, current signed-out answer is kept for the person who signs in to confirm (needsConfirm). An age-only or stale
  // one, a legacy one included, and another account's answer are dropped: the age is asked again, so a minor never inherits "adult".
  if (doc && (doc.account || "") !== account && !(!doc.account && account && consentValid(doc))) dropAnswers(storage);
  pending = false;
  const run = waiting;
  waiting = [];
  run.forEach((fn) => fn());
  return account;
}

/** api/auth/me could not be reached (offline, a fault, a timeout): who is signed in is unknown, so nothing is dropped and nothing is
 * decided. Waiting callers go on. */
export function accountUnknown() {
  pending = false;
  const run = waiting;
  waiting = [];
  run.forEach((fn) => fn());
}

/** True once api/auth/me has told who is signed in (or that nobody is). */
export const accountKnown = () => account !== null;

/** True when the server needs a consent answer and this browser holds none that may be sent (waiting for a confirm, or none). */
export const answerNeeded = (storage) => consentPolicy().required === true && Object.keys(consentFields(storage)).length === 0;

/** Sign-out and Delete my data: forget the answers and who they were for. */
export function forgetAccount(storage) { account = null; pending = false; dropAnswers(storage); }

/** "under13", "minor" or "adult" for a birth `year` and `month` (1 to 12), counted to the month at `now`. The day is
 * not asked, so the birthday month counts as not yet reached (the younger answer protects a child). Same rule as
 * part7/consent_record.py `age_band`. */
export function ageBand(year, month, now = new Date()) {
  const years = now.getUTCFullYear() - year - (now.getUTCMonth() + 1 <= month ? 1 : 0);
  return years < MIN_AGE ? "under13" : years < ADULT_AGE ? "minor" : "adult";
}

/** The stored doc `{age_band, version?, items?, at?}`, or null when unset, blocked or junk. */
export function loadAnswers(storage) {
  try {
    const doc = JSON.parse(store(storage).getItem(KEY) || "null");
    return doc && typeof doc === "object" && ["adult", "minor", "under13"].includes(doc.age_band) ? doc : null;
  } catch { return null; }
}

function save(doc, storage) {
  try { store(storage).setItem(KEY, JSON.stringify(doc)); } catch { /* blocked storage: asked again next time */ }
  return doc;
}

/** Keep the age answer. Under 13 is kept too, so the screen stays closed in this browser. */
export const saveAge = (band, storage) => save({ age_band: band, account: account || "" }, storage); // stamped like the consent answer: an account change drops it

/** Keep a complete consent answer for the stored age band; returns the record. */
export function saveConsent(items, storage, at = new Date().toISOString().replace(/\.\d{3}Z$/, "Z")) {
  const prior = loadAnswers(storage);
  return save(consentRecord(items, prior ? prior.age_band : null, at, account || ""), storage);
}

/** True when the stored answer is current: the version matches, every point is ticked and the band is 13 or over. */
export function consentValid(doc) {
  return Boolean(doc && doc.version === CONSENT_VERSION && allTicked(doc.items) && (doc.age_band === "adult" || doc.age_band === "minor"));
}

/** True when the server refuses this band: under 13 always, 13 to 17 where `minimum` is the adult age (prod at launch). */
export const bandRefused = (band, minimum = MIN_AGE) => band === "under13" || (band === "minor" && minimum >= ADULT_AGE);

export const isBlocked = (doc) => Boolean(doc && doc.age_band === "under13");
export const isMinor = (doc) => Boolean(doc && doc.age_band === "minor");

/** The job-request fields `{consent: {version, items, at}, age_band}`, or `{}` without a current answer. */
export function consentFields(storage) {
  const doc = loadAnswers(storage);
  if (!consentValid(doc) || !sendable(doc)) return {};
  const tickIsHis = account !== null && (doc.account || "") === account; // belt: an unknown account sends no Meta tick
  const { meta, meta_adults: adults, ...rest } = doc.items; // eslint-disable-line no-unused-vars
  return { consent: { version: doc.version, items: tickIsHis ? doc.items : rest, at: doc.at, account: doc.account || "" }, age_band: doc.age_band };
}

/** The answer may go with a request: the account is not yet known, or it is this account's own (not a signed-out answer awaiting confirmation). */
const sendable = (doc) => account === null || (doc.account || "") === account;

/** The upload header naming the consent version, or `{}` without a current answer. */
export function consentHeader(storage) {
  const doc = loadAnswers(storage);
  return consentValid(doc) && sendable(doc) ? { [HEADER]: CONSENT_VERSION } : {};
}
