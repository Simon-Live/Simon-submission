// Follow (follower): the shared take flow with a mode picker and "Learn in sections". `#/follow/<id>`
import { getConfig, getEntry, ApiError } from "./api.js";
import { mountTakeFlow } from "./take-flow.js";
import { h, clear, stateBlock, linkButton } from "./ui.js";
import { showLoading } from "./progress.js";
import { MODES, effectiveMode, loadChoice, mountModePicker, modeCoaching, countdownFor, ensureStyles } from "./modes.js";
import { mountPractice } from "./practice.js";
import { getChallenge } from "./challenge-core.js";

export { TAKE_ERROR } from "./take-flow.js";

/**
 * `challengeId` (route `#/follow/<id>/c/<challenge>`) is sent with the take once the challenge is known to be open and
 * for this movement; the server checks it again. `mode` is sent only when the person chose one (stored choice or a
 * click): the default from the category sets the presets and is never sent as a choice (practice-and-modes.md).
 */
export function mountFollow(root, id, challengeId = null) {
  let stop = () => {};
  let practice = null;
  let alive = true;
  const screen = h("section", { class: "screen" });
  root.append(screen);
  showLoading(screen, "Loading movement");

  Promise.all([getEntry(id), getConfig()]).then(([entry, cfg]) => {
    if (!alive) return;
    ensureStyles();
    const eid = entry.id || id;
    const full = { ...entry, id: eid };
    let mode = effectiveMode(full);
    let chosen = MODES.includes(loadChoice()) ? loadChoice() : null;
    let taking = null; // the open challenge this take joins
    const box = h("div", {});
    const coaching = h("div", { class: "mode-coaching", "data-testid": "mode-coaching" });
    const practiceBox = h("div", {});
    const challengeNote = h("p", { class: "hint", role: "status", "data-testid": "follow-challenge", hidden: true });
    if (challengeId) {
      getChallenge(challengeId).then((ch) => {
        if (!alive || ch.ended || ch.entry_id !== eid) return;
        taking = ch;
        challengeNote.textContent = `You are taking the challenge: ${ch.title}. Your score can join its board.`;
        challengeNote.hidden = false;
      }).catch(() => {});
    }
    const paintCoaching = () => { coaching.dataset.mode = mode; coaching.replaceChildren(...modeCoaching(mode)); };
    const picker = mountModePicker({
      value: mode, testid: "follow-mode",
      onChange: (next) => {
        mode = next;
        chosen = next;
        paintCoaching();
        if (practice) practice.setMode(mode);
        if (stop.setCountdownDefault) stop.setCountdownDefault(countdownFor(mode));
      },
    });
    paintCoaching();
    clear(screen).append(
      h("p", { class: "crumb" }, h("a", { href: `#/watch/${encodeURIComponent(eid)}`, text: "Back to the movement" })),
      h("h1", { text: `Follow ${entry.name || eid}` }),
      h("p", { class: "lede", text: "Do the movement once, from the front, with your whole body in view." }),
      challengeNote, picker.el, coaching, practiceBox, box);
    practice = mountPractice(practiceBox, { entry: full, mode });
    stop = mountTakeFlow(box, {
      role: "follower", entryId: eid, entry: full, limits: cfg.limits,
      extra: () => ({ ...(chosen ? { mode: chosen } : {}), ...(taking ? { challenge_id: taking.id } : {}), ...practice.extra() }),
      onReference: (ref) => practice.attach(ref),
      countdownDefault: countdownFor(mode),
      onDone: (jobId) => { practice.markPending(jobId); location.hash = `#/job/${jobId}`; },
    });
  }).catch((e) => {
    const missing = e instanceof ApiError && e.status === 404;
    clear(screen).append(stateBlock("not-found",
      missing ? "This movement is not in the catalog." : "The movement did not load",
      missing ? "Pick another one from the list." : e.message,
      linkButton("#/", "Back to movements", "back-home")));
  });
  return () => { alive = false; stop(); if (practice) practice.destroy(); };
}
