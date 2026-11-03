// The class handout at `#/teacher/<entry>/handout` (docs/specs/handout.md): glue between the API, the model and the
// view. The author route answers 404 for an entry its owner keeps to "only me", so no handout is made for it.
import { getEntry } from "./api.js";
import { call } from "./me-api.js";
import { h } from "./ui.js";
import { followUrl, handoutView, HANDOUT_TEXT } from "./model/handout.js";
import { authorUrl } from "./model/teacher.js";
import { renderHandout, renderHandoutError } from "./views/handout.js";

/** @returns cleanup */
export function mountHandout(container, entryId) {
  let live = true;
  const screen = h("section", { class: "screen" }, h("p", { "data-testid": "loading", text: HANDOUT_TEXT.loading }));
  container.append(screen);
  (async () => {
    const [shown, entry] = await Promise.all([call("GET", authorUrl(entryId), undefined, { expectStatus: [404] }), getEntry(entryId).catch((err) => err)]);
    if (!live) return;
    if (!shown.ok || entry instanceof Error) {
      renderHandoutError(screen, shown.status === 404 || entry?.status === 404);
      return;
    }
    renderHandout(screen, handoutView(entryId, entry?.name, followUrl(entryId)), () => window.print());
  })();
  return () => { live = false; };
}
