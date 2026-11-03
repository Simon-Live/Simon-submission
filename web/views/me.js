// The Me page from plain data (words come in as `t`, rows from model/me.js), styled by theme/auth.css on the brand
// tokens. No fetching and no storage.
import { h, clear, stateBlock, linkButton } from "../ui.js";

const note = (testid) => h("p", { class: "au-note", role: "status", "data-testid": testid, text: "" });
const setNote = (el, text, bad = false) => { el.textContent = text || ""; el.setAttribute("data-tone", bad ? "bad" : "ok"); };

const takeItem = (r, i, t) => h("li", { class: "au-take", "data-testid": `me-take-${i}`, "data-job": r.jobId },
  h("div", { class: "au-take-head" },
    r.score ? h("strong", { class: "au-score", "data-tone": r.tone, text: r.score }) : null,
    r.grade ? h("span", { class: "au-grade", text: r.grade }) : null,
    h("span", { class: "au-kind", text: r.kind }),
    r.when ? h("time", { class: "au-when", text: r.when }) : null),
  h("a", { class: "au-open", href: r.href, text: t.open }));

/** Not signed in: a way to sign in. Used when #/me is opened by hand. */
export function renderMeSignedOut(host, { t }) {
  clear(host).classList.add("au");
  host.append(stateBlock("me-signed-out", t.signInFirst, "", linkButton("#/signin", t.signIn, "me-signin")));
}

/** The load failed (not a refusal). */
export function renderMeError(host, { t }) {
  clear(host).classList.add("au");
  host.append(stateBlock("me-error", t.loadFailed, "", linkButton("#/", t.back, "me-back")));
}

/** The account was deleted: the only thing left to say. */
export function renderDeleted(host, { t, summary }) {
  clear(host).classList.add("au");
  host.append(stateBlock("me-deleted", t.deleted, summary, linkButton("#/", t.back, "me-back")));
}

/**
 * The Me page. `vm`: { t, email, optedIn, consentLines, rows }. `on`: { signOut, consent(on), claim(text), delete() }.
 * Each handler returns a promise of { ok, text } so the view can show the outcome. Returns { setRows, setBusy }.
 */
export function renderMe(host, vm, on) {
  const { t } = vm;
  clear(host).classList.add("au");

  const box = h("input", { type: "checkbox", id: "me-retention", class: "au-check", "data-testid": "me-retention", checked: vm.optedIn });
  const consentNote = note("me-consent-note");
  box.addEventListener("change", async () => {
    box.disabled = true;
    const out = await on.consent(box.checked);
    box.disabled = false;
    if (!out.ok) box.checked = !box.checked;
    setNote(consentNote, out.text, !out.ok);
  });

  const claimInput = h("input", { class: "input au-input", id: "me-claim", name: "job", type: "text", autocomplete: "off",
    autocapitalize: "off", spellcheck: "false", "data-testid": "me-claim-input" });
  const claimNote = note("me-claim-note");
  const claimForm = h("form", { class: "au-form", novalidate: true, "data-testid": "me-claim-form" },
    h("label", { class: "au-label", for: "me-claim", text: t.claimLabel }), claimInput,
    h("p", { class: "au-hint", text: t.claimHint }), claimNote,
    h("button", { class: "btn secondary au-submit", type: "submit", "data-testid": "me-claim-button", text: t.claimButton }));
  claimForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const out = await on.claim(claimInput.value);
    if (out.ok) claimInput.value = "";
    setNote(claimNote, out.text, !out.ok);
  });

  const list = h("ol", { class: "au-takes", "data-testid": "me-takes" });
  const empty = h("p", { class: "au-hint", "data-testid": "me-takes-empty", text: t.takesEmpty });
  const setRows = (rows) => {
    clear(list).append(...rows.map((r, i) => takeItem(r, i, t)));
    empty.hidden = rows.length > 0;
    list.hidden = rows.length === 0;
  };
  setRows(vm.rows);

  const exportSlot = h("section", { class: "au-card", "data-testid": "me-export-slot" }); // "Download my data" (web/my-data.js)
  const deleteNote = note("me-delete-note");
  const busyList = h("p", { class: "au-hint", "data-testid": "me-busy", hidden: true });
  const ask = h("button", { class: "btn danger au-submit", type: "button", "data-testid": "me-delete", text: t.deleteButton });
  const yes = h("button", { class: "btn danger au-submit", type: "button", "data-testid": "me-delete-confirm", text: t.deleteConfirm });
  const no = h("button", { class: "btn secondary au-submit", type: "button", "data-testid": "me-delete-cancel", text: t.deleteCancel });
  const sure = h("div", { class: "au-sure", "data-testid": "me-delete-sure", hidden: true }, h("p", { class: "au-warn", text: t.deleteSure }), yes, no);
  ask.addEventListener("click", () => { ask.hidden = true; sure.hidden = false; });
  no.addEventListener("click", () => { sure.hidden = true; ask.hidden = false; });
  yes.addEventListener("click", async () => {
    yes.disabled = true;
    const out = await on.delete();
    yes.disabled = false;
    if (out.ok) return;
    sure.hidden = true;
    ask.hidden = false;
    setNote(deleteNote, out.text, true);
    busyList.hidden = !out.busy?.length;
    busyList.textContent = out.busy?.length ? out.busy.join(", ") : "";
  });

  host.append(
    h("h1", { class: "au-title", text: t.title }),
    h("section", { class: "au-card" },
      h("p", { class: "au-who", "data-testid": "me-email", text: t.signedInAs(vm.email) }),
      h("button", { class: "btn secondary au-submit", type: "button", "data-testid": "me-signout", text: t.signOut, onclick: on.signOut })),
    h("section", { class: "au-card", "data-testid": "me-takes-card" }, h("h2", { text: t.takesTitle }), list, empty), // first under the account: one tap from home (TICKET-327)
    h("section", { class: "au-card", "data-testid": "me-consent" },
      h("h2", { text: t.consentTitle }),
      h("label", { class: "au-tick", for: "me-retention" }, box, h("span", { text: t.consentLabel })),
      h("ul", { class: "au-hint pf-points", "data-testid": "me-consent-lines" }, vm.consentLines.map((line) => h("li", { text: line }))), consentNote),
    h("section", { class: "au-card" }, h("h2", { text: t.claimTitle }), claimForm),
    exportSlot,
    h("section", { class: "au-card", "data-testid": "me-delete-card" },
      h("h2", { text: t.deleteTitle }), h("p", { class: "au-hint", text: t.deleteBody }), ask, sure, deleteNote, busyList));
  return { setRows, exportSlot };
}

/** The Keep this take slot on a finished result. States: button, kept, error. Returns { setState }. */
export function renderKeep(host, { t }, { onKeep }) {
  clear(host).classList.add("au-keep");
  const msg = h("p", { class: "au-note", role: "status", "data-testid": "keep-note", text: "" });
  const btn = h("button", { class: "btn secondary au-submit", type: "button", "data-testid": "keep-take", text: t.keepButton });
  btn.addEventListener("click", async () => {
    btn.disabled = true;
    const out = await onKeep();
    btn.disabled = false;
    setNote(msg, out.text, !out.ok);
    if (out.ok) btn.hidden = true;
  });
  host.append(btn, msg);
}

/** Replace the slot with the kept state at once (the take is already in the list). */
export function renderKept(host, { t, href }) {
  clear(host).classList.add("au-keep");
  host.append(h("p", { class: "au-note", "data-tone": "ok", "data-testid": "keep-kept", text: t.keepDone }),
    h("a", { class: "au-open", href, "data-testid": "keep-open", text: t.open }));
}
