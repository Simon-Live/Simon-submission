// Who can see a board: the Public / People I choose choice, the owner's panel and the invite results
// (docs/specs/board-visibility.md). The server decides access; this file only asks and shows what it answered.
import { h, clear } from "./ui.js";
import { fetchMe } from "./auth.js";
import { copyText } from "./share-card.js";
import { getAccess, setAccess, splitEmails, mailtoInvite, compact, ChallengeError, MSG_FAILED, MSG_OFFLINE } from "./challenge-core.js";

export const TEXT = {
  legend: "Who can see this challenge?",
  publicLabel: "Public",
  publicHint: "Anyone can see it, with or without the link. It is listed on the movement.",
  invitedLabel: "People I choose",
  invitedHint: "Only the people you list, once they sign in with that address.",
  emails: "Email addresses",
  emailsHint: "Separate them with commas or spaces. Simon mails each one a link.",
  signIn: "Sign in to choose people.",
  sentNote: "Sent means the mail service accepted it. It does not promise the mail arrived.",
  needAddress: "Type at least one email address, or choose Public.",
};

const messageOf = (err) => (err instanceof ChallengeError ? err.message : err && err.message ? MSG_FAILED : MSG_OFFLINE);

/** The one choice, used when a board is made and when it is changed. `read()` gives `{visibility, invites}`. */
export function accessChooser({ signedIn, visibility = "public", idPrefix = "access" } = {}) {
  const radio = (value, label, hint, disabled) => {
    const input = h("input", { type: "radio", name: `${idPrefix}-visibility`, value, id: `${idPrefix}-${value}`, "data-testid": `access-${value}`, disabled: disabled || undefined });
    if (value === visibility && !disabled) input.checked = true;
    return { input, row: h("label", { class: "ch-choice", for: `${idPrefix}-${value}` }, input, h("span", {}, h("strong", { text: label }), h("span", { class: "hint", text: hint }))) };
  };
  const pub = radio("public", TEXT.publicLabel, TEXT.publicHint, false);
  const inv = radio("invited", TEXT.invitedLabel, TEXT.invitedHint, !signedIn);
  const area = h("textarea", { class: "input", rows: "3", id: `${idPrefix}-emails`, "data-testid": "access-emails", autocomplete: "off", spellcheck: "false" });
  const emails = h("div", { class: "field", hidden: true }, h("label", { for: `${idPrefix}-emails`, text: TEXT.emails }), area, h("p", { class: "hint", text: TEXT.emailsHint }));
  const sync = () => { emails.hidden = !inv.input.checked; };
  pub.input.addEventListener("change", sync);
  inv.input.addEventListener("change", sync);
  if (visibility === "invited" && signedIn) { inv.input.checked = true; }
  sync();
  const note = signedIn ? null : h("p", { class: "hint", "data-testid": "access-signin" }, h("a", { href: "#/signin", text: TEXT.signIn }));
  const el = h("fieldset", { class: "ch-access", "data-testid": "access-chooser" }, h("legend", { text: TEXT.legend }), pub.row, inv.row, note, emails);
  return { el, area, read: () => ({ visibility: inv.input.checked ? "invited" : "public", invites: inv.input.checked ? splitEmails(area.value) : [] }) };
}

/** What happened to each invite. "Sent" appears only for a mail the service accepted; a failure shows Try again, the link and a mailto. */
export function renderMailResults(box, access, { title, retry }) {
  clear(box);
  const url = access.link || "";
  const rows = (access.mail || []).map((m, i) => {
    const line = h("li", { class: "ch-mail", "data-testid": `mail-result-${i + 1}`, "data-state": m.state });
    if (m.state === "sent") { line.append(`Invite sent to ${m.email}.`); return line; }
    const why = m.state === "failed" ? `Could not send to ${m.email}. Reference ${m.failure_id}.` : `Not mailed to ${m.email}. Send them the link yourself.`;
    const status = h("span", { role: "status" });
    line.append(...compact([why, " ",
      m.state === "failed" ? h("button", { type: "button", class: "btn secondary", "data-testid": "mail-retry", text: "Try again", onclick: () => retry([m.email]) }) : null,
      h("button", { type: "button", class: "btn secondary", "data-testid": "mail-copy", text: "Copy link", onclick: async () => { status.textContent = (await copyText(url)) ? " Link copied." : " Copy the link from the address bar."; } }),
      h("a", { class: "btn secondary", "data-testid": "mail-mailto", href: mailtoInvite(m.email, title, url), text: "Write it in your mail app" }), status])); // append(null) would print "null"
    return line;
  });
  if (!rows.length) return;
  box.append(h("ul", { class: "ch-mail-list", "data-testid": "mail-results" }, rows));
  if ((access.mail || []).some((m) => m.state === "sent")) box.append(h("p", { class: "hint", text: TEXT.sentNote }));
}

function stateOf(i) {
  if (i.joined) return "Joined";
  if (i.mail === "sent") return "Invited, mail sent";
  if (i.mail === "failed") return "Invited, mail not sent";
  return "Invited, not mailed";
}

/** The owner's panel on the board page: the choice, the list with who has joined, add and remove. */
export async function mountAccessPanel(slot, ch) {
  let access;
  try { access = await getAccess(ch.id); } catch { return; }
  const me = await fetchMe().catch(() => ({ signedIn: true }));
  const box = h("section", { class: "ch-actions-box ch-owner", "data-testid": "access-panel" }, h("h2", { text: "Who can see it" }));
  const results = h("div", { "data-testid": "access-results" });
  const error = h("p", { class: "ch-error", role: "alert", hidden: true, "data-testid": "access-error" });
  const warn = h("p", { class: "hint", role: "status", "data-testid": "access-warning", hidden: true });
  const paint = () => {
    const chooser = accessChooser({ signedIn: me.signedIn !== false, visibility: access.visibility, idPrefix: "own" });
    const list = h("ul", { class: "ch-invites", "data-testid": "access-list" }, access.invites.map((i, n) =>
      h("li", {}, h("span", { text: `${i.email}: ${stateOf(i)}` }), " ",
        h("button", { type: "button", class: "btn secondary", "data-testid": `access-remove-${n + 1}`, text: "Remove", onclick: () => apply({ remove: [i.email] }) }))));
    const save = h("button", { type: "button", class: "btn primary", "data-testid": "access-save", text: "Save", onclick: () => {
      const v = chooser.read();
      if (v.visibility === "invited" && !v.invites.length && !access.invites.length) { error.textContent = TEXT.needAddress; error.hidden = false; return; }
      apply({ visibility: v.visibility, add: v.invites });
    } });
    warn.textContent = access.warning || "";
    warn.hidden = !access.warning;
    clear(box).append(...[chooser.el, access.invites.length ? list : null, h("div", { class: "row" }, save), error, warn, results].filter(Boolean));
  };
  async function apply(change) {
    error.hidden = true;
    error.textContent = "";
    try {
      access = await setAccess(ch.id, change);
      paint();
      renderMailResults(results, access, { title: ch.title, retry: (resend) => apply({ resend }) });
    } catch (err) { error.textContent = messageOf(err); error.hidden = false; }
  }
  paint();
  slot.append(box);
}
