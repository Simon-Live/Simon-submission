// Glue for "My reference" on the result page (docs/specs/my-reference.md): says which reference the take used and, for the
// owner, lets them mark this take as their reference, replace it or remove it. Signed-out viewers and takes that are not
// theirs see the note only. Opt-in: nothing is stored in the browser.
import { el } from "./score.js";
import { call } from "./me-api.js";
import { fetchMe } from "./auth.js";
import { TEXT, referenceNote, actionFor, isMine, isGroupTake, approvedNotice, suggestionNotice } from "./model/my-reference.js";

const QUIET = { expectStatus: [401, 404, 409, 422, 429] }; // normal answers of this feature, not anomalies

function button(testid, text, onClick) {
  const b = el("button", { type: "button", class: "sr-btn", "data-testid": testid, text });
  b.addEventListener("click", onClick);
  return b;
}

/** The result page slot. `ctx` = { job, pid, jobRecord }. */
export function mountMyReference(slot, ctx) {
  if (!ctx || !ctx.job || ctx.job === "fixture" || ctx.pid) return undefined;
  const note = referenceNote(ctx.jobRecord);
  if (!note) return undefined;
  const box = el("section", { class: "sr-reference", "data-testid": "reference", "data-reference": note.kind });
  box.append(el("p", { class: "sr-reference-note", "data-testid": `reference-${note.kind}`, text: note.text }));
  slot.append(box);
  let live = true;
  const entry = ctx.jobRecord.entry_id;
  const mine = isMine(ctx.jobRecord) && !isGroupTake(ctx.jobRecord);   // only the maker of a solo take can mark it
  const status = el("p", { class: "sr-reference-status", role: "status", "data-testid": "reference-status" });
  const row = el("div", { class: "sr-reference-actions" });
  const approval = el("p", { class: "sr-reference-approval", "data-testid": "reference-approval", hidden: true });   // a teacher's approval (ADR-0019)
  const offer = el("div", { class: "sr-reference-offer", "data-testid": "reference-suggestion", hidden: true });
  box.append(approval, offer, row, status);
  let waiting = null;
  const paintOffer = () => {
    offer.replaceChildren();
    offer.hidden = !waiting;
    if (!waiting) return;
    offer.append(el("p", { text: suggestionNotice(waiting.approved, waiting.date) }),
      button("reference-accept", TEXT.accept, () => decide("accept")), button("reference-decline", TEXT.decline, () => decide("decline")));
  };
  async function decide(action) {
    const res = await call("POST", "api/me/reference/suggestion", { entry_id: entry, action }, QUIET);
    if (!live) return;
    if (!res.ok) { status.textContent = (res.body && res.body.message) || TEXT.failed; return; }
    waiting = null;
    paintOffer();
    if (action === "accept") { paint(res.body.reference); status.textContent = TEXT.accepted; } else status.textContent = TEXT.declined;
  }
  const paint = (current) => {
    approval.hidden = !(current && current.approved);
    approval.textContent = current && current.approved ? approvedNotice(current.approved, current.job_id === ctx.job) : "";
    row.replaceChildren();
    const mode = actionFor(ctx.job, current);
    status.textContent = mode === "current" ? TEXT.marked : "";
    if (mode !== "current") row.append(button("reference-mark", mode === "mark" ? TEXT.mark : TEXT.replace, () => save()));
    if (current) row.append(button("reference-remove", TEXT.remove, () => drop()));
  };
  async function save() {
    const res = await call("POST", "api/me/reference", { job_id: ctx.job }, QUIET);
    if (!live) return;
    if (res.ok) { paint(res.body.reference); status.textContent = TEXT.confirm; } else status.textContent = (res.body && res.body.message) || TEXT.failed;
  }
  async function drop() {
    const res = await call("POST", "api/me/reference/remove", { entry_id: entry }, QUIET);
    if (!live) return;
    if (res.ok) { paint(null); status.textContent = TEXT.removed; } else status.textContent = (res.body && res.body.message) || TEXT.failed;
  }
  (async () => {
    if (!mine || !entry) return;
    const me = await fetchMe().catch(() => null);
    if (!me || !me.signedIn || !live) return;
    const got = await call("GET", `api/me/reference?entry=${encodeURIComponent(entry)}`, undefined, QUIET);
    if (live && got.ok) { waiting = got.body.suggestion || null; paintOffer(); paint(got.body.reference); }
  })();
  return () => { live = false; };
}
