// Follow (follower): the shared take flow with a mode picker and "Learn in sections". `#/follow/<id>`
import { getConfig, getEntry, ApiError } from "./api.js";
import { mountTakeFlow } from "./take-flow.js";
import { h, clear, stateBlock, linkButton } from "./ui.js";
import { showLoading } from "./progress.js";
import { MODES, effectiveMode, loadChoice, mountModePicker, modeCoaching, countdownFor, ensureStyles, lockedMode, takeMode } from "./modes.js";
import { getEntryLabels } from "./labels.js";
import { mountPractice } from "./practice.js";
import { watchChallenge } from "./follow-challenge.js";
import { consentBlock } from "./consent.js";
import { savedMode } from "./saved-mode.js";
import { mountEntryAuthor } from "./entry-author.js";
import { mountFocus } from "./focus.js";
import { langOffered, langExtra } from "./follow-lang.js";
import { rememberSignedOutTake } from "./takes-on.js"; // the takes this browser sent signed out (TICKET-327)

export { TAKE_ERROR } from "./take-flow.js";
export { currentLang, pickedLang, langOffered, langExtra } from "./follow-lang.js";

/**
 * `challengeId` (route `#/follow/<id>/c/<challenge>`) is sent with the take once the challenge is known to be open and
 * for this movement; the server checks it again. `mode` is sent only when the person chose one (stored choice or a
 * click): the default from the category sets the presets and is never sent as a choice (practice-and-modes.md).
 * TICKET-311: an entry's own kind (`rehab` tag, else category) decides instead: shown locked, sent whatever the bar says.
 */
export function mountFollow(root, id, challengeId = null) {
  let stop = () => {};
  let practice = null;
  let alive = true;
  const screen = h("section", { class: "screen" });
  root.append(screen);
  showLoading(screen, "Loading movement");

  Promise.all([getEntry(id), getConfig(), savedMode().catch(() => null), getEntryLabels(id).catch(() => null)]).then(([entry, cfg, saved, entryLabels]) => {
    if (!alive) return;
    ensureStyles();
    const eid = entry.id || id;
    const full = { ...entry, id: eid };
    const fixed = lockedMode(full, entryLabels && entryLabels.tags); // TICKET-311: the entry's kind decides, the picker is locked
    const picked = (MODES.includes(loadChoice()) ? loadChoice() : null) || saved; // a picked mode wins, then the profile's first saved mode (TICKET-231 AC-4)
    let chosen = takeMode(full, entryLabels && entryLabels.tags, picked);
    let mode = chosen || effectiveMode(full);
    const box = h("div", {});
    const coaching = h("div", { class: "mode-coaching", "data-testid": "mode-coaching" });
    const practiceBox = h("div", {});
    const focusBox = h("div", { "data-testid": "focus-slot" }); // "Last time you worked on", for a signed-in student with kept takes (TICKET-223)
    const offerLang = langOffered(cfg);
    const langSlot = h("div", { "data-testid": "lang-picker-slot" });
    const challengeNote = h("p", { class: "hint", role: "status", "data-testid": "follow-challenge", hidden: true });
    const taking = watchChallenge(challengeId, eid, challengeNote, () => alive); // the open challenge this take joins
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
    if (fixed) picker.lock();
    paintCoaching();
    clear(screen).append(
      h("p", { class: "crumb" }, h("a", { href: `#/watch/${encodeURIComponent(eid)}`, text: "Back to the movement" })),
      h("h1", { text: `Follow ${entry.name || eid}` }),
      mountEntryAuthor(eid, "follow-author", { credit: "follow-source" }),
      h("p", { class: "lede", text: "Do the movement once, from the front, with your whole body in view." }),
      focusBox,
      challengeNote, picker.el, coaching, ...(offerLang ? [langSlot] : []), practiceBox, consentBlock(), box);
    if (offerLang) import("./lang-picker.js").then((m) => m.mountLangPicker(langSlot)).catch(() => {}); // contract C4: another lane builds it
    practice = mountPractice(practiceBox, { entry: full, mode });
    mountFocus(focusBox, eid, () => alive).catch(() => {});
    stop = mountTakeFlow(box, {
      role: "follower", entryId: eid, entry: full, limits: cfg.limits,
      extra: () => ({ ...langExtra(cfg), ...(chosen ? { mode: chosen } : {}), ...(taking() ? { challenge_id: taking().id } : {}), ...practice.extra() }),
      onReference: (ref) => practice.attach(ref),
      countdownDefault: countdownFor(mode),
      onDone: (jobId) => { practice.markPending(jobId); rememberSignedOutTake(jobId, eid, entry.name).catch(() => {}); location.hash = `#/job/${jobId}`; }, // TICKET-327: listed on the watch page and Me
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
