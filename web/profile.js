// The profile section of the Me page (TICKET-231; `#/me`, me-page.js, which also mounts the share list): glue between
// the profile routes, the model (model/profile.js) and the views (views/profile.js). Opt-in like the rest of sign-in:
// with sign-in off or nobody signed in the section says so. The header's one entry point is the Me link (auth.js).
// Nothing is stored in the browser.
import { ensureCss, h } from "./ui.js";
import { call } from "./me-api.js";
import { fetchMe } from "./auth.js";
import { TEXT as AUTH_TEXT } from "./model/auth.js";
import {
  AVATARS_URL, FALLBACK_GOALS, FALLBACK_MODES, HISTORY_URL, PROFILE_URL, TEXT,
  avatarList, cappedLine, checkName, draftFrom, entryRows, failureText, movementRows, normalizeProfile, optionList, shownName, summaryLines, toggled, toWire,
} from "./model/profile.js";
import { mountDevices } from "./devices.js"; // the signed-in devices card (TICKET-235), after the share list slot
import { SESSIONS_URL } from "./model/devices.js";
import { renderOff } from "./views/auth.js";
import { renderProfile, renderProfileError, renderProfileSignedOut } from "./views/profile.js";

const css = () => ensureCss("theme/profile.css", "data-profile-css");
const QUIET = { expectStatus: [401, 404] }; // signed out, or nothing kept yet: normal answers, not anomalies

/** The profile section of `#/me`. Returns the cleanup function. `signedIn`: a page that has already asked auth/me
 *  passes the answer; true sends every request of the section, the devices list too, in the same tick as the page's
 *  takes list, so a sign-out that lands meanwhile cannot draw a 401 (staging verify, the devices card). */
export function mountProfile(el, { signedIn } = {}) {
  css();
  ensureCss("theme/auth.css", "data-auth-css");
  let live = true;
  let stopDevices = () => {};

  let hint = signedIn; // used once: a retry asks auth/me again
  async function load() {
    el.replaceChildren(h("p", { class: "pf-loading", "data-testid": "profile-loading", text: TEXT.loading }));
    const info = hint === true ? { available: true, signedIn: true } : await fetchMe();
    hint = undefined;
    if (!live) return;
    if (!info.available) return renderOff(el, { t: AUTH_TEXT });
    if (!info.signedIn) return renderProfileSignedOut(el, { t: TEXT });
    const [prof, avatars, history, sessions] = await Promise.all([
      call("GET", PROFILE_URL, undefined, QUIET), call("GET", AVATARS_URL, undefined, QUIET), call("GET", HISTORY_URL, undefined, QUIET),
      call("GET", SESSIONS_URL, undefined, QUIET), // the devices card's first list, sent with the rest
    ]);
    if (!live) return;
    if (prof.status === 401) return renderProfileSignedOut(el, { t: TEXT });
    if (!prof.ok || !prof.body) return renderProfileError(el, { t: TEXT }, load);
    draw(prof.body, avatars.ok ? avatars.body : null, history.ok ? history.body : null, sessions);
  }

  function draw(body, avatarBody, historyBody, sessions) {
    const profile = normalizeProfile(body);
    const vm = {
      t: TEXT, profile, fn: { checkName, toggled, draftFrom, shownName },
      avatars: avatarList(avatarBody),
      modes: optionList(avatarBody?.modes ?? profile.options.modes, FALLBACK_MODES),
      goals: optionList(avatarBody?.goals ?? profile.options.goals, FALLBACK_GOALS),
      movements: movementRows(body, historyBody),
      entries: entryRows(body),
      summary: summaryLines(body, historyBody),
      cappedNote: cappedLine(body),
    };
    const view = renderProfile(el, vm, {
      save: async (draft) => {
        const out = await call("PUT", PROFILE_URL, toWire(draft));
        if (!out.ok) return { ok: false, text: failureText(out.status, TEXT.saveFailed) };
        return { ok: true, text: TEXT.saved, profile: normalizeProfile(out.body) };
      },
      remove: async () => {
        const out = await call("DELETE", PROFILE_URL, {}); // JSON content type: the same-origin guard (auth.origin_ok) refuses a DELETE without it
        if (!out.ok) return { ok: false, text: TEXT.deleteFailed };
        window.dispatchEvent(new Event("profile-deleted")); // "My 3D model" (my-model.js) shows the cleared default
        return { ok: true, text: TEXT.deleted, profile: normalizeProfile(out.body) };
      },
    });
    stopDevices(); stopDevices = mountDevices(view.devicesAnchor, { first: sessions });
  }

  load().catch(() => { if (live) renderProfileError(el, { t: TEXT }, load); });
  return () => { live = false; stopDevices(); };
}
