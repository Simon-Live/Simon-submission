// "Show only my 3D model" (docs/specs/model-default.md AC-MD10 to AC-MD12): a per-account choice kept with the profile
// (`model_only_view` of api/me/profile), next to the default model on the Me page. When it is on and the account has a
// default model, the follow capture and the result (its compare and video views) show no video of the person; the
// trainer's video stays. The upload is still stored as today, because Part 2 needs it to measure the take.
import { h } from "./ui.js";
import { call } from "./me-api.js";
import { loadServerDefault } from "./model-default.js";
import { PROFILE_URL, isChoiceId } from "./model/model-default.js";
import { soloHandle } from "./result-stage.js";
import { drawSoloVideo } from "./views/result-stage.js";

export const FIELD = "model_only_view";

export const TEXT = {
  label: "Show only my 3D model",
  help: "Your follow and result screens show your default 3D model instead of your camera video. The trainer's video still shows. Simon still keeps the video you record, because it is needed to measure your movement.",
  needsDefault: "Set a default model above for this to take effect.",
  saved: "Saved.",
  saveFailed: "This choice did not save. Try again.",
  trainerVideo: "The trainer's video",
  standIn:"Your camera is on. Only your 3D model is shown, on your result.",
};

/** On only when the profile answer has the switch on and names a default model. */
export const modelOnlyViewOn = (body) => Boolean(body && body[FIELD] === true && isChoiceId(body.default_model_id));

/** The signed-in account's choice, for the follow page; false signed out, with sign-in off or on any failure. */
export async function loadModelOnlyView(callImpl = call) {
  const server = await loadServerDefault(callImpl);
  return server.signedIn === true && server.modelOnlyView === true;
}

/** The follower video address a result may use: none when the choice is on. */
export const ownVideoUrl = (on, url) => (on ? null : url);

/**
 * The result's Videos view with the choice on: the trainer's video alone (no video of the person), added to the stage
 * (`stageCtl` of result-stage.js) and removed again if it fails to load. Returns the solo video handle.
 */
export function mountTrainerOnlyVideo(host, url, stageCtl) {
  const side = drawSoloVideo(host, url, { label: TEXT.trainerVideo, testid: "stage-trainer-video" });
  stageCtl.addView("videos", soloHandle(side.video));
  side.video.addEventListener("error", () => stageCtl.removeView("videos"), { once: true });
  return side;
}

/** The line the follow capture shows in place of the person's own videos (capture.js `hideOwn`, AC-MD11). */
export const standInLine = () => h("p", { class: "cam-text", "data-testid": "model-only-view-stand-in", text: TEXT.standIn });

/** True for a take whose owner had the choice on when it was sent (the job record's stamp, AC-MD12). */
export const stampedModelOnly = (record) => Boolean(record && record[FIELD] === true);

/**
 * The switch on the Me page, signed in only, in `host`. `initial` is the profile answer (or null). Saving sends
 * `PUT api/me/profile {model_only_view}`. Returns {el, input}.
 */
export function mountModelOnlySetting(host, { initial = null, callImpl = call } = {}) {
  const input = h("input", { type: "checkbox", id: "model-only-view", class: "pf-check", "data-testid": "model-only-view-toggle", "aria-describedby": "model-only-view-help" });
  input.checked = Boolean(initial && initial[FIELD] === true);
  const help = h("p", { class: "pf-hint", id: "model-only-view-help", "data-testid": "model-only-view-help", text: TEXT.help });
  const needs = h("p", { class: "pf-hint", "data-testid": "model-only-view-needs-default", text: TEXT.needsDefault });
  needs.hidden = Boolean(initial && isChoiceId(initial.default_model_id));
  const note = h("p", { class: "pf-note", role: "status", "aria-live": "polite", "data-testid": "model-only-view-note", text: "" });
  // the same row as the profile's privacy switches (views/profile.js `tick`, theme/profile.css `.pf-tick`)
  const el = h("div", { class: "pf-tick", "data-testid": "model-only-view" }, input,
    h("div", {}, h("label", { class: "pf-tick-text", for: "model-only-view", text: TEXT.label }), help, needs, note));
  input.addEventListener("change", async () => {
    const want = input.checked === true;
    const out = await callImpl("PUT", PROFILE_URL, { [FIELD]: want }).catch(() => ({ ok: false }));
    if (!out || !out.ok) input.checked = !want;
    note.textContent = out && out.ok ? TEXT.saved : TEXT.saveFailed;
  });
  host.append(el);
  return { el, input };
}
