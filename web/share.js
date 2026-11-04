// Glue for share links (TICKET-233): the one place that joins the share model (model/share.js) to the share views.
// The views import nothing from the model; routes and pages import this file and get the views with the model injected.
import * as shareModel from "./model/share.js";
import { bylines } from "./model/attribution.js";
import * as list from "./views/share-list.js";
import * as action from "./views/share.js";
import * as viewer from "./views/shared.js";
import * as resultShare from "./views/share-prompt.js";
import { renderShared as renderSheet } from "./progress-sheet.js";
import { resultWarnings, WARNING_TITLE } from "./result.js";
import { shownScoreDisplay } from "./score-display.js";

/** The share model plus the attribution wording and the progress sheet (TICKET-283), injected into every share view.
 * A shared take's warnings are the result screen's own (`resultWarnings`, `WARNING_TITLE` in web/result.js) and its unit
 * is the result page's own, points (`shownScoreDisplay`, TICKET-372). The hooks read result.js's bindings
 * when called, never while the modules load (result.js loads this file with a dynamic import). */
const model = { ...shareModel, bylines, renderSheet,
  warningsOf: (analysis) => resultWarnings(analysis), warningTitle: () => WARNING_TITLE, scoreDisplay: () => shownScoreDisplay() };
/** The injected hooks, read by tests/part7/share-score-cap.dom.test.mjs. */
export const shareHooks = model;

/** The result page "Share this result" flow: `(slot, ctx)`, `ctx.trigger` being the action row's button. */
export const mountShareAction = (slot, ctx) => resultShare.mountResultShare(slot, ctx, model);
/** The history page Share button: `(container, entryId)`; its preview is the server's snapshot. */
export const mountReportShare = (container, entryId) => action.mountReportShare(container, entryId, model);
/** "Your share links" with Revoke buttons: `(el, opts)`; `opts.signedIn` is the caller's auth/me answer when it has one. */
export const mountShareList = (el, opts) => list.mountShareList(el, model, opts);
/** `#/shared/<token>`: `(el, token)`. */
export const mountShared = (el, token) => viewer.mountShared(el, token, model);
