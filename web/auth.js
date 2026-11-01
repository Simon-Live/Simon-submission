// Glue for sign-in, the Me page, the Keep this take slot and the header link. Logic lives in model/auth.js and
// model/me.js, drawing in views/auth.js and views/me.js. Signed-in state comes from `GET api/auth/me` only: nothing
// is stored in the browser (auth-design.md, contract B to C). Every route here is opt-in; with sign-in off the app
// shows no trace of it.
import { ensureCss } from "./ui.js";
import { call } from "./me-api.js";
import {
  TEXT as AUTH_TEXT, initialState, step, sentNotice, parseSigninHash, scrubbedHash, meInfo, headerLink, codeDigits,
} from "./model/auth.js";
import {
  TEXT as ME_TEXT, CONSENT_LINES, consentBody, jobIdFrom, claimError, takeRows, holdsTake, deletedSummary, busyIds,
} from "./model/me.js";
import { renderEmail, renderCode, renderWorking, renderOff, renderAuthLink } from "./views/auth.js";
import { renderMe, renderMeSignedOut, renderMeError, renderDeleted, renderKeep, renderKept } from "./views/me.js";

const css = () => ensureCss("theme/auth.css", "data-auth-css");

/** Who is signed in, from the server alone. */
export async function fetchMe() {
  const out = await call("GET", "api/auth/me");
  return meInfo(out.ok ? out.body : null);
}

/** `#/signin` and `#/signin/<token>`. */
export function mountSignin(el, token) {
  css();
  let live = true;
  let state = initialState();
  let screen = null;
  const send = (event) => { state = step(state, event); draw(); };

  async function start() {
    const out = await call("POST", "api/auth/start", { email: state.email });
    if (live) send(out.status === 202 || out.ok ? { type: "started" } : { type: "start-failed", status: out.status });
  }

  async function verify(payload, fromLink) {
    const out = await call("POST", "api/auth/verify", payload);
    if (!live) return;
    if (out.ok) { changed(); location.hash = "#/me"; return; }
    send({ type: "verify-failed", status: out.status, fromLink });
  }

  function draw() {
    const t = AUTH_TEXT;
    if (state.phase === "off") screen = renderOff(el, { t });
    else if (state.phase === "sending") { renderWorking(el, t.sending); start(); }
    else if (state.phase === "verifying") renderWorking(el, t.verifying);
    else if (state.phase === "code") {
      screen = renderCode(el, { t, notice: sentNotice(state.email), error: state.error }, {
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
    if (!info.available) return send({ type: "off" });
    if (info.signedIn && hit.kind !== "token") { location.hash = "#/me"; return; }
    if (hit.kind === "token") {
      send({ type: "verify-token" });
      verify({ token: hit.token }, true);
    } else draw();
  })();

  return () => { live = false; };
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
    const view = renderMe(el, { t, email: info.email, optedIn: info.retention.optedIn, consentLines: CONSENT_LINES, rows: takeRows(first.body) }, {
      signOut: async () => { await call("POST", "api/auth/signout", {}); changed(); location.hash = "#/"; },
      consent: async (on) => {
        const out = await call("POST", "api/me/consent", consentBody(on));
        return { ok: out.ok, text: out.ok ? t.consentSaved : t.consentFailed };
      },
      claim: async (raw) => {
        const id = jobIdFrom(raw);
        if (!id) return { ok: false, text: t.claimEmpty };
        const out = await call("POST", "api/me/claims", { job_id: id });
        if (!out.ok) return { ok: false, text: claimError(out.status) };
        const rows = await reload();
        if (rows && live) view.setRows(rows);
        return { ok: true, text: t.claimDone };
      },
      delete: async () => {
        const out = await call("POST", "api/me/delete", { confirm: "delete" });
        if (out.ok && out.body?.deleted === true) {
          changed();
          if (live) renderDeleted(el, { t, summary: deletedSummary(out.body) });
          return { ok: true, text: "" };
        }
        const busy = busyIds(out.body);
        return { ok: false, text: busy.length ? t.deleteBusy : t.deleteFailed, busy };
      },
    });
  })();
  return () => { live = false; };
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
    if (holdsTake(list.body, jobId)) return renderKept(el, { t: ME_TEXT, href: "#/me" });
    renderKeep(el, { t: ME_TEXT }, {
      onKeep: async () => {
        const out = await call("POST", "api/me/claims", { job_id: jobId });
        if (!out.ok) return { ok: false, text: claimError(out.status) };
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
    if (live) renderAuthLink(host, headerLink(info));
  };
  host.hidden = true;
  window.addEventListener("hashchange", refresh);
  window.addEventListener("auth-changed", refresh);
  refresh();
  return () => { live = false; window.removeEventListener("hashchange", refresh); window.removeEventListener("auth-changed", refresh); };
}
