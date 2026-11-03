// The signed-in devices card of the profile page (TICKET-235): glue between the session routes, the model
// (model/devices.js) and the view (views/devices.js). Mounted by the profile page only when someone is signed in, so a
// signed-out visitor, or an app with sign-in off, sees no trace of it. Nothing is stored in the browser.
import { ensureCss, h } from "./ui.js";
import { call } from "./me-api.js";
import { END_OTHERS_URL, SESSIONS_URL, TEXT, endFailure, endUrl, endedOthers, normalizeRows } from "./model/devices.js";
import { renderDevices, renderDevicesError, renderDevicesLoading } from "./views/devices.js";

const QUIET = { expectStatus: [401, 404] }; // a session ended elsewhere or an id already gone: normal answers, not anomalies

/** Put the card after `anchor` and fill it. Returns the cleanup function. `first`: the answer of GET api/me/sessions
 *  the profile already asked for in the same tick as its other requests; without it the card asks itself. */
export function mountDevices(anchor, { first } = {}) {
  ensureCss("theme/devices.css", "data-devices-css");
  const card = h("section", { class: "pf-card dv", "data-testid": "devices", hidden: true });
  anchor.after(card);
  let live = true;

  async function load(note, noteBad = false, focus = false, given = null) {
    if (!given && !card.querySelector('[data-testid="devices-list"]')) { card.hidden = false; renderDevicesLoading(card, { t: TEXT }); }
    const out = given || await call("GET", SESSIONS_URL, undefined, QUIET);
    if (!live) return;
    if (out.status === 401 || out.status === 404) { card.hidden = true; card.replaceChildren(); return; } // signed out meanwhile, or sign-in off
    card.hidden = false;
    if (!out.ok || !Array.isArray(out.body)) return renderDevicesError(card, { t: TEXT }, () => load());
    renderDevices(card, { t: TEXT, rows: normalizeRows(out.body), note, noteBad }, { end, endOthers });
    if (focus) card.querySelector('[data-testid="devices-title"]')?.focus(); // the button that was pressed is gone: keep the place
  }

  async function end(row) {
    const out = await call("POST", endUrl(row.id), {}, QUIET);
    if (out.ok) return load(TEXT.endedOne, false, true);
    if (out.status === 404) return load(endFailure(404), false, true); // gone already: show the list as it is now
    return load(endFailure(out.status), true, true);
  }

  async function endOthers() {
    const out = await call("POST", END_OTHERS_URL, {}, QUIET);
    if (out.ok) return load(endedOthers(Number(out.body && out.body.ended) || 0), false, true);
    return load(endFailure(out.status), true, true);
  }

  load(undefined, false, false, first || null).catch(() => { if (live) renderDevicesError(card, { t: TEXT }, () => load()); });
  return () => { live = false; card.remove(); };
}
