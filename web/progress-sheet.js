// Glue of the progress sheet (docs/specs/progress-sheet.md, TICKET-283): the one place that joins the model
// (model/progress-sheet.js), the routes and the view (views/progress-sheet.js). The owner's page is `#/me/<entry>/progress`;
// a shared sheet is drawn by `#/shared/<token>` through `renderShared`. Signed out, the page asks auth only through the
// sheet route itself (401) and nothing else in the app reads this module, so every anonymous flow is unchanged.
import { ensureCss, h, linkButton, stateBlock } from "./ui.js";
import { call } from "./me-api.js";
import * as model from "./model/progress-sheet.js";
import { renderSheet, shareControls } from "./views/progress-sheet.js";

const css = () => ensureCss("theme/progress-sheet.css", "data-progress-sheet-css");
const T = model.TEXT;
const linkOf = (token) => `${location.origin}${location.pathname}#/shared/${token}`;

/** A share snapshot of kind `progress_sheet`, drawn by the viewer page. Returns `{stop()}`. */
export function renderShared(el, snap) {
  css();
  el.classList.add("ps"); // the print rules print only the sheet
  return renderSheet(el, snap, model);
}

async function copyText(text) {
  try { await navigator.clipboard.writeText(text); return true; } catch { return false; }
}

/** `#/me/<entry>/progress`. Returns the cleanup function. */
export function mountProgressSheet(container, entryId) {
  css();
  let live = true;
  let drawn = { stop() {} };
  const page = h("section", { class: "screen ps", "data-testid": "ps-page" }, h("p", { "data-testid": "ps-loading", text: T.loading }));
  container.append(page);
  const back = () => linkButton(model.historyHash(entryId), T.back, "ps-back");
  const on = {
    share: async () => {
      const res = await call("POST", "api/shares", model.shareBody(entryId));
      return res.status === 201 && res.body ? { link: linkOf(res.body.token), id: res.body.id } : null;
    },
    remove: async (id) => (await call("DELETE", model.deleteUrl(id), {}, { expectStatus: [404] })).status === 200,
    copy: copyText,
  };
  (async () => {
    const res = await call("GET", model.sheetUrl(entryId), undefined, { expectStatus: [401, 404] });
    if (!live) return;
    if (res.status === 200 && res.body) {
      const programme = `${location.origin}${location.pathname}${model.programmeHash(entryId)}`;
      drawn = renderSheet(page, res.body, model, [shareControls(T, on, programme), back()]);
    } else if (res.status === 401) {
      page.replaceChildren(stateBlock("ps-signed-out", T.heading, T.signIn, linkButton("#/signin", T.signInLink, "ps-signin")));
    } else if (res.status === 404) {
      page.replaceChildren(stateBlock("ps-empty", T.emptyTitle, T.emptyBody, back()));
    } else {
      page.replaceChildren(stateBlock("ps-error", T.heading, T.failed, back()));
    }
  })();
  return () => { live = false; drawn.stop(); };
}

/** The "Progress sheet" link on the history page, for a movement with a take in rehab mode. Null otherwise. */
export function historyLink(doc, entryId) {
  return model.offersSheet(doc) ? linkButton(model.pageHash(entryId), T.historyLink, "ps-history-link") : null;
}
