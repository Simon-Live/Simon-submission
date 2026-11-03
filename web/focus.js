// "Last time you worked on" on the follow screen and the cue's result line on the result page (TICKET-223 AC-1, AC-2).
// Glue only: signed out, nothing is asked, so no owner-only request and no 401 reaches the console.
import { call } from "./me-api.js";
import { fetchMe } from "./auth.js";
import { ensureCss } from "./ui.js";
import { focusUrl, focusView, afterView } from "./model/focus.js";
import { renderFocusLine, renderFocusResult } from "./views/focus.js";

const CSS = ["theme/history.css", "data-history-css"];
const NORMAL = { expectStatus: [401, 404] };

async function read(entryId, jobId) {
  if (!entryId || !(await fetchMe()).signedIn) return null; // nobody signed in: no request at all
  const res = await call("GET", focusUrl(entryId, jobId), undefined, NORMAL);
  return res.status === 200 && res.body ? res.body : null;
}

/** Fills `box` with the line before a take (follow screen); returns true when a line was drawn. `alive()` is false once the screen is gone. */
export async function mountFocus(box, entryId, alive = () => true) {
  const view = focusView(await read(entryId));
  if (!view || !alive()) return false;
  ensureCss(...CSS);
  renderFocusLine(box, view);
  return true;
}

/** Appends the result line for the take `jobId` to `box` (result page); returns true when a line was drawn. */
export async function addFocusResult(box, entryId, jobId) {
  if (!jobId) return false;
  const doc = await read(entryId, jobId);
  const view = afterView(doc, focusView(doc));
  if (!view) return false;
  ensureCss(...CSS);
  renderFocusResult(box, view);
  return true;
}
