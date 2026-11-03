// "Takes on this movement" on the watch page and "Recorded in this browser" on Me (docs/specs/takes-on-movement.md,
// TICKET-327): model/takes-on.js for the logic, views/takes-on.js for the DOM, me-api.js `call` for the one request.
import { ensureCss } from "./ui.js";
import { call } from "./me-api.js";
import { TEXT, deviceTakes, deviceRows, rememberTake, takesOnUrl, takesOnView } from "./model/takes-on.js";
import { meInfo } from "./model/auth.js";
import { renderTakesOn, renderTakesOnError, renderDeviceTakes } from "./views/takes-on.js";

/**
 * Remember a take this browser sent, only when the server says nobody is signed in: a signed-in take is the account's
 * (api/me/takes) and is never kept in the browser. A failed check keeps nothing (fails closed). Resolves to whether it was kept.
 */
export async function rememberSignedOutTake(job, entry, name, { storage, me = () => call("GET", "api/auth/me") } = {}) {
  const out = await me();
  if (!out || !out.ok || !out.body || out.body.signed_in === true || meInfo(out.body).signedIn) return false;
  rememberTake(job, entry, name, storage);
  return true;
}

/** The shared one-letter row helper (model/score-labels.js `shownRow`, docs/specs/one-letter.md) when the build has it. */
export const loadPick = () => import("./model/score-labels.js").then((m) => (typeof m.shownRow === "function" ? m.shownRow : null)).catch(() => null);

/** Mount the two lists for `entry` into `el`. Returns the cleanup function. */
export function mountTakesOn(el, entry, { storage, fetchTakes = (url) => call("GET", url, undefined, { expectStatus: [404] }), pick = loadPick } = {}) {
  ensureCss("theme/auth.css", "data-auth-css");
  let live = true;
  Promise.all([fetchTakes(takesOnUrl(entry, deviceTakes(storage))), pick()]).then(([out, chosen]) => {
    if (!live) return;
    if (out.status === 404) return; // a movement this caller may not see: the watch page says so itself
    if (!out.ok) return renderTakesOnError(el, { t: TEXT });
    renderTakesOn(el, { t: TEXT, ...takesOnView(out.body, entry, chosen) });
  });
  return () => { live = false; };
}

/**
 * Mount the Me page card of the takes this browser sent. Signed in, the takes the account already lists (`api/me/takes`)
 * are left out, so a take shows once. Returns the cleanup function.
 */
export function mountDeviceTakes(el, { signedIn = false, storage, fetchMine = () => call("GET", "api/me/takes") } = {}) {
  ensureCss("theme/auth.css", "data-auth-css");
  let live = true;
  const list = deviceTakes(storage);
  if (!list.length) return () => {};
  (signedIn ? fetchMine() : Promise.resolve(null)).then((out) => {
    if (!live) return;
    const owned = new Set(out && out.ok && Array.isArray(out.body?.takes) ? out.body.takes.map((t) => t && t.job_id) : []);
    renderDeviceTakes(el, { t: TEXT, rows: deviceRows(list.filter((t) => !owned.has(t.job))) });
  });
  return () => { live = false; };
}
