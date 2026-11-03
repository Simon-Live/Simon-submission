// The profile section of the Me page from plain data (words come in as `t`, rows and options from model/profile.js),
// styled by theme/profile.css on the brand tokens. No fetching and no storage. The Me page holds the one h1, so the
// section title is an h2; the devices card is placed after `devicesAnchor` by the glue.
import { h, clear, stateBlock, linkButton } from "../ui.js";

const note = (testid) => h("p", { class: "pf-note", role: "status", "aria-live": "polite", "data-testid": testid, text: "" });
const setNote = (el, text, bad = false) => { el.textContent = text || ""; el.setAttribute("data-tone", bad ? "bad" : "ok"); };

/** Not signed in. */
export function renderProfileSignedOut(host, { t }) {
  clear(host).classList.add("pf");
  host.append(stateBlock("profile-signed-out", t.signedOutTitle, t.signedOutBody, linkButton("#/signin", t.signIn, "profile-signin")));
}

/** The load failed (not a refusal). `onRetry` loads again. */
export function renderProfileError(host, { t }, onRetry) {
  clear(host).classList.add("pf");
  const retry = h("button", { type: "button", class: "btn secondary", "data-testid": "profile-retry", text: t.retry, onclick: onRetry });
  host.append(h("section", { class: "state", "data-testid": "profile-error" },
    h("h2", { text: t.errorTitle }), h("p", { text: t.errorBody }), h("div", { class: "row" }, retry, linkButton("#/", t.back, "profile-back"))));
}

/** The avatar disc: a letter on a token colour. Decorative; the name beside it carries the meaning. */
export function avatarDisc(option, testid) {
  return h("span", { class: "pf-disc", "data-tone": option ? option.tone : "none", "aria-hidden": "true", "data-testid": testid, text: option ? option.initial : "" });
}

function group(legend, hint, testid, ...kids) {
  return h("fieldset", { class: "pf-group", "data-testid": testid },
    h("legend", { class: "pf-legend", text: legend }),
    hint ? h("p", { class: "pf-hint", text: hint }) : null,
    ...kids);
}

function tick(id, label, hint, get, onChange, testid, syncers) {
  const box = h("input", { type: "checkbox", id, class: "pf-check", "data-testid": testid });
  syncers.push((p) => { box.checked = Boolean(get(p)); });
  box.addEventListener("change", () => onChange(box.checked));
  return h("div", { class: "pf-tick" }, box,
    h("label", { for: id, class: "pf-tick-text" }, h("span", { text: label }), hint ? h("span", { class: "pf-hint", text: hint }) : null));
}

function rowsList(rows, empty, testid) {
  if (!rows.length) return h("p", { class: "pf-empty", "data-testid": `${testid}-empty`, text: empty });
  return h("ul", { class: "pf-list", "data-testid": testid },
    ...rows.map((r, i) => h("li", { class: "pf-row", "data-testid": `${testid}-${i}` },
      h("a", { class: "pf-row-link", href: r.href, text: r.name }),
      r.line ? h("span", { class: "pf-row-line", text: r.line }) : null)));
}

/**
 * The profile page. `vm`: { t, fn, profile, avatars, modes, goals, movements, entries, summary }; `fn` holds the model's
 * pure helpers { checkName, toggled, draftFrom, shownName } (a view imports no model module).
 * `on`: { save(draft) -> {ok, text, profile?}, remove() -> {ok, text, profile?} }. Returns { devicesAnchor, setProfile }.
 */
export function renderProfile(host, vm, on) {
  const { t, fn } = vm;
  const { checkName, toggled, draftFrom, shownName } = fn;
  clear(host).classList.add("pf");
  let draft = draftFrom(vm.profile);
  const syncers = [];

  const title = h("h2", { class: "pf-title", "data-testid": "profile-title", tabindex: "-1", text: t.title });
  const who = h("p", { class: "pf-who", "data-testid": "profile-who" });
  const drawWho = (p) => { clear(who).append(avatarDisc(vm.avatars.find((a) => a.id === p.avatar) || null, "profile-who-avatar"), h("span", { text: shownName(p) })); };
  drawWho(vm.profile);

  // display name
  const name = h("input", { type: "text", id: "pf-name", class: "pf-input", autocomplete: "nickname", maxlength: "80", "aria-describedby": "pf-name-hint pf-name-error", "data-testid": "profile-name" });
  const nameError = h("p", { class: "pf-error", id: "pf-name-error", role: "alert", "data-testid": "profile-name-error", text: "" });
  name.value = draft.name;
  name.addEventListener("input", () => { draft.name = name.value; nameError.textContent = ""; name.removeAttribute("aria-invalid"); });
  const nameField = h("div", { class: "pf-field" },
    h("label", { for: "pf-name", class: "pf-label", text: t.nameLabel }),
    h("p", { class: "pf-hint", id: "pf-name-hint", text: t.nameHint }), name, nameError);

  // avatar: native radios, so arrow keys and labels work without script
  const picks = [{ id: "", label: t.avatarNone, tone: "none" }, ...vm.avatars].map((a, i) => {
    const input = h("input", { type: "radio", name: "pf-avatar", id: `pf-avatar-${i}`, class: "pf-radio", value: a.id, "data-testid": `profile-avatar-${a.id || "none"}` });
    syncers.push((p) => { input.checked = p.avatar === a.id; });
    input.checked = draft.avatar === a.id;
    input.addEventListener("change", () => { if (input.checked) draft.avatar = a.id; });
    return h("label", { class: "pf-pick", for: `pf-avatar-${i}` }, input, a.id ? avatarDisc(a) : h("span", { class: "pf-disc", "data-tone": "none", "aria-hidden": "true", text: "-" }), h("span", { class: "pf-pick-text", text: a.label }));
  });
  const avatarGroup = group(t.avatarLegend, t.avatarHint, "profile-avatars", h("div", { class: "pf-picks" }, picks));

  const checks = (list, key, prefix, legend, testid) => group(legend, "", testid,
    ...list.map((o, i) => tick(`pf-${prefix}-${i}`, o.label, "", (p) => p[key].includes(o.id), () => { draft[key] = toggled(draft[key], o.id, list); }, `profile-${prefix}-${i}`, syncers)));
  const modesGroup = checks(vm.modes, "modes", "mode", t.modesLegend, "profile-modes");
  const goalsGroup = checks(vm.goals, "goals", "goal", t.goalsLegend, "profile-goals");
  const privacy = group(t.privacyLegend, "", "profile-privacy",
    tick("pf-show-name", t.showName, t.showNameHint, (p) => p.showName, (v) => { draft.showName = v; }, "profile-show-name", syncers),
    tick("pf-credit", t.credit, t.creditHint, (p) => p.creditTrainer, (v) => { draft.creditTrainer = v; }, "profile-credit", syncers));

  const saveNote = note("profile-save-note");
  const save = h("button", { type: "submit", class: "btn primary pf-save", "data-testid": "profile-save", text: t.save });
  const form = h("form", { class: "pf-form", "data-testid": "profile-form", novalidate: true }, nameField, avatarGroup, modesGroup, goalsGroup, privacy, save, saveNote);
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const check = checkName(draft.name);
    if (!check.ok) {
      nameError.textContent = check.error;
      name.setAttribute("aria-invalid", "true");
      name.focus();
      return;
    }
    save.disabled = true;
    setNote(saveNote, t.saving);
    const out = await on.save({ ...draft, name: check.name });
    save.disabled = false;
    setNote(saveNote, out.text, !out.ok);
    if (out.ok && out.profile) { draft = draftFrom(out.profile); drawAll(out.profile); }
  });

  // what the account holds
  const holds = h("section", { class: "pf-card", "data-testid": "profile-holds" },
    h("h2", { text: t.movements }), rowsList(vm.movements, t.movementsEmpty, "profile-movements"),
    h("h2", { text: t.entries }), rowsList(vm.entries, t.entriesEmpty, "profile-entries"),
    h("h2", { text: t.summary }),
    vm.summary.length
      ? h("ul", { class: "pf-list", "data-testid": "profile-summary" }, ...vm.summary.map((l) => h("li", { class: "pf-row", text: l })))
      : h("p", { class: "pf-empty", "data-testid": "profile-summary-empty", text: t.summaryEmpty }),
    vm.cappedNote ? h("p", { class: "pf-hint", "data-testid": "profile-capped", text: vm.cappedNote }) : null);

  const devicesAnchor = h("div", { class: "pf-anchor", "data-testid": "profile-devices-anchor", hidden: true });

  // delete the profile details, behind a confirmation
  const delNote = note("profile-delete-note");
  const del = h("button", { type: "button", class: "btn secondary", "data-testid": "profile-delete", "aria-expanded": "false", text: t.deleteButton });
  const yes = h("button", { type: "button", class: "btn danger", "data-testid": "profile-delete-yes", text: t.deleteYes });
  const no = h("button", { type: "button", class: "btn secondary", "data-testid": "profile-delete-no", text: t.deleteNo });
  const sure = h("div", { class: "pf-sure", role: "group", "aria-labelledby": "pf-sure-text", "data-testid": "profile-delete-sure", hidden: true },
    h("p", { class: "pf-warn", id: "pf-sure-text", text: t.deleteSure }), h("div", { class: "row" }, yes, no));
  const closeSure = () => { sure.hidden = true; del.setAttribute("aria-expanded", "false"); };
  del.addEventListener("click", () => { sure.hidden = false; del.setAttribute("aria-expanded", "true"); no.focus(); });
  no.addEventListener("click", () => { closeSure(); del.focus(); });
  yes.addEventListener("click", async () => {
    yes.disabled = true;
    const out = await on.remove();
    yes.disabled = false;
    closeSure();
    setNote(delNote, out.text, !out.ok);
    if (out.ok && out.profile) { draft = draftFrom(out.profile); drawAll(out.profile); }
    del.focus();
  });
  const danger = h("section", { class: "pf-card", "data-testid": "profile-danger" },
    h("h2", { text: t.deleteTitle }), h("p", { class: "pf-hint", text: t.deleteLead }), del, sure, delNote);

  /** Put a profile back into every field. */
  function drawAll(p) {
    name.value = p.name;
    drawWho(p);
    syncers.forEach((fn) => fn(p));
  }

  syncers.forEach((fn) => fn(vm.profile)); // first state of every box and radio
  host.append(title, who, h("p", { class: "pf-lead", text: t.lead }), form, holds, devicesAnchor, danger);
  return { devicesAnchor, setProfile: (p) => { draft = draftFrom(p); drawAll(p); } };
}
