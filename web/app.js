// Hash router. Relative URLs only; each screen returns a cleanup function.
import { installErrorCapture } from "./errors.js";
import { getAnalysis, getReplay, getTrainerVisibility, getFixtureResult, getJob, getEntry, entryFileUrl, routeName, ApiError } from "./api.js";
import { mountCatalog } from "./catalog.js";
import { mountWatch } from "./watch.js";
import { mountRecord } from "./record.js";
import { mountFollow } from "./follow.js";
import { mountJob } from "./job.js";
import { mountGroupResult } from "./group-result.js";
import { mountTeacher } from "./teacher.js";
import { h, clear, stateBlock, linkButton } from "./ui.js";
import { showLoading } from "./progress.js";
import { mountBuildStamp } from "./build.js";
import { isDebug, profile, showModes } from "./flags.js";
import { mountPendingList, mountPendingResume, mountPendingBanner } from "./pending-ui.js";
import { startPending } from "./pending-app.js";
import { mountShell } from "./shell.js";

installErrorCapture(); // uncaught errors and failed fetches reach the server log (observability.md)
const root = document.getElementById("app");
let cleanup = () => {};

/**
 * Result data for `#/result/<job>` and `#/result/<job>/<pid>`; the replay may be missing (422) and the screen
 * copes. `record` is the job record (follower labels, entry to go back to); null when it cannot be read.
 */
async function loadResult(job, pid) {
  if (job === "fixture") return getFixtureResult();
  const [analysis, record] = await Promise.all([getAnalysis(job, pid), getJob(job).catch(() => null)]);
  const [replay, trainerVisibility, trainerVideoUrl] = await Promise.all([
    getReplay(job, pid).catch(() => null), getTrainerVisibility(job), trainerVideoOf(record, pid)]);
  return { analysis, replay, record, trainerVisibility, trainerVideoUrl };
}

/** The trainer's original video for a follow take's result (side by side); null for a group take or an entry without one. */
async function trainerVideoOf(record, pid) {
  const id = !pid && record && record.kind === "follow" ? record.entry_id : null;
  if (!id) return null;
  const entry = await getEntry(id).catch(() => null);
  return entry && entry.video_uri ? entryFileUrl(entry.id || id, entry.video_uri) : null;
}

function mountResultRoute(el, job, pid) {
  let live = true;
  let handle = null;
  showLoading(el, "Loading your result");
  Promise.all([loadResult(job, pid), import("./result.js")]).then(([data, mod]) => {
    if (!live) return;
    clear(el);
    // TICKET-087: keep the handle, so leaving the screen stops its video and 3D clock
    mod.mountResult(el, { analysis: data.analysis, replay: data.replay, trainerVisibility: data.trainerVisibility, trainerVideoUrl: data.trainerVideoUrl, job, record: data.record, pid }).then((h) => {
      handle = h;
      // TICKET-159: "Delete this take" ends every real result (not the committed example)
      if (live && job !== "fixture") import("./delete-take.js").then((m) => live && m.mountDeleteTake(el, { job, group: Boolean(pid) })).catch(() => {});
    });
  }).catch((err) => {
    if (!live) return;
    const missing = err instanceof ApiError && err.status === 404;
    clear(el).append(stateBlock("not-found",
      missing ? "This result is not found" : "The result did not load",
      missing ? "Results are kept for 7 days." : err.message,
      linkButton("#/", "Back to movements", "back-home")));
  });
  return () => { live = false; if (handle) handle.destroy(); };
}

/** `#/challenge/<id>`: the leaderboard, loaded on first use. */
function mountChallengeRoute(el, id) {
  let stop = () => {};
  let live = true;
  import("./challenge.js").then((m) => { if (live) stop = m.mountChallenge(el, id); });
  return () => { live = false; stop(); };
}

/** `#/signin` and `#/signin/<token>`: opt-in sign-in, loaded on first use (identity.md). */
function mountSigninRoute(el, token) {
  let stop = () => {};
  let live = true;
  import("./auth.js").then((m) => { if (live) stop = m.mountSignin(el, token); }).catch(() => {});
  return () => { live = false; stop(); };
}

/** `#/me`: the account page, with the list of movements the student has takes of under "Your takes over time". */
function mountMeRoute(el) {
  const stops = [];
  let live = true;
  const account = h("div");
  const over = h("section", { class: "me-history", "data-testid": "me-history", hidden: true }, h("h2", { text: "Your takes over time" }));
  const list = h("div");
  over.append(list);
  el.append(account, over);
  (async () => {
    const auth = await import("./auth.js");
    if (!live) return;
    stops.push(auth.mountMe(account));
    if (!(await auth.fetchMe()).signedIn || !live) return; // signed out: the account page already says so
    const history = await import("./history.js");
    if (!live) return;
    over.hidden = false;
    stops.push(history.mountMyTakes(list));
  })().catch(() => {});
  return () => { live = false; stops.forEach((stop) => stop()); };
}

/** `#/me/<entry>`: one movement's takes over time, loaded on first use. */
function mountHistoryRoute(el, entryId) {
  let stop = () => {};
  let live = true;
  import("./history.js").then((m) => { if (live) stop = m.mountHistory(el, entryId); }).catch(() => {});
  return () => { live = false; stop(); };
}

export const ROUTES = [
  [/^$/, (el) => mountCatalog(el)],
  [/^watch\/([^/]+)$/, (el, m) => mountWatch(el, m[1])],
  [/^record$/, (el) => mountRecord(el)],
  [/^follow\/([^/]+)$/, (el, m) => mountFollow(el, m[1])],
  [/^follow\/([^/]+)\/c\/([^/]+)$/, (el, m) => mountFollow(el, m[1], m[2])], // a challenge taken (challenges.md)
  [/^job\/([^/]+)$/, (el, m) => mountJob(el, m[1])],
  [/^result\/([^/]+)$/, (el, m) => mountResultRoute(el, m[1])],
  [/^result\/([^/]+)\/([^/]+)$/, (el, m) => mountResultRoute(el, m[1], m[2])],
  [/^group\/([^/]+)$/, (el, m) => mountGroupResult(el, m[1])],
  [/^challenge\/([^/]+)$/, (el, m) => mountChallengeRoute(el, m[1])],
  [/^pending$/, (el) => mountPendingList(el)], // saved takes (offline-takes.md)
  [/^pending\/([^/]+)$/, (el, m) => mountPendingResume(el, m[1])],
  [/^teacher\/([^/]+)$/, (el, m) => mountTeacher(el, m[1])], // the followers of one movement (teacher-dashboard.md)
  [/^signin$/, (el) => mountSigninRoute(el)],
  [/^signin\/([^/]+)$/, (el, m) => mountSigninRoute(el, m[1])],
  [/^me$/, (el) => mountMeRoute(el)],
  [/^me\/([^/]+)$/, (el, m) => mountHistoryRoute(el, m[1])],
];

export function resolve(hash) {
  const path = hash.replace(/^#\/?/, "");
  for (const [re, mount] of ROUTES) {
    const m = re.exec(path);
    if (m) return { mount, params: m.map((p) => (p ? decodeURIComponent(p) : p)) };
  }
  return null;
}

function show() {
  try { cleanup(); } catch { /* a screen that failed to mount has nothing to clean */ }
  cleanup = () => {};
  clear(root);
  const hit = resolve(location.hash);
  if (!hit) {
    root.append(stateBlock("route-missing", "Page not found", "That address does not match a screen.", linkButton("#/", "Back to movements", "back-home")));
    return;
  }
  document.body.dataset.route = routeName(location.hash) || "#/"; // the name only: a sign-in token or job id is never kept here (observability.md)
  cleanup = hit.mount(root, hit.params) || (() => {});
  window.scrollTo(0, 0);
}

profile(); // `?profile=submission` is read here before any screen and kept (flags.js)
window.addEventListener("hashchange", show);
const kindHost = document.getElementById("kind-switch");
kindHost.hidden = !showModes(); // the submission profile hides the Exercise / Dance / Rehab choice with the other modes
mountShell({ switchHost: kindHost });
show();
if (isDebug()) mountBuildStamp(document.getElementById("build")); // the build line shows only with ?debug=1
// Saved takes: drop expired ones, send what is waiting, and show the banner on every screen (offline-takes.md).
import("./auth.js").then((m) => m.mountAuthLink(document.getElementById("auth-link"))).catch(() => {}); // the header link, only when sign-in is on
startPending().then((pending) => mountPendingBanner(document.getElementById("pending"), pending)).catch(() => {});
