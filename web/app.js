// Hash router. Relative URLs only; each screen returns a cleanup function.
import { getAnalysis, getReplay, getFixtureResult, getJob, ApiError } from "./api.js";
import { mountCatalog } from "./catalog.js";
import { mountWatch } from "./watch.js";
import { mountRecord } from "./record.js";
import { mountFollow } from "./follow.js";
import { mountJob } from "./job.js";
import { mountGroupResult } from "./group-result.js";
import { h, clear, stateBlock, linkButton } from "./ui.js";
import { showLoading } from "./progress.js";

const root = document.getElementById("app");
let cleanup = () => {};

/**
 * Result data for `#/result/<job>` and `#/result/<job>/<pid>`; the replay may be missing (422) and the screen
 * copes. `record` is the job record (follower labels, entry to go back to); null when it cannot be read.
 */
async function loadResult(job, pid) {
  if (job === "fixture") return getFixtureResult();
  const [analysis, record] = await Promise.all([getAnalysis(job, pid), getJob(job).catch(() => null)]);
  const replay = await getReplay(job, pid).catch(() => null);
  return { analysis, replay, record };
}

function mountResultRoute(el, job, pid) {
  let live = true;
  showLoading(el, "Loading your result");
  Promise.all([loadResult(job, pid), import("./result.js")]).then(([data, mod]) => {
    if (!live) return;
    clear(el);
    mod.mountResult(el, { analysis: data.analysis, replay: data.replay, job, record: data.record, pid });
  }).catch((err) => {
    if (!live) return;
    const missing = err instanceof ApiError && err.status === 404;
    clear(el).append(stateBlock("not-found",
      missing ? "This result is not found" : "The result did not load",
      missing ? "Results are kept for 7 days." : err.message,
      linkButton("#/", "Back to movements", "back-home")));
  });
  return () => { live = false; };
}

export const ROUTES = [
  [/^$/, (el) => mountCatalog(el)],
  [/^watch\/([^/]+)$/, (el, m) => mountWatch(el, m[1])],
  [/^record$/, (el) => mountRecord(el)],
  [/^follow\/([^/]+)$/, (el, m) => mountFollow(el, m[1])],
  [/^job\/([^/]+)$/, (el, m) => mountJob(el, m[1])],
  [/^result\/([^/]+)$/, (el, m) => mountResultRoute(el, m[1])],
  [/^result\/([^/]+)\/([^/]+)$/, (el, m) => mountResultRoute(el, m[1], m[2])],
  [/^group\/([^/]+)$/, (el, m) => mountGroupResult(el, m[1])],
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
  document.body.dataset.route = location.hash || "#/";
  cleanup = hit.mount(root, hit.params) || (() => {});
  window.scrollTo(0, 0);
}

window.addEventListener("hashchange", show);
show();
