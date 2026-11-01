// "Your takes over time" (docs/specs/history-web.md, contract C-WEB): glue between the history routes (C-HTTP), the
// model (model/history.js) and the views (views/history.js). Opt-in: with nobody signed in every call answers 401 and
// the page, the list and the result slot stay empty or say so; nothing else in the app reads this module.
import { ensureCss } from "./ui.js";
import { call } from "./me-api.js";
import { fetchMe } from "./auth.js";
import {
  CONSENT_VERSION, historyUrls, keepPolling, pageView, plural, retryDelayMs, slotTitle, stateForStatus,
} from "./model/history.js";
import { renderHistoryPage, renderHistoryState, renderMyTakes, renderSlot } from "./views/history.js";

const CSS = ["theme/history.css", "data-history-css"];
const PAGE_OK = { expectStatus: [401, 404] }; // signed out, or nothing kept yet: the page says so, it is not an anomaly
const NONE_YET = { expectStatus: [404] }; // no copies kept yet, or no report made yet: a normal answer, not an anomaly

const get = (url, opts) => call("GET", url, undefined, opts);
const post = (url, data) => call("POST", url, data || {});
const isReport = (r) => r.status === 200 && r.body && typeof r.body === "object";

/** The page `#/me/<entry>`. Returns the cleanup function. */
function mountPage(container, entryId) {
  ensureCss(...CSS);
  let live = true;
  let timer = null;
  const screen = document.createElement("section");
  screen.className = "screen";
  const loading = document.createElement("p");
  loading.setAttribute("data-testid", "history-loading");
  loading.textContent = "Loading your takes";
  screen.append(loading);
  container.append(screen);
  const urls = historyUrls(entryId);
  let doc = null;
  let report = null;
  let ui = null;

  const draw = () => {
    ui = renderHistoryPage(screen, pageView(doc, entryId, report), { onRun: run, onConsent: setConsent });
  };
  const show = (res) => {
    report = res.body;
    ui.report(pageView(doc, entryId, report));
    ui.status("done", "");
    ui.busy(false);
  };
  const fail = (status) => {
    const s = stateForStatus(status);
    ui.status(s.kind, s.message);
    ui.busy(false);
  };
  // 202: ask again after Retry-After until the report is there or the wait runs out
  function poll(startedAt, delay) {
    timer = setTimeout(async () => {
      if (!live) return;
      const res = await get(urls.report, NONE_YET);
      if (!live) return;
      if (isReport(res)) return show(res);
      if (res.status === 202 && keepPolling(Date.now() - startedAt)) return poll(startedAt, retryDelayMs(res.retryAfter));
      if (res.status === 202) {
        ui.status("slow", "This is taking longer than usual. Leave the page open, or come back in a few minutes.");
        return ui.busy(false);
      }
      fail(res.status);
    }, delay);
  }
  async function run() {
    ui.busy(true);
    ui.status("waiting", stateForStatus(202).message);
    const res = await post(urls.run);
    if (!live) return;
    if (isReport(res)) return show(res);
    if (res.status === 202) return poll(Date.now(), retryDelayMs(res.retryAfter));
    fail(res.status);
  }
  async function setConsent(video) {
    const res = await post(urls.consent, { video, version: CONSENT_VERSION });
    if (!live) return;
    if (res.status >= 200 && res.status < 300) {
      doc = { ...doc, consent: { ...(doc.consent || {}), video } };
      draw();
    } else {
      ui.status("error", "That choice could not be saved. Try again in a moment.");
    }
  }

  (async () => {
    const res = await get(urls.page, PAGE_OK);
    if (!live) return;
    if (res.status !== 200 || !res.body || typeof res.body !== "object") {
      const s = stateForStatus(res.status === 0 ? 500 : res.status);
      const title = res.status === 401 ? "Sign in to see your takes" : res.status === 404 ? "No takes found" : "Your takes did not load";
      return renderHistoryState(screen, "history-error", title, res.status === 0 || res.status >= 500 ? "Try again in a moment." : s.message);
    }
    doc = res.body;
    report = doc.report && typeof doc.report === "object" ? doc.report : null; // the server sends a state word ("none", "ready") here
    draw();
    if (report) return;
    const cached = await get(urls.report, NONE_YET); // a finished or still running report from an earlier visit
    if (!live) return;
    if (isReport(cached)) show(cached);
    else if (cached.status === 202) { ui.busy(true); ui.status("waiting", stateForStatus(202).message); poll(Date.now(), retryDelayMs(cached.retryAfter)); }
  })();
  return () => { live = false; if (timer) clearTimeout(timer); };
}

/** The result-page slot: fills `section` with "Your takes over time (N)" only for a signed-in student with 2+ takes. */
export async function historySlot(section, ctx) {
  const entryId = ctx && ctx.entryId;
  if (!section || !entryId) return null;
  if (!(await fetchMe()).signedIn) return null; // nobody signed in: no history request at all
  const res = await get(historyUrls(entryId).page, NONE_YET);
  const n = res.status === 200 && res.body && Array.isArray(res.body.takes) ? res.body.takes.length : 0;
  if (n < 2) return null;
  ensureCss(...CSS);
  renderSlot(section, slotTitle(n), `#/me/${encodeURIComponent(entryId)}`);
  return section;
}

/** `#/me`: the movements the signed-in student has takes of. Returns the cleanup function. */
export function mountMyTakes(container) {
  ensureCss(...CSS);
  let live = true;
  const screen = document.createElement("section");
  screen.className = "screen";
  container.append(screen);
  (async () => {
    const res = await get(historyUrls("").list, PAGE_OK);
    if (!live) return;
    if (res.status === 401) return renderHistoryState(screen, "history-signedout", "Sign in to see your takes", stateForStatus(401).message);
    if (res.status !== 200 || !res.body) return renderHistoryState(screen, "history-error", "Your takes did not load", "Try again in a moment.");
    const entries = Array.isArray(res.body.entries) ? res.body.entries : [];
    renderMyTakes(screen, entries.filter((e) => e && e.entry_id).map((e) => {
      const n = Array.isArray(e.takes) ? e.takes.length : Number(e.takes) || 0;
      return { href: `#/me/${encodeURIComponent(e.entry_id)}`, name: e.name || e.entry_id, line: plural(n, "take", "takes") };
    }));
  })();
  return () => { live = false; };
}

/**
 * C-WEB entry. `mountHistory(el, entryId)` mounts the page; `mountHistory(el, {jobId, entryId, analysis, seek})` is the
 * result-page slot (called once per mount, only when the job has an entry_id).
 */
export function mountHistory(el, arg) {
  if (typeof arg === "string") return mountPage(el, arg);
  historySlot(el, arg).catch(() => {});
  return () => {};
}
