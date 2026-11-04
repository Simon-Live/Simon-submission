// The server's prod policy (GET api/policy, part7/policy_routes.py; #415): which switches are on, whether the consent and
// age step is required, and its version. app.js loads it once before the first screen. The server enforces every
// switch on its own; the web only hides what the server would refuse.
//
// Before `loadPolicy` runs (unit tests that never load it) every switch reads as on and consent as not required, which
// is today's behaviour outside prod. A failed load in the app is fail-closed: every switch off and consent required.
export const SWITCHES = ["face_copy", "rehab", "trainer_public", "prize_boards", "byok_ranked", "mms_tts", "muse"];
const CLOSED = Object.freeze({
  prod: true, switches: Object.fromEntries(SWITCHES.map((k) => [k, false])), phrasing_live: false,
  consent: { required: true, version: null, items: [], header: "X-Simon-Consent" }, age: { minimum: 18, adult: 18 },
});

let current = null;

/** Keep `doc` as the policy (a malformed doc counts as a failed load). Returns what was kept. */
export function setPolicy(doc) {
  const ok = doc && typeof doc === "object" && doc.switches && typeof doc.switches === "object" && doc.consent;
  current = ok ? doc : CLOSED;
  return current;
}

/** Forget the loaded policy (tests). */
export function resetPolicy() { current = null; }

/** GET api/policy once; never rejects. `fetcher(url)` resolves to the parsed body. */
export async function loadPolicy(fetcher) {
  const get = fetcher || (async (url) => {
    const r = await fetch(url, { credentials: "same-origin", cache: "no-store" });
    if (!r.ok) throw new Error(`api/policy answered ${r.status}`);
    return r.json();
  });
  try { return setPolicy(await get("api/policy")); } catch { return setPolicy(null); }
}

/** True when the switch is on. Unknown names are off. */
export function policyOn(name) {
  if (!SWITCHES.includes(name)) return false;
  if (current === null) return true;
  return current.switches[name] === true;
}

/** `{required, version, items, header}` of the consent step. */
export function consentPolicy() {
  return current === null ? { required: false, version: null, items: [], header: "X-Simon-Consent" } : current.consent;
}

/** The youngest age the server serves (api/policy `age.minimum`). Before a load: 13, as outside prod. */
export const ageMinimum = () => (current !== null && current.age && Number(current.age.minimum)) || 13;

/** True when the server runs in prod (a failed load counts as prod: fail closed). Before a load: false. */
export const isProd = () => current !== null && current.prod === true;

/** True when fault wording may come from a hosted model (labelled as AI); false means template wording only. */
export const phrasingLive = () => current === null || current.phrasing_live === true;

/** False when the server cannot check a picture for a person (prod): the web then asks who it shows with the first send,
 * so the person answers once. A missing field or an unloaded policy counts as a server that checks. */
export const personCheckOff = () => current !== null && current.person_check === false;
