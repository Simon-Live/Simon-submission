// Mount points the result screen leaves for modules another session owns (docs/specs/result-redesign-additions.md R6,
// contracts C2 and C2b). The modules are glue entries at the web/ root (web/voice.js, second-opinion.js, export.js,
// narration.js); each is loaded on demand, and a missing or failing module leaves its slot empty and the screen as it
// was. View only: no fetch, no storage.
import { h } from "../ui.js";

/** The empty slot under one coaching row: `data-fault-index` indexes analysis.faults (and phrasing.faults). */
export const voiceSlot = (index, atS) => h("div", {
  class: "sr-voice-slot", "data-testid": "voice-slot", "data-fault-index": index, "data-at-s": atS ?? false,
});

/** The one empty section a second look at the take goes into; it follows the coaching rows. */
export const secondOpinionSlot = () => h("section", { class: "sr-second-opinion", "data-testid": "second-opinion-slot" });

/** The empty section the owner's corrected-pose image and blind referee go into (corrected-card.js; hidden until there is something to show). */
export const correctedSlot = () => h("section", { class: "sr-corrected", "data-testid": "corrected-slot", hidden: true });

/** The empty section "Your takes over time" goes into (history.js; stays empty unless a student is signed in). */
export const historySection = () => h("section", { class: "sr-history", "data-testid": "history-slot" });

/** The empty slot the "Keep this take" button goes into (auth.js; stays empty unless a student is signed in). */
export const keepTakeSlot = () => h("div", { class: "sr-keep", "data-testid": "keep-take-slot" });

/** The empty slot next to Retry and Replay that the export button goes into. */
export const exportSlot = () => h("div", { class: "rs-export", "data-testid": "export-slot" });

const quiet = (p) => p.catch(() => {});

/**
 * Load the other session's modules once the coaching rows exist.
 * @param rootEl the result screen's root (holds every voice slot and the second-opinion section)
 * @param ctx {jobId, analysis, video, seek, entryId, owns, narration}: `video` is the follower's <video> or null; `seek(t)`
 *   moves the video and the 3D view to `t` seconds and brings them into view; `entryId` is the movement's catalog id or
 *   null. `owns` false (the result answer's attribution.mine): the viewer does not own the take, so no owner-only request
 *   (since last time) is sent; `narration` false: the movement has no narration, so none is asked for.
 */
export function mountLaneModules(rootEl, { jobId, analysis, video = null, seek, entryId = null, owns = true, narration = true, trainer = null }) {
  const ctx = { jobId, analysis, video, seek };
  if (rootEl.querySelector('[data-testid="voice-slot"]')) quiet(import("../voice.js").then((m) => m.mountVoiceSlots(rootEl, ctx)));
  const section = rootEl.querySelector('[data-testid="second-opinion-slot"]');
  if (section) quiet(import("../second-opinion.js").then((m) => m.mountSecondOpinion(section, ctx)));
  const corrected = rootEl.querySelector('[data-testid="corrected-slot"]');
  if (corrected && owns && jobId !== "fixture") quiet(import("../corrected-card.js").then((m) => m.mountCorrectedCard(corrected, jobId)));
  const history = rootEl.querySelector('[data-testid="history-slot"]');
  if (history && entryId) quiet(import("../history.js").then((m) => m.mountHistory(history, { jobId: owns ? jobId : null, entryId, analysis, seek })));
  const keep = rootEl.querySelector('[data-testid="keep-take-slot"]');
  if (keep && jobId !== "fixture") quiet(import("../auth.js").then((m) => m.mountKeepTake(keep, jobId)));
  if (entryId && narration) quiet(import("../narration.js").then((m) => m.mountNarration(rootEl, { entryId, trainer })));
}

/**
 * Fill the export slot (called again after the summary repaints, since the repaint makes a new slot).
 * Returns `stop()`: it ends the button's polling and forgets the job, also when the module is still loading.
 */
export function mountExport(slot, jobId) {
  let stopButton = null;
  let stopped = false;
  const modelOnly = slot && typeof slot.closest === "function" && slot.closest('[data-model-only="true"]'); // no video, so no export clip (model-only-take.md)
  if (slot && !modelOnly) quiet(import("../export.js").then((m) => m.mountExportButton(slot, jobId)).then((stop) => { stopButton = stop; if (stopped) stop(); }));
  return () => { stopped = true; if (stopButton) stopButton(); };
}
