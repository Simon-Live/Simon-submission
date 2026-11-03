// Glue between the account's default model for "You" and the model picker (docs/specs/model-default.md). The picker
// (web/skin/picker.js) remembers a choice per role in localStorage. For "You" a pick on a result is kept for that take
// on this device (`simon.model.you.<job>`) and never written as a default; a take with no pick opens on the account
// default when signed in, else the device default `simon.model.you`. Defaults are set on the Me page only.
import { call } from "./me-api.js";
import { meInfo } from "./model/auth.js";
import { PROFILE_URL, TEXT, YOU_KEY, preferredChoice } from "./model/model-default.js";
import { renderDefaultHint } from "./views/my-model.js";

const QUIET = { expectStatus: [401, 404] }; // signed out, or sign-in off: normal answers, not anomalies
const SIGNED_OUT = { signedIn: false, serverDefault: null };
let lastServer = null; // the answer the last picker read, so the hint under it asks nothing more

/**
 * The account's saved default: { signedIn, serverDefault }. Signed out, sign-in off or a failed call: not signed in.
 * Sign-in is asked first (`api/auth/me`, as fetchMe does) unless the caller already knows (`knownSignedIn`, the Me
 * page). Signed out, the profile is never requested, so no 401 reaches the console (the same rule as saved-mode.js).
 */
export async function loadServerDefault(callImpl = call, { knownSignedIn = false } = {}) {
  try {
    if (!knownSignedIn) { // the Me page already knows; anyone else asks
      const me = await callImpl("GET", "api/auth/me", undefined, QUIET);
      if (!meInfo(me && me.ok ? me.body : null).signedIn) return SIGNED_OUT;
    }
    const out = await callImpl("GET", PROFILE_URL, undefined, QUIET);
    if (!out.ok || !out.body || typeof out.body !== "object") return SIGNED_OUT;
    return { signedIn: true, serverDefault: out.body.default_model_id ?? null };
  } catch {
    return SIGNED_OUT;
  }
}

/**
 * A storage for the picker's `deps.storage` on the take `job`. Reading `simon.model.you` answers the pick kept for this
 * take (`simon.model.you.<job>`), else the default: the account's when signed in, else the device's. A pick for You is
 * written only under the take's key, signed in or out, so it survives a reload of that take and never becomes a
 * default (defaults are set on the Me page). With no take, a pick is kept as the device default signed out and not at
 * all signed in. Every other key reads and writes `storage` unchanged. `storage` may be null (private mode): reads
 * then give null and writes do nothing, as the picker expects.
 */
export async function youStorage(storage, callImpl = call, { job = null } = {}) {
  const server = await loadServerDefault(callImpl);
  lastServer = server;
  const takeKey = job ? `${YOU_KEY}.${job}` : null;
  const read = (key) => { try { return storage ? storage.getItem(key) : null; } catch { return null; } };
  const write = (key, value) => { if (storage) storage.setItem(key, value); };
  return {
    getItem: (key) => (key === YOU_KEY ? (takeKey && read(takeKey)) || preferredChoice({ ...server, local: read(key) }) : read(key)),
    setItem: (key, value) => {
      if (key !== YOU_KEY) return write(key, value);
      if (takeKey) return write(takeKey, value);
      if (!server.signedIn) write(key, value);
    },
  };
}

/** "Your default is set on Me." under a result's model picker (`host`), only when signed in. Resolves the line or null. */
export async function mountDefaultHint(host, callImpl = call) {
  const server = lastServer || await loadServerDefault(callImpl);
  return server.signedIn ? renderDefaultHint(host, { t: TEXT }) : null;
}
