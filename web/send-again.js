// TICKET-290: on a failed job's page, "Send it again" when this browser still keeps the recording of that job
// (pending-keep.js). Nothing shows when it does not. The engine is injected so the DOM test drives it directly.
import { h } from "./ui.js";
import { KEEP_TEXT } from "./pending-keep.js";

export const SEND_AGAIN_TEXT = {
  kept: "Your recording is still on this device.",
  sending: "Sending",
  waiting: "Saved on this device. It is sent when the app is back.",
};

/** The kept take of job `jobId`: at "sent" or "job_failed" with that job, or null. */
export const findKept = (records, jobId) =>
  (records || []).find((r) => r && r.job === jobId && (r.stage === "sent" || r.stage === "job_failed")) || null;

/**
 * Put "Send it again" in `slot` (first) when the engine keeps the recording of `jobId`.
 * @param opts.engine () => Promise<pending engine>   @param opts.go (newJobId) => void, opens the new job
 * @returns stop()
 */
export function mountSendAgain(slot, jobId, { engine, go = (job) => { location.hash = `#/job/${encodeURIComponent(job)}`; } } = {}) {
  let live = true;
  Promise.resolve(engine ? engine() : import("./pending-app.js").then((m) => m.getPending())).then(async (p) => {
    const rec = live && p && p.listKept ? findKept(await p.listKept(), jobId) : null;
    if (!live || !rec) return;
    const note = h("p", { class: "hint", "data-testid": "send-again-note", role: "status", text: SEND_AGAIN_TEXT.kept });
    const btn = h("button", { type: "button", class: "btn primary block", "data-testid": "send-again", text: KEEP_TEXT.sendAgain });
    btn.addEventListener("click", async () => {
      btn.disabled = true;
      btn.textContent = SEND_AGAIN_TEXT.sending;
      const out = await p.sendAgain(rec.id).catch(() => null);
      if (!live) return;
      const fresh = out && out.record;
      if (fresh && fresh.job) { go(fresh.job); return; }
      if (fresh && fresh.stage === "people_ready") { location.hash = `#/pending/${encodeURIComponent(fresh.id)}`; return; }
      note.textContent = fresh && fresh.stage === "refused" ? `${(fresh.last_error && fresh.last_error.message) || ""} ${KEEP_TEXT.refusedKept}`.trim()
        : SEND_AGAIN_TEXT.waiting;
      btn.hidden = true;
      slot.append(h("a", { class: "btn secondary block", href: "#/pending", "data-testid": "send-again-saved", text: "See saved takes" }));
    });
    slot.prepend(note, btn);
  }).catch(() => {});
  return () => { live = false; };
}
