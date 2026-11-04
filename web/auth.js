// Glue for sign-in, the Me page, the Keep this take slot and the header link. Logic lives in model/auth.js and
// model/me.js, drawing in views/auth.js and views/me.js. Signed-in state comes from `GET api/auth/me` only: nothing
// is stored in the browser (auth-design.md, contract B to C). Every route here is opt-in; with sign-in off the app
// shows no trace of it.
import { ensureCss } from "./ui.js";
import { call } from "./me-api.js";
import { isProd, policyOn } from "./policy.js"; // a11y-copy B1, B2: the prod consent lines
import {
  TEXT as AUTH_TEXT, initialState, step, sentNotice, parseSigninHash, scrubbedHash, meInfo, headerLink, headerMeLink, codeDigits, OUTBOX_HASH, MAIL_POLL_MS, MAIL_POLL_MAX, mailVerdict,
} from "./model/auth.js";
import {
  TEXT as ME_TEXT, consentLines, consentBody, jobIdFrom, claimError, takeRows, keptTake, deletedSummary, busyIds,
} from "./model/me.js";
import { renderEmail, renderCode, renderWorking, renderOff, renderAuthLink } from "./views/auth.js";
import { mountDownload } from "./my-data.js";
import { accountUnknown, beginAccountCheck, setAccount, forgetAccount, setAccountLoader } from "./model/consent-store.js"; // the Meta tick belongs to the signed-in account
import { forgetTakes } from "./model/takes-on.js"; // TICKET-327: a shared computer keeps no takes past the session
import { forgetKeys, tokenForJob } from "./model/creator-keys.js"; // prod-data.md: only the device that made a take keeps it

/** The claim body: the job id and this browser's creator token for it (LEG-H4: a result link alone never claims). */
const claimBody = (jobId) => ({ job_id: jobId, ...(tokenForJob(jobId) ? { creator_token: tokenForJob(jobId) } : {}) });
import { renderMe, renderMeSignedOut, renderMeError, renderDeleted, renderKeep, renderKept } from "./views/me.js";

const css = () => ensureCss("theme/auth.css", "data-auth-css");

/** Who is signed in, from the server alone. */
export async function fetchMe() {
  beginAccountCheck();
  const out = await call("GET", "api/auth/me", undefined, { expectStatus: [401, 404], timeoutMs: 8000 }); // signed out is a normal answer, not an anomaly
  // A real answer is 401 or 404 (signed out, or sign-in off) or a 200 with a JSON document. Anything else (offline, 403, 429, a fault, a 200
  // that is not JSON) leaves who is signed in unknown: no stored answer is dropped.
  const real = out.status === 401 || out.status === 404 || (out.ok && out.body !== null && typeof out.body === "object");
  if (!real) {
    accountUnknown();
    return { ...meInfo(null), unreachable: true };
  }
  const info = meInfo(out.ok ? out.body : null);
  setAccount(info.userId); // a real answer, signed out included: another account's consent answers are dropped
  return info;
}
setAccountLoader(fetchMe); // the consent gate asks who is signed in before it reads a stored answer

/**
 * `#/signin` and `#/signin/<token>`. With `onSignedIn` it signs in where it stands and calls that instead of going
 * to `#/me` (a take waiting on the page, offline-takes.md AC-OT10); `lead` then replaces the intro.
 */
export function mountSignin(el, token, { onSignedIn = null, lead = "" } = {}) {
  css();
  let live = true;
  let state = initialState();
  let screen = null;
  let outbox = false; // the staging test mailbox is this server's mail (auth/me says so)
  const words = onSignedIn ? { ...AUTH_TEXT, intro: lead, titleTag: "h2" } : AUTH_TEXT;
  const send = (event) => { state = step(state, event); draw(); };
  let doneOnce = false;
  const done = () => {
    if (!onSignedIn) { location.hash = "#/me"; return; }
    if (doneOnce) return;
    doneOnce = true;
    onSignedIn();
  };
  // The link in the mail opens another tab: back here, the server says who is signed in.
  const recheck = async () => { const info = await fetchMe(); if (live && info.signedIn) done(); };
  const onBack = () => { if (document.visibilityState !== "hidden") recheck().catch(() => {}); };
  if (onSignedIn) { document.addEventListener("visibilitychange", onBack); window.addEventListener("focus", onBack); }

  async function start() {
    const out = await call("POST", "api/auth/start", { email: state.email });
    if (outbox) import("./outbox.js").then((m) => m.rememberAddress(state.email)).catch(() => {});
    if (!live) return;
    if (out.status === 202 || out.ok) {
      const attempt = typeof out.body?.attempt === "string" ? out.body.attempt : "";
      send({ type: "started", attempt });
      if (attempt) watchMail(attempt);
    } else send({ type: "start-failed", status: out.status });
  }

  // The mail goes out after the 202. Ask how it went; if the provider refused it, say so instead of "on its way".
  async function watchMail(attempt) {
    for (let n = 0; n < MAIL_POLL_MAX && live && state.attempt === attempt; n += 1) {
      await new Promise((resolve) => setTimeout(resolve, MAIL_POLL_MS));
      if (!live || state.attempt !== attempt) return;
      const verdict = mailVerdict(await call("GET", `api/auth/mail-status?id=${encodeURIComponent(attempt)}`, undefined, { expectStatus: [404, 429] }));
      if (verdict === "failed") return send({ type: "mail-failed" });
      if (verdict === "done") return;
    }
  }

  async function verify(payload, fromLink) {
    const out = await call("POST", "api/auth/verify", payload);
    if (!live) return;
    if (out.ok) { changed(); done(); return; }
    send({ type: "verify-failed", status: out.status, fromLink });
  }

  function draw() {
    const t = words;
    if (state.phase === "off") screen = renderOff(el, { t });
    else if (state.phase === "sending") { renderWorking(el, t.sending); start(); }
    else if (state.phase === "verifying") renderWorking(el, t.verifying);
    else if (state.phase === "code") {
      screen = renderCode(el, { t, notice: sentNotice(state.email), error: state.error, outboxHref: outbox ? OUTBOX_HASH : "" }, {
        onInput: (value) => { state = step(state, { type: "code-input", value }); screen.setError(""); return codeDigits(value); },
        onSubmit: () => { send({ type: "submit-code" }); if (state.phase === "verifying") verify({ email: state.email, code: state.code }, false); },
        onOther: () => send({ type: "other-email" }),
      });
      screen.focus();
    } else {
      screen = renderEmail(el, { t, email: state.email, error: state.error }, {
        onInput: (value) => { state = step(state, { type: "email-input", value }); screen.setError(""); },
        onSubmit: () => send({ type: "submit-email" }),
      });
    }
  }

  (async () => {
    const hit = token ? { kind: "token", token } : parseSigninHash(location.hash);
    if (hit.kind === "token") {
      // The link token never stays in the address bar, the route marker or any request but the one verify POST.
      history.replaceState(null, "", `${location.pathname}${location.search}${scrubbedHash()}`);
      document.body.dataset.route = scrubbedHash();
    }
    const info = await fetchMe();
    if (!live) return;
    outbox = info.outbox;
    if (!info.available) return send({ type: "off" });
    if (info.signedIn && hit.kind !== "token") { done(); return; }
    if (hit.kind === "token") {
      send({ type: "verify-token" });
      verify({ token: hit.token }, true);
    } else draw();
  })();

  return () => {
    live = false;
    if (onSignedIn) { document.removeEventListener("visibilitychange", onBack); window.removeEventListener("focus", onBack); }
  };
}

/** Tells the header link that who is signed in just changed. */
const changed = () => window.dispatchEvent(new Event("auth-changed"));

const reload = async () => {
  const out = await call("GET", "api/me/takes");
  return out.ok ? takeRows(out.body) : null;
};

/** `#/me`: who is signed in, the retention choice, claims, the takes and Delete my data. */
export function mountMe(el) {
  css();
  let live = true;
  const t = ME_TEXT;
  (async () => {
    const info = await fetchMe();
    if (!live) return;
    if (!info.available) return renderOff(el, { t: AUTH_TEXT });
    if (!info.signedIn) return renderMeSignedOut(el, { t });
    const first = await call("GET", "api/me/takes");
    if (!live) return;
    if (first.status === 401) return renderMeSignedOut(el, { t });
    if (!first.ok) return renderMeError(el, { t });
    const view = renderMe(el, { t, email: info.email, optedIn: info.retention.optedIn, consentLines: consentLines(isProd(), policyOn("muse")), rows: takeRows(first.body) }, {
      signOut: async () => { await call("POST", "api/auth/signout", {}); forgetTakes(); forgetKeys(); forgetAccount(); changed(); location.hash = "#/"; },
      consent: async (on) => {
        const out = await call("POST", "api/me/consent", consentBody(on));
        return { ok: out.ok, text: out.ok ? t.consentSaved : t.consentFailed };
      },
      claim: async (raw) => {
        const id = jobIdFrom(raw);
        if (!id) return { ok: false, text: t.claimEmpty };
        const out = await call("POST", "api/me/claims", claimBody(id));
        if (!out.ok) return { ok: false, text: claimError(out.status, out.body) };
        const rows = await reload();
        if (out.body?.kept === false) { if (rows && live) view.setRows(rows); return keepRefused(); }
        if (rows && live) view.setRows(rows);
        return { ok: true, text: t.claimDone };
      },
      delete: async () => {
        const out = await call("POST", "api/me/delete", { confirm: "delete" });
        if (out.ok && out.body?.deleted === true) {
          forgetTakes();
          forgetKeys();
          forgetAccount();
          changed();
          if (live) renderDeleted(el, { t, summary: deletedSummary(out.body) });
          return { ok: true, text: "" };
        }
        const busy = busyIds(out.body);
        return { ok: false, text: busy.length ? t.deleteBusy : t.deleteFailed, busy };
      },
    });
    mountDownload(view.exportSlot);
  })();
  return () => { live = false; };
}

/** The line for a take on the account with no history copy, from the consent as it stands now (another tab may have changed it). */
async function keepRefused() {
  const now = await fetchMe();
  return { ok: false, text: now.retention?.optedIn ? ME_TEXT.keepFailed : ME_TEXT.keepNeedsConsent };
}

/**
 * The Keep this take slot of a finished result: nothing unless signed in; a button when the take is not yours yet;
 * "Kept" when it is. The integrator mounts it on the result screen with the job id.
 */
export function mountKeepTake(el, jobId) {
  css();
  let live = true;
  (async () => {
    const info = await fetchMe();
    if (!live || !info.signedIn) return;
    const list = await call("GET", "api/me/takes");
    if (!live || !list.ok) return;
    if (keptTake(list.body, jobId)) return renderKept(el, { t: ME_TEXT, href: "#/me" });
    renderKeep(el, { t: ME_TEXT }, {
      onKeep: async () => {
        const out = await call("POST", "api/me/claims", claimBody(jobId));
        if (!out.ok) return { ok: false, text: claimError(out.status, out.body) };
        if (out.body?.kept === false) return keepRefused();
        if (live) renderKept(el, { t: ME_TEXT, href: "#/me" });
        return { ok: true, text: ME_TEXT.keepDone };
      },
    });
  })();
  return () => { live = false; };
}

/** The header link: "Sign in" or "Me" when mail is on, nothing at all when it is off. Refreshed on every route change. */
export function mountAuthLink(host) {
  css();
  let live = true;
  const refresh = async () => {
    const info = await fetchMe();
    if (live) renderAuthLink(host, headerLink(info), headerMeLink(info));
  };
  host.hidden = true;
  window.addEventListener("hashchange", refresh);
  window.addEventListener("auth-changed", refresh);
  refresh();
  return () => { live = false; window.removeEventListener("hashchange", refresh); window.removeEventListener("auth-changed", refresh); };
}
