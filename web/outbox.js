// `#/outbox`: the staging test mailbox. Sign-in mail on staging is kept here for 30 minutes so a tester can read their
// own code and link. It lists only the messages sent to the exact address typed in (prefilled from the sign-in screen
// in the same tab); with no address nothing is listed. Server side: part7/staging_mailbox.py. Opt-in: with sign-in
// or the mailbox off, the page says it is not available.
import { h, clear, stateBlock, linkButton, ensureCss } from "./ui.js";
import { call } from "./me-api.js";
import { fetchMe } from "./auth.js";
import { isEmail, cleanEmail, OUTBOX_KEY, TEXT as AUTH_TEXT } from "./model/auth.js";

export const TEXT = {
  title: "Test mail outbox",
  banner: "Staging test mailbox: anyone using this staging site can read these messages. On staging, anyone who knows an address can read the messages sent to it. Use an address you do not mind sharing.",
  emailLabel: "The address you signed in with",
  show: "Show my messages",
  refresh: "Check again",
  bad: "Enter an email address like name@example.com.",
  none: "No messages for this address in the last 30 minutes. Ask for a code on the sign-in screen, then check again.",
  code: "Code",
  link: "Open the sign-in link",
  useCode: "Sign in with this code",
  wrong: "This code did not work. Ask for a new one.",
  failed: "The outbox could not be reached. Try again.",
  limited: "Too many tries. Wait a little, then try again.",
  signIn: "Back to sign-in",
  off: "The test mail outbox is not available here.",
};

const when = (iso) => new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

/** The address just used on the sign-in screen, kept for this tab only so the outbox page can prefill it. */
export function rememberAddress(email) {
  try { sessionStorage.setItem(OUTBOX_KEY, email); } catch { /* the page then asks for the address */ }
}

export function mountOutbox(el) {
  ensureCss("theme/auth.css", "data-auth-css");
  let live = true;
  let remembered = "";
  try { remembered = sessionStorage.getItem(OUTBOX_KEY) || ""; } catch { /* no storage: the page asks */ }

  async function draw() {
    const info = await fetchMe();
    if (!live) return;
    if (!info.available || !info.outbox) {
      clear(el).classList.add("au");
      el.append(stateBlock("outbox-off", TEXT.off, AUTH_TEXT.offBody, linkButton("#/", AUTH_TEXT.back, "outbox-back")));
      return;
    }
    const input = h("input", { class: "input au-input", id: "ob-email", type: "email", autocomplete: "email", autocapitalize: "off",
      spellcheck: "false", value: remembered, "data-testid": "outbox-email" });
    const status = h("p", { class: "au-error", role: "status", "data-testid": "outbox-status", text: "" });
    const list = h("div", { "data-testid": "outbox-list" });
    async function useCode(m) {
      const out = await call("POST", "api/auth/verify", { email: m.to, code: m.code });
      if (!live) return;
      if (!out.ok) { status.textContent = TEXT.wrong; return; }
      window.dispatchEvent(new Event("auth-changed"));
      location.hash = "#/me";
    }
    let seq = 0;  // the prefilled load and a tap can overlap: only the newest answer fills the list
    async function load() {
      const mine = ++seq;
      const email = cleanEmail(input.value);
      clear(list);
      if (!isEmail(email)) { status.textContent = TEXT.bad; return; }
      const out = await call("GET", `api/auth/outbox?email=${encodeURIComponent(email)}`);
      if (!live || mine !== seq) return;
      clear(list);
      if (!out.ok) { status.textContent = out.status === 429 ? TEXT.limited : TEXT.failed; return; }
      const rows = out.body?.messages || [];
      status.textContent = rows.length ? "" : TEXT.none;
      rows.forEach((m, i) => list.append(h("div", { class: "au-field", "data-testid": `outbox-message-${i}` },
        h("p", { class: "au-hint", text: `${when(m.at)}, to ${m.to}` }),
        h("p", { class: "au-lead" }, `${TEXT.code}: `, h("strong", { "data-testid": `outbox-code-${i}`, text: m.code })),
        h("p", { class: "au-lead" }, h("a", { href: m.link, "data-testid": `outbox-link-${i}`, text: TEXT.link })),
        h("button", { class: "btn secondary au-submit", type: "button", "data-testid": `outbox-use-${i}`, text: TEXT.useCode, onclick: () => useCode(m) }))));
    }
    const form = h("form", { class: "au-form", novalidate: true, "data-testid": "outbox-form" },
      h("div", { class: "au-field" }, h("label", { class: "au-label", for: "ob-email", text: TEXT.emailLabel }), input),
      status, h("button", { class: "btn primary au-submit", type: "submit", "data-testid": "outbox-show", text: TEXT.show }));
    form.addEventListener("submit", (e) => { e.preventDefault(); load(); });
    clear(el).classList.add("au");
    el.append(h("h1", { class: "au-title", text: TEXT.title }),
      h("p", { class: "au-lead", role: "note", "data-testid": "outbox-banner", text: TEXT.banner }), form, list,
      linkButton("#/signin", TEXT.signIn, "outbox-signin"));
    if (isEmail(remembered)) load();
  }
  draw();
  return () => { live = false; };
}
