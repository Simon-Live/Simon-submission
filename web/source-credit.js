// Glue for the source and licence credit (docs/specs/source-credit.md; TICKET-322): a slot that loads the credit of an
// entry or a take, draws the block when there is one, and gives the owner a small form to write it. A failed read
// draws nothing; the server decides who sees a credit and who may change it.
import { h, clear } from "./ui.js";
import { call } from "./me-api.js";
import * as model from "./model/source-credit.js";
import * as view from "./views/source-credit.js";

const { TEXT, readUrl, writeUrl, failText } = model;

/** The credit block of a source payload, or null when there is nothing to show. The one place the model and the view meet. */
export const creditBlock = (source, testid, lead = "") => view.creditBlock(model.creditView(source), TEXT, testid, lead);

const EXPECTED = [400, 401, 403, 404];

/** A slot for `kind` ("entry" or "take") and its id. `edit` false draws the credit only. `testid` names the block. */
export function mountSourceCredit(kind, id, testid, { edit = true, trainerClip = false } = {}) {
  const slot = h("div", { class: "src-slot", "data-testid": `${testid}-slot` });
  if (!id) return slot;
  let state = null; // { source, mine, licences }
  const paint = (open) => {
    clear(slot);
    const block = creditBlock(state.source, testid, trainerClip ? TEXT.trainerClip : "");
    if (block) slot.append(block);
    if (!(edit && state.mine)) return;
    const form = view.editForm({ kind, current: state.source, licences: state.licences, model, testid: `${testid}-edit`, onSave, onRemove });
    if (open) form.setAttribute("open", "");
    slot.append(form);
  };
  const redraw = (source) => {
    const open = slot.querySelector(`[data-testid="${testid}-edit"]`)?.getAttribute("open") != null;
    state = { ...state, source };
    paint(open);
  };
  async function send(body, done) {
    const res = await call("POST", writeUrl(kind, id), body, { expectStatus: EXPECTED });
    if (!res.ok) return { ok: false, message: failText(res) };
    redraw(res.body?.source || null);
    return { ok: true, message: done };
  }
  const onSave = (body) => send(body, TEXT.saved);
  const onRemove = () => send({}, TEXT.removed);
  call("GET", readUrl(kind, id), undefined, { expectStatus: [404] }).then((res) => {
    if (!res.ok || !res.body || typeof res.body !== "object") return;
    state = { source: res.body.source || null, mine: Boolean(res.body.mine), licences: Array.isArray(res.body.licences) ? res.body.licences : [] };
    paint(false);
  });
  return slot;
}
