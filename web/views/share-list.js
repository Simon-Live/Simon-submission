// "Your share links" with a Revoke button each (docs/specs/share.md). Mounted once by the Me page (web/me-page.js),
// which holds the profile too. Signed out: nothing. Never shows a token, which the server does not keep.
import { h, clear, ensureCss } from "../ui.js";
import { call } from "../me-api.js";
import { fetchMe } from "../auth.js";

/**
 * @param {HTMLElement} el  @param {object} model the share model, injected by web/share.js
 * @param {{signedIn?: boolean}} [opts] a page that has already asked auth/me passes the answer: true sends the list
 *   request at once (before the page goes on, so a later sign-out cannot turn it into a 401), false sends nothing.
 *   Left out, the list asks auth/me itself first.
 * @returns {() => void} cleanup
 */
export function mountShareList(el, model, { signedIn } = {}) {
  const { TEXT, kindWord, stateWord, createdText } = model;
  ensureCss("theme/share.css", "data-share-css");
  let live = true;
  const list = h("ul", { class: "sh-rows", "data-testid": "share-rows" });
  const note = h("p", { class: "sh-hint", role: "status", "aria-live": "polite", "data-testid": "share-list-status" });
  const all = h("button", { type: "button", class: "btn secondary", "data-testid": "share-revoke-all", "aria-expanded": "false", text: TEXT.revokeAll, hidden: true });
  const allYes = h("button", { type: "button", class: "btn danger", "data-testid": "share-revoke-all-yes", text: TEXT.revokeAllYes });
  const allNo = h("button", { type: "button", class: "btn secondary", "data-testid": "share-revoke-all-no", text: TEXT.revokeAllNo });
  const sure = h("div", { class: "sh-sure", role: "group", "aria-labelledby": "sh-sure-text", "data-testid": "share-revoke-all-sure", hidden: true },
    h("p", { id: "sh-sure-text", text: TEXT.revokeAllSure }), h("div", { class: "row" }, allYes, allNo));
  const box = h("section", { class: "sh-list-box", "data-testid": "share-list", hidden: true }, h("h2", { text: TEXT.listTitle }), list, all, sure, note);
  el.append(box);

  function row(item) {
    const live_ = item.state === "active";
    const button = h("button", { type: "button", class: "btn secondary", "data-testid": "share-revoke", text: TEXT.revoke, disabled: !live_,
      "aria-label": `${TEXT.revoke}: ${item.title || kindWord(item.kind)}` });
    const state = h("span", { class: "sh-state", "data-testid": "share-state", "data-state": item.state, text: stateWord(item) });
    button.addEventListener("click", async () => {
      button.disabled = true;
      const out = await call("DELETE", `api/me/shares/${item.id}`, {}) /* JSON content type: the same-origin guard needs it */;
      if (!live) return;
      if (out.ok) { state.textContent = stateWord({ ...item, state: "revoked" }); state.dataset.state = "revoked"; note.textContent = ""; }
      else { button.disabled = false; note.textContent = TEXT.revokeFailed; }
    });
    const extras = [item.show_name ? "name shown" : null, item.show_clip ? "clip included" : null].filter(Boolean).join(", ");
    return h("li", { class: "sh-row", "data-testid": "share-row" },
      h("strong", { text: `${kindWord(item.kind)}${item.title ? `: ${item.title}` : ""}` }), " ", state,
      createdText(item) ? h("span", { class: "sh-hint", "data-testid": "share-created", text: ` ${createdText(item)}.` }) : null,
      extras ? h("span", { class: "sh-hint", text: ` (${extras})` }) : null, " ", button);
  }

  async function load() {
    const out = await call("GET", "api/me/shares", undefined, { expectStatus: [401, 404] }); // fetch starts in this tick
    if (!live) return;
    box.hidden = false;
    if (!out.ok) { note.textContent = TEXT.listFailed; return; }
    const items = Array.isArray(out.body?.shares) ? out.body.shares : [];
    clear(list).append(...items.map(row));
    all.hidden = !items.some((i) => i.state === "active");
    if (!items.length) note.textContent = TEXT.listEmpty;
  }
  const closeSure = () => { sure.hidden = true; all.setAttribute("aria-expanded", "false"); };
  all.addEventListener("click", () => { sure.hidden = false; all.setAttribute("aria-expanded", "true"); allNo.focus(); });
  allNo.addEventListener("click", () => { closeSure(); all.focus(); });
  allYes.addEventListener("click", async () => {
    allYes.disabled = true;
    const out = await call("DELETE", "api/me/shares", {}); // JSON content type: the same-origin guard needs it
    allYes.disabled = false;
    if (!live) return;
    closeSure();
    if (!out.ok) { note.textContent = TEXT.revokeAllFailed; all.focus(); return; }
    await load();
    note.textContent = TEXT.revokedAll;
  });
  if (signedIn === true) load();
  else if (signedIn === undefined) fetchMe().then((me) => (me.signedIn && live ? load() : null)).catch(() => {});
  return () => { live = false; box.remove(); };
}
