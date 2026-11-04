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
import { mountHandout } from "./handout.js";
import { clear, stateBlock, linkButton } from "./ui.js";
import { showLoading } from "./progress.js";
import { mountBuildStamp } from "./build.js";
import { isDebug, profile } from "./flags.js";
import { mountPendingList, mountPendingResume, mountPendingBanner } from "./pending-ui.js";
import { startPending } from "./pending-app.js";
import { mountShell, mountTestServerBanner } from "./shell.js";
import { mountMePage, redirectToMe } from "./me-page.js";
import { mountFooter } from "./footer.js";
import { loadResultFor as loadChecked } from "./orphan-load.js";

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
  Promise.all([loadChecked(job, pid, loadResult), import("./result.js")]).then(([data, mod]) => {
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

/** `#/outbox`: the staging test mailbox, loaded on first use. */
function mountOutboxRoute(el) {
  let stop = () => {};
  let live = true;
  import("./outbox.js").then((m) => { if (live) stop = m.mountOutbox(el); }).catch(() => {});
  return () => { live = false; stop(); };
}

/** `#/me/<entry>`: one movement's takes over time, loaded on first use. */
function mountHistoryRoute(el, entryId) {
  let stop = () => {};
  let live = true;
  import("./history.js").then((m) => { if (live) stop = m.mountHistory(el, entryId); }).catch(() => {});
  return () => { live = false; stop(); };
}

/** `#/me/notes/<id>`: the trainer's page for one note request (TICKET-237), loaded on first use. */
function mountNoteRequestRoute(el, id) {
  let stop = () => {};
  let live = true;
  import("./notes.js").then((m) => { if (live) stop = m.mountNoteRequest(el, id); }).catch(() => {});
  return () => { live = false; stop(); };
}

/** `#/shared/<token>`: the public viewer of a share link, loaded on first use (share.md). */
function mountSharedRoute(el, token) {
  let stop = () => {};
  let live = true;
  import("./share.js").then((m) => { if (live) stop = m.mountShared(el, token); }).catch(() => {});
  return () => { live = false; stop(); };
}

/** `#/any-body/<job>`: one take on several body models at once, loaded on first use (any-body.md). */
function mountAnyBodyRoute(el, job) {
  let stop = () => {};
  let live = true;
  import("./any-body.js").then((m) => { if (live) stop = m.mountAnyBodyRoute(el, job); }).catch(() => {});
  return () => { live = false; stop(); };
}

/** `#/me/<entry>/progress`: the progress sheet of a measure-only home programme (TICKET-283), loaded on first use. */
function mountProgressRoute(el, entryId) {
  let stop = () => {};
  let live = true;
  import("./progress-sheet.js").then((m) => { if (live) stop = m.mountProgressSheet(el, entryId); }).catch(() => {});
  return () => { live = false; stop(); };
}

/** `#/me/all` and `#/me/recap`: across my movements and the monthly recap, loaded on first use. */
function mountRecapRoute(el, which, month) {
  let stop = () => {};
  let live = true;
  import("./recap.js").then((m) => { if (live) stop = which === "all" ? m.mountAcross(el) : m.mountRecap(el, month); }).catch(() => {});
  return () => { live = false; stop(); };
}

/** `#/impact` and `#/architecture`: the persona page and the diagrams, loaded on first use (impact-page.md). */
/** A business page (web/legal.js), loaded on first use like the other static pages. */
function mountLegalRoute(el, key) {
  let stop = () => {};
  let live = true;
  import("./legal.js").then((m) => { if (live) stop = m.mountLegal(el, key); }).catch(() => {});
  return () => { live = false; stop(); };
}

function mountLazy(el, file, name) {
  let stop = () => {};
  let live = true;
  import(file).then((m) => { if (live) stop = m[name](el); }).catch(() => {});
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
  [/^any-body\/([^/]+)$/, (el, m) => mountAnyBodyRoute(el, m[1])],
  [/^group\/([^/]+)$/, (el, m) => mountGroupResult(el, m[1])],
  [/^challenge\/([^/]+)$/, (el, m) => mountChallengeRoute(el, m[1])],
  [/^pending$/, (el) => mountPendingList(el)], // saved takes (offline-takes.md)
  [/^pending\/([^/]+)$/, (el, m) => mountPendingResume(el, m[1])],
  [/^teacher\/([^/]+)$/, (el, m) => mountTeacher(el, m[1])], // the followers of one movement (teacher-dashboard.md)
  [/^teacher\/([^/]+)\/handout$/, (el, m) => mountHandout(el, m[1])], // the printable class handout (handout.md)
  [/^signin$/, (el) => mountSigninRoute(el)],
  [/^signin\/([^/]+)$/, (el, m) => mountSigninRoute(el, m[1])],
  [/^outbox$/, (el) => mountOutboxRoute(el)],
  [/^shared\/([^/]+)$/, (el, m) => mountSharedRoute(el, m[1])],
  [/^me$/, (el) => mountMePage(el)], // the one Me page: account, profile, My 3D model, takes, share links (me-page.md)
  [/^me\/all$/, (el) => mountRecapRoute(el, "all")],
  [/^me\/recap(?:\?month=(\d{4}-\d{2}))?$/, (el, m) => mountRecapRoute(el, "recap", m[1])],
  [/^me\/notes\/([^/]+)$/, (el, m) => mountNoteRequestRoute(el, m[1])],
  [/^me\/([^/]+)\/progress$/, (el, m) => mountProgressRoute(el, m[1])],
  [/^me\/([^/]+)$/, (el, m) => mountHistoryRoute(el, m[1])],
  [/^impact$/, (el) => mountLazy(el, "./impact.js", "mountImpact")], // who Simon is for: persona cards (impact-page.md)
  [/^architecture$/, (el) => mountLazy(el, "./architecture.js", "mountArchitecture")], // the three diagrams of docs/ARCHITECTURE.md
  [/^(about|mission|safety|privacy|terms|accessibility|biometric|dmca|sub-processors)$/, (el, m) => mountLegalRoute(el, m[1])], // the business pages and legal stand-ins (model/legal.js)
  [/^whitepaper$/, (el) => mountLazy(el, "./whitepaper.js", "mountWhitepaper")], // the design blueprint, shown in the app (web/whitepaper.html)
  [/^notices$/, (el) => mountLazy(el, "./notices.js", "mountNotices")], // the open-source notices as a page (api/notices)
  [/^profile(?:\/.*)?$/, () => redirectToMe()], // the old profile address, and anything below it, opens the Me page
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
mountShell();
mountTestServerBanner(); // a test stand-in server says so in a banner (self-healing.md)
show();
if (isDebug()) mountBuildStamp(document.getElementById("build")); // the build line shows only with ?debug=1
mountFooter(document.getElementById("site-footer")); // the live version, links and credits on every screen (version-footer.md)
// Saved takes: drop expired ones, send what is waiting, and show the banner on every screen (offline-takes.md).
import("./auth.js").then((m) => m.mountAuthLink(document.getElementById("auth-link"))).catch(() => {}); // the header link, only when sign-in is on
startPending().then((pending) => mountPendingBanner(document.getElementById("pending"), pending)).catch(() => {});
