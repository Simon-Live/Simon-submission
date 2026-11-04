// "Serverless (Modal)" on the Me page (TICKET-367, parts-harness.md AC-H16): a signed-in person stores their own Modal
// token so "Run on: Serverless" uses their Modal account. The secret is sent once with Save and never comes back:
// api/me/modal answers whether a token is set, the last 4 characters of its ID and the last "Check my credentials"
// result (a fixed reason, never Modal's own output). Nothing is kept in the browser.
import { h } from "./ui.js";
import { call } from "./me-api.js";

export const MODAL_URL = "api/me/modal";
export const CHECK_URL = "api/me/modal/check";
export const DEPLOY_COMMAND = "uvx modal deploy deploy/serverless/part2_app.py";
export const TEXT = {
  title: "Serverless (Modal)",
  intro: "Add your own Modal token and Serverless takes run on your Modal account.",
  id: "Token ID", secret: "Token secret", save: "Save", remove: "Remove", check: "Check my credentials",
  saved: "Saved. Use Check my credentials to test them.",
  removed: "Removed. Simon no longer holds your token. Revoke it in your Modal settings too.",
  // byok audit R4: a Modal token is not scoped to Simon; the person learns that before they make one
  guide: "A Modal token works across its whole Modal workspace: it can deploy and run apps, run up charges and read "
    + "the secrets kept there. Use a separate Modal workspace just for Simon, with a spending limit set. Make a new API "
    + "token in that workspace's settings, and revoke it there when you stop using Simon. Simon deletes a token it has "
    + "not used for 24 hours.",
  expired: "Your last token was deleted after 24 hours unused. Add a new one.",
  // the compute lane's contract (937625f8): api/me/modal `key_unavailable`, the words of part7/modal_creds.py MSG_KEY_DOWN
  keyDown: "This server cannot read saved Modal tokens right now. That is a fault on the server, not your token, and your token is kept. Try again later.",
  setAs: (hint) => `A token is set (${hint}).`, notSet: "No token is set.",
  failed: "That did not work. Check the token and try again.",
  checking: "Checking. This takes up to 30 seconds.",
  checkOk: "Your token works and Simon's app is in your Modal workspace.",
  checkBad: (reason) => `The check did not pass: ${reason}.`,
  // a11y R5: the person has no Simon checkout. The docs name only the deploy command (deploy/serverless/README.md), not
  // where its file comes from, so the operator fills that line; the prod start check refuses it while it is a draft.
  deploy: "Your Modal account needs Simon's Part 2 app, deployed in your Modal workspace with this command:",
  deployWhere: "Ask whoever runs this Simon server for the file deploy/serverless/part2_app.py.",
  // serverless-compute.md AC-SC12: the server says `paused`; the form stays visible and does nothing
  wip: "Work in progress",
  paused: "Bring-your-own compute is paused. Simon runs the GPU work for now, so you do not need a Modal token.",
};
const QUIET = { expectStatus: [400, 401, 404, 409, 429, 503] };
const POLL_MS = 2000;
const POLLS = 20;

/** Pure: whether api/me/modal says this person has their own token. */
export const hasOwnModal = (doc) => !!doc && doc.set === true;

/** Pure: the plain words for a stored check result, or "" when there is none. */
export const checkText = (check) => (!check ? "" : check.ok ? TEXT.checkOk : TEXT.checkBad(String(check.reason || "check failed")));

/** Put the section into `slot` and fill it. Returns the cleanup function. Mounted for a signed-in person only.
 *  `wait(ms)` is the poll delay (a test passes a fast one). */
export function mountModalCreds(slot, { wait = (ms) => new Promise((r) => setTimeout(r, ms)) } = {}) {
  let live = true;
  const status = h("p", { "data-testid": "modal-status" });
  const result = h("p", { "data-testid": "modal-check-result" });
  const note = h("p", { "data-testid": "modal-note", role: "status" });
  // a11y-copy R4: a refused Save names the two fields; the error is linked to them and they are marked invalid
  const fieldError = h("p", { class: "error", id: "modal-token-error", role: "alert", "data-testid": "modal-token-error", hidden: true });
  const id = h("input", { type: "text", autocomplete: "off", spellcheck: "false", "data-testid": "modal-token-id" });
  const secret = h("input", { type: "password", autocomplete: "new-password", "data-testid": "modal-token-secret" });
  const markFields = (message) => {
    fieldError.textContent = message || "";
    fieldError.hidden = !message;
    for (const el of [id, secret]) {
      if (message) { el.setAttribute("aria-invalid", "true"); el.setAttribute("aria-describedby", "modal-token-error"); }
      else { el.removeAttribute("aria-invalid"); el.removeAttribute("aria-describedby"); }
    }
  };
  const save = h("button", { type: "button", "data-testid": "modal-save", text: TEXT.save });
  const remove = h("button", { type: "button", "data-testid": "modal-remove", text: TEXT.remove });
  const check = h("button", { type: "button", "data-testid": "modal-check", text: TEXT.check });
  const wip = h("p", { class: "wip-note", "data-testid": "modal-wip", hidden: true },
    h("span", { class: "wip-badge", text: TEXT.wip }), " ", TEXT.paused);
  const intro = h("div", {}, h("p", { text: TEXT.intro }), h("p", { "data-testid": "modal-guide", text: TEXT.guide }));
  const deployment = h("div", {}, h("p", { text: TEXT.deploy }), h("code", { "data-testid": "modal-deploy", text: DEPLOY_COMMAND }),
    h("p", { "data-testid": "modal-deploy-where", text: TEXT.deployWhere }));
  const card = h("section", { class: "pf-card", "data-testid": "modal-creds" },
    h("h2", { text: TEXT.title }), wip, intro,
    status, result,
    h("label", {}, TEXT.id, " ", id), h("label", {}, TEXT.secret, " ", secret), fieldError, save, remove, check, note,
    deployment);
  slot.replaceChildren(card);
  // Closed until the server has answered that BYOK is on, so a click can never send a token while it is paused.
  let open = false;
  const setOpen = (value) => {
    open = value;
    for (const el of [id, secret, save, check]) el.disabled = !value;
  };
  setOpen(false);

  const paint = (doc) => {
    status.textContent = doc && doc.key_unavailable === true ? TEXT.keyDown // the server's fault, never "add a token"
      : hasOwnModal(doc) ? TEXT.setAs(doc.token_id_hint) : doc && doc.expired ? TEXT.expired : TEXT.notSet;
    result.textContent = hasOwnModal(doc) ? checkText(doc.check) : "";
    remove.hidden = check.hidden = !hasOwnModal(doc);
    if (!doc) return; // no answer: stays as it was
    const paused = doc.paused === true;
    setOpen(!paused);
    wip.hidden = !paused;
    intro.hidden = deployment.hidden = paused;
    if (paused) check.hidden = true;
  };
  const load = async () => {
    const out = await call("GET", MODAL_URL, undefined, QUIET);
    if (!live) return null;
    if (out.status === 401 || out.status === 404) { slot.replaceChildren(); return null; } // signed out meanwhile, or sign-in off
    paint(out.ok ? out.body : null);
    return out.ok ? out.body : null;
  };
  save.addEventListener("click", async () => {
    if (!open) return;
    const out = await call("PUT", MODAL_URL, { token_id: id.value.trim(), token_secret: secret.value.trim() }, QUIET);
    if (!live) return;
    secret.value = ""; // the secret leaves the page with the request, never stays in the field
    if (out.ok) { id.value = ""; markFields(""); paint(out.body); note.textContent = TEXT.saved; return; }
    const said = [400, 429, 503].includes(out.status) && out.body && out.body.message ? out.body.message : TEXT.failed;
    if (out.status === 400) { note.textContent = ""; markFields(said); return; } // the fields were refused
    markFields("");
    note.textContent = said;
  });
  remove.addEventListener("click", async () => {
    const out = await call("DELETE", MODAL_URL, {}, QUIET);
    if (!live) return;
    if (out.ok) { paint(out.body); note.textContent = TEXT.removed; } else note.textContent = TEXT.failed;
  });
  check.addEventListener("click", async () => {
    if (!open) return;
    const before = (await load())?.check?.checked_at ?? null;
    const out = await call("POST", CHECK_URL, {}, QUIET);
    if (!live) return;
    if (!out.ok) { note.textContent = (out.body && out.body.message) || TEXT.failed; return; }
    note.textContent = TEXT.checking;
    for (let i = 0; i < POLLS && live; i += 1) {
      await wait(POLL_MS);
      const doc = await load();
      if (doc && doc.check && doc.check.checked_at !== before) { note.textContent = ""; return; }
    }
  });
  load().catch(() => {});
  return () => { live = false; slot.replaceChildren(); };
}
