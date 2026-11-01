// The sign-in screens from plain data (web/model/auth.js words come in as `t`), styled by theme/auth.css on the
// brand tokens. No fetching and no storage.
import { h, clear, stateBlock, linkButton } from "../ui.js";

const errorLine = (text) => h("p", { class: "au-error", role: "alert", "data-testid": "auth-error", text: text || "" });

function field({ id, label, hint, input }) {
  return h("div", { class: "au-field" },
    h("label", { class: "au-label", for: id, text: label }), input, hint ? h("p", { class: "au-hint", text: hint }) : null);
}

/** Email entry. Returns { setError }. */
export function renderEmail(host, { t, email = "", error = "" }, { onInput, onSubmit }) {
  const input = h("input", { class: "input au-input", id: "au-email", name: "email", type: "email", autocomplete: "email",
    inputmode: "email", autocapitalize: "off", spellcheck: "false", value: email, "data-testid": "auth-email" });
  const err = errorLine(error);
  input.addEventListener("input", () => onInput(input.value));
  const form = h("form", { class: "au-form", novalidate: true, "data-testid": "auth-email-form" },
    field({ id: "au-email", label: t.emailLabel, hint: t.emailHint, input }), err,
    h("button", { class: "btn primary au-submit", type: "submit", "data-testid": "auth-send", text: t.send }));
  form.addEventListener("submit", (e) => { e.preventDefault(); onSubmit(); });
  clear(host).classList.add("au");
  host.append(h("h1", { class: "au-title", text: t.title }), h("p", { class: "au-lead", text: t.intro }), form);
  return { setError: (text) => { err.textContent = text || ""; }, focus: () => input.focus() };
}

/** Code entry after the mail is sent. Returns { setError }. */
export function renderCode(host, { t, notice, error = "" }, { onInput, onSubmit, onOther }) {
  const input = h("input", { class: "input au-input au-code", id: "au-code", name: "code", type: "text", autocomplete: "one-time-code",
    inputmode: "numeric", pattern: "[0-9 ]*", autocapitalize: "off", spellcheck: "false", "data-testid": "auth-code" });
  const err = errorLine(error);
  input.addEventListener("input", () => { const v = onInput(input.value); if (typeof v === "string" && v !== input.value) input.value = v; });
  const form = h("form", { class: "au-form", novalidate: true, "data-testid": "auth-code-form" },
    field({ id: "au-code", label: t.codeLabel, input }), err,
    h("button", { class: "btn primary au-submit", type: "submit", "data-testid": "auth-verify", text: t.codeSubmit }),
    h("button", { class: "btn secondary au-submit", type: "button", "data-testid": "auth-other", text: t.otherEmail, onclick: onOther }));
  form.addEventListener("submit", (e) => { e.preventDefault(); onSubmit(); });
  clear(host).classList.add("au");
  host.append(h("h1", { class: "au-title", "data-testid": "auth-code-title", text: t.codeTitle }),
    h("p", { class: "au-lead", "data-testid": "auth-notice", text: notice }), form);
  return { setError: (text) => { err.textContent = text || ""; }, focus: () => input.focus() };
}

/** A working state: sending the mail or checking a code or link. */
export function renderWorking(host, text) {
  clear(host).classList.add("au");
  host.append(h("p", { class: "au-working", role: "status", "data-testid": "auth-working", text }));
}

/** Sign-in is off on this server: said plainly, with a way back. */
export function renderOff(host, { t }) {
  clear(host).classList.add("au");
  host.append(stateBlock("auth-off", t.off, t.offBody, linkButton("#/", t.back, "auth-back")));
}

/** The header link; nothing at all (the host is emptied and hidden) when `link` is null. */
export function renderAuthLink(host, link) {
  clear(host);
  host.hidden = !link;
  if (link) host.append(h("a", { class: "au-link", href: link.href, "data-testid": "auth-link", text: link.label }));
}
