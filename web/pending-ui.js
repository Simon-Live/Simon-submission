// Offline takes on screen (offline-takes.md): the header banner on every screen, the #/pending list and the
// #/pending/<id> screen that reopens a saved take at the person picker. All state comes from web/pending.js.
import { h, clear, ensureCss, stateBlock, linkButton } from "./ui.js";
import { createProgress } from "./progress.js";
import { getPending } from "./pending-app.js";
import { getConfig } from "./api.js";
import { TEXT, statusText, SENDABLE } from "./pending.js";

const ensureStyles = () => ensureCss("pending.css", "data-simon-pending-css");

export const waitingText = (n) => `${n} ${n === 1 ? "take" : "takes"} waiting to send`;
export const sizeText = (bytes) => (bytes >= 1e6 ? `${(bytes / 1e6).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1e3))} KB`);
export const whenText = (ms, now = Date.now()) => {
  const mins = Math.round((now - ms) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  if (mins < 24 * 60) return `${Math.round(mins / 60)} h ago`;
  return `${Math.round(mins / 1440)} d ago`;
};
export const titleOf = (rec) => (rec.role === "follow" ? (rec.entry_name || "Your take") : (rec.name || "New movement"));

/** The banner under the header: how many takes wait, the live percentage, and the notice after a background send. */
export function mountPendingBanner(el, pending) {
  ensureStyles();
  let note = null; // {job}
  let live = true;
  let sending = null;
  const progress = createProgress({ testid: "pending-progress", label: "Sending your saved take", text: "" });
  async function paint() {
    if (!live) return;
    const waiting = (await pending.list()).filter((r) => !pending.isOwned(r.id)); // the take being sent from the open screen is not "waiting"
    const kids = [];
    if (note) {
      kids.push(h("p", { class: "pending-line", "data-testid": "pending-sent", role: "status" },
        h("span", { text: TEXT.sent + " " }), h("a", { href: `#/job/${encodeURIComponent(note.job)}`, "data-testid": "pending-sent-link", text: "See progress" }),
        h("button", { type: "button", class: "btn-link", "data-testid": "pending-dismiss", text: "Dismiss", onclick: () => { note = null; paint(); } })));
    }
    if (waiting.length) {
      if (sending) {
        progress.setValue(sending.fraction);
        progress.setText(sending.fraction == null ? "Sending" : `Sending, ${Math.round(sending.fraction * 100)}%`);
        kids.push(progress.el);
      } else {
        kids.push(h("p", { class: "pending-line", "data-testid": "pending-count", text: waitingText(waiting.length) }));
      }
      kids.push(h("a", { class: "pending-link", href: "#/pending", "data-testid": "pending-link", text: "See saved takes" }));
    }
    el.replaceChildren(...kids);
    el.hidden = kids.length === 0;
  }
  const off = pending.subscribe((evt) => {
    if (evt.type === "sent" && evt.headless) note = { job: evt.job };
    if (evt.type === "progress") sending = evt.sending && !pending.isOwned(evt.id) ? { id: evt.id, fraction: evt.fraction } : null;
    paint();
  });
  paint();
  return () => { live = false; off(); };
}

/** `#/pending`: every saved take with Send now / Finish / Delete. */
export function mountPendingList(root) {
  ensureStyles();
  let live = true;
  let off = () => {};
  let sending = null;
  const list = h("ul", { class: "pending-list", "data-testid": "pending-list" });
  const screen = h("section", { class: "screen pending-screen", "data-testid": "pending" },
    h("h1", { text: "Saved takes" }),
    h("p", { class: "lede", text: TEXT.privacy }),
    list);
  root.append(screen);
  getPending().then((pending) => {
    if (!live) return;
    async function paint() {
      const recs = await pending.list();
      if (!live) return;
      list.replaceChildren(...recs.map((rec) => row(pending, rec)));
      screen.querySelector('[data-testid="pending-empty"]')?.remove();
      if (!recs.length) screen.append(stateBlock("pending-empty", "Nothing is waiting to send", "A take you record is kept here if the app cannot be reached.", linkButton("#/", "Back to movements", "back-home")));
    }
    function row(p, rec) {
      const id = rec.id;
      const sendable = SENDABLE.includes(rec.stage);
      const status = h("p", { class: "pending-status", "aria-live": "polite", "data-testid": `pending-status-${id}`, text: statusText(rec, { sending }) });
      const send = sendable ? h("button", { type: "button", class: "btn primary", "data-testid": `pending-send-${id}`, text: "Send now", onclick: () => p.sendNow(id) }) : null;
      const finish = rec.stage === "people_ready" ? linkButton(`#/pending/${encodeURIComponent(id)}`, "Finish", `pending-finish-${id}`, "primary") : null;
      const del = h("button", { type: "button", class: "btn secondary", "data-testid": `pending-delete-${id}`, text: "Delete", onclick: async () => { await p.remove(id, "user"); } });
      return h("li", { class: "pending-row", "data-testid": `pending-${id}`, "data-stage": rec.stage },
        h("p", { class: "pending-title", text: titleOf(rec) }),
        h("p", { class: "hint", text: `${TEXT.safe} · recorded ${whenText(rec.created_at)} · ${sizeText(rec.size)}` }),
        status, h("div", { class: "row" }, send, finish, del));
    }
    off = pending.subscribe((evt) => {
      if (evt.type === "progress") {
        sending = evt.sending ? { id: evt.id, fraction: evt.fraction } : null;
        const node = sending && list.querySelector(`[data-testid="pending-status-${sending.id}"]`);
        if (node) { node.textContent = statusText({ id: sending.id }, { sending }); return; }
      }
      paint();
    });
    paint();
  });
  return () => { live = false; off(); };
}

/** `#/pending/<id>` (Finish): the take flow reopened at the picker and details, from the saved record. */
export function mountPendingResume(root, id) {
  ensureStyles();
  let live = true;
  let stop = () => {};
  const screen = h("section", { class: "screen", "data-testid": "pending-resume" });
  root.append(screen);
  Promise.all([getPending(), getConfig(), import("./take-flow.js")]).then(async ([pending, cfg, flow]) => {
    if (!live) return;
    const rec = await pending.get(id);
    if (!rec) { clear(screen).append(stateBlock("pending-gone", TEXT.gone, "", linkButton("#/pending", "Saved takes", "pending-back"))); return; }
    if (rec.stage !== "people_ready") {
      clear(screen).append(stateBlock("pending-busy", "This take is still being sent", "It will be ready to finish in a moment.", linkButton("#/pending", "Saved takes", "pending-back")));
      return;
    }
    const box = h("div", {});
    clear(screen).append(
      h("p", { class: "crumb" }, h("a", { href: "#/pending", text: "Saved takes" })),
      h("h1", { text: titleOf(rec) }),
      h("p", { class: "lede", text: `${TEXT.safe}. ${TEXT.peopleReady}` }),
      box);
    stop = flow.mountTakeFlow(box, { role: rec.role === "follow" ? "follower" : "trainer", entryId: rec.entry_id, limits: cfg.limits, resume: rec });
  });
  return () => { live = false; stop(); };
}
