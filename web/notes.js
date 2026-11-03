// Glue for "ask the trainer for a note" (TICKET-237): joins the notes model (model/notes.js) to the notes views
// (views/notes.js) and to the routes. The views import nothing from the model; the model words go in from here.
// Opt-in: signed out, or a take that cannot be sent, shows nothing at all. Nothing is stored in the browser.
import { ensureCss, h } from "./ui.js";
import { call } from "./me-api.js";
import { fetchMe } from "./auth.js";
import * as m from "./model/notes.js";
import * as v from "./views/notes.js";
import { isOrphaned } from "./orphan-take.js";

const css = () => ensureCss("theme/notes.css", "data-notes-css");
const QUIET = { expectStatus: [401, 404, 409, 429] }; // normal answers of this feature, not anomalies
const done = { ok: true, text: "" };

/** The result page slot: the button, the dialog, the state of the request and the note. `(slot, ctx)`. */
export function mountAskTrainer(slot, ctx) {
  if (!ctx || !ctx.job || ctx.job === "fixture" || ctx.pid) return undefined;
  if (ctx.jobRecord && ctx.jobRecord.attribution && ctx.jobRecord.attribution.mine === false) return undefined; // someone else's take: no owner-only request
  if (isOrphaned(ctx.jobRecord)) return undefined; // TICKET-331: the trainer deleted the movement, so there is no one to ask
  css();
  let live = true;
  const host = h("div", { class: "nt-slot", "data-testid": "ask-trainer-slot" });
  let attached = false;
  const load = async () => {
    const out = await call("GET", m.askUrl(ctx.job), undefined, QUIET);
    const view = out.status === 200 ? m.followerView(out.body) : null;
    if (!live) return;
    if (!view) { host.remove(); attached = false; return; } // not eligible, or signed out: no trace
    if (!attached) { slot.append(host); attached = true; }
    v.renderAsk(host, { t: m.TEXT, ...view }, {
      send: async (ticks) => {
        const res = await call("POST", m.askUrl(ctx.job), m.askBody(ticks), QUIET);
        if (!res.ok) return { ok: false, text: m.failureText(res, m.TEXT.sendFailed) };
        await load();
        return done;
      },
      withdraw: async () => {
        const res = await call("POST", m.withdrawUrl(ctx.job), {}, QUIET);
        if (!res.ok) return { ok: false, text: m.failureText(res, m.TEXT.withdrawFailed) };
        await load();
        return done;
      },
    });
  };
  fetchMe().then((me) => (me.signedIn && live ? load() : undefined)).catch(() => {});
  return () => { live = false; host.remove(); };
}

/** The notes of one movement under the history page: `(container, entryId)`. Nothing when there are none. */
export function mountTakeNotes(container, entryId) {
  css();
  let section = null;
  let live = true;
  call("GET", m.notesUrl(entryId), undefined, QUIET).then((out) => {
    const list = out.status === 200 ? m.notesList(out.body) : [];
    if (live && list.length) section = v.renderNotesList(container, { t: m.TEXT, notes: list });
  }).catch(() => {});
  return () => { live = false; if (section) section.remove(); };
}

/** The Me page card, placed after `anchor`: requests waiting for a trainer and new notes for a follower. */
export function mountNotesCard(anchor) {
  css();
  let live = true;
  const card = h("section", { class: "au-card nt", "data-testid": "notes-card", hidden: true });
  anchor.after(card);
  (async () => {
    const [notices, list] = await Promise.all([call("GET", m.NOTICES_URL, undefined, QUIET), call("GET", m.REQUESTS_URL, undefined, QUIET)]);
    const view = notices.status === 200 ? m.cardView(notices.body, list.status === 200 ? list.body : null) : null;
    if (!live || !view) return;
    v.renderCard(card, { t: m.TEXT, ...view });
    card.hidden = false;
    if (view.received.length) await call("POST", m.SEEN_URL, {}, QUIET); // "since the last visit": counted once
  })().catch(() => {});
  return () => { live = false; card.remove(); };
}

/** `#/me/notes/<id>`: the trainer's page for one request. */
export function mountNoteRequest(el, id) {
  css();
  let live = true;
  const t = m.TEXT;
  let stopApprove = null;
  const draw = async () => {
    const out = await call("GET", m.requestUrl(id), undefined, QUIET);
    if (!live) return;
    if (stopApprove) { stopApprove(); stopApprove = null; }
    if (out.status === 401) return v.renderState(el, "request-signed-out", t.signIn, "", h("a", { class: "btn secondary", href: "#/signin", text: "Sign in" }));
    if (out.status === 404) return v.renderState(el, "request-gone", t.gone, t.goneBody);
    const view = out.ok ? m.trainerView(out.body) : null;
    if (!view) return v.renderState(el, "request-error", t.loadFailed, "");
    const closeAfter = async (res) => {
      if (!res.ok) return { ok: false, text: m.failureText(res, t.actFailed) };
      await draw();
      return done;
    };
    const shown = v.renderRequest(el, { t, ...view, counter: (n) => m.counterText(n, view.max) }, {
      send: async (text, at) => closeAfter(await call("POST", m.answerUrl(id), m.answerBody(text, at === "" ? null : Number(at)), QUIET)),
      decline: async () => closeAfter(await call("POST", m.declineUrl(id), {}, QUIET)),
    });
    if (out.body.can_approve_reference === true && live) {   // the open request is the consent (ADR-0019)
      const { mountApproveReference } = await import("./approve-reference.js");
      if (live) stopApprove = mountApproveReference(el, id);
    }
    return shown;
  };
  draw().catch(() => {});
  return () => { live = false; if (stopApprove) stopApprove(); };
}
