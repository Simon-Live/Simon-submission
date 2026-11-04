// "Your takes over time" (docs/specs/history-web.md, contract C-WEB): glue between the history routes (C-HTTP), the
// model (model/history.js) and the views (views/history.js). Opt-in: with nobody signed in every call answers 401 and
// the page, the list and the result slot stay empty or say so; nothing else in the app reads this module.
import { consentPolicy, policyOn } from "./policy.js";
import { ensureCss } from "./ui.js";
import { call } from "./me-api.js";
import { fetchMe } from "./auth.js";
import {
  CONSENT_VERSION, historyUrls, keepPolling, pageView, plural, retryDelayMs, slotTitle, stateForStatus,
} from "./model/history.js";
import { pollFailure, reelState, reelUrls, reelView } from "./model/reel.js";
import { sinceUrl, sinceView } from "./model/since.js";
import { renderHistoryPage, renderHistoryState, renderMyTakes, renderSlot } from "./views/history.js";
import { renderSince } from "./views/since.js";
import { patternsGate, patternsState, patternsUrl, patternsView } from "./model/patterns.js";
import { patternsSection } from "./views/patterns.js";
import { ASK_URL, QUESTION_MAX, answerView, questionError, stateForStatus as askState } from "./model/ask.js";
import { renderAsk } from "./views/ask.js";
import { listExtras } from "./model/recap.js";
import { renderListExtras } from "./views/recap.js";

const CSS = ["theme/history.css", "data-history-css"];
const PAGE_OK = { expectStatus: [401, 404] }; // signed out, or nothing kept yet: the page says so, it is not an anomaly
const NONE_YET = { expectStatus: [404] }; // no copies kept yet, or no report made yet: a normal answer, not an anomaly

const get = (url, opts) => call("GET", url, undefined, opts);
const post = (url, data) => call("POST", url, data || {});
const isReport = (r) => r.status === 200 && r.body && typeof r.body === "object";

/** The "Next session" card under the title of a page; nothing is added when there is no plan. */
function addPlanCard(screen, entryId, alive) {
  const slot = document.createElement("div");
  slot.setAttribute("data-testid", "plan-slot");
  import("./recap.js").then(async (m) => {
    if (!(await m.addPlan(slot, entryId)) || !alive()) return;
    const title = screen.querySelector('[data-testid="history-title"]');
    if (title && title.after) title.after(slot); else screen.append(slot);
  }).catch(() => {});
}

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
  // TICKET-233: once a comparison exists the person can share it (signed in only, the module checks)
  const offerShare = () => import("./share.js").then((m) => { if (live) m.mountReportShare(screen, entryId); }).catch(() => {});

  let found = null; // the stored result of "Patterns across your takes" (TICKET-221), drawn again when the page is
  let patterns = null;
  let ptimer = null;
  let stopNotes = () => {}; // trainer notes for this movement (TICKET-237), kept apart from `screen` so a redraw does not remove them
  let rtimer = null; // the reel's poll (TICKET-228), apart from the report's `timer`
  const clipOf = (n) => (pageView(doc, entryId, report).takes.find((r) => r.take === n) || {}).clip || "";
  const draw = () => {
    ui = renderHistoryPage(screen, pageView(doc, entryId, report), { onRun: run, onConsent: setConsent, onReel: makeReel, adultsAsked: consentPolicy().required === true });
    patterns = patternsSection(patternsGate(doc), ui.player, { onFind: findPatterns });
    ui.patternsSlot.append(patterns.el);
    if (found) patterns.result(patternsView(found, clipOf));
  };
  const showPatterns = (body) => {
    found = body;
    patterns.result(patternsView(found, clipOf));
    patterns.status("done", "");
    patterns.busy(false);
  };
  const failPatterns = (status) => {
    patterns.status(patternsState(status).kind, patternsState(status).message);
    patterns.busy(false);
  };
  function pollPatterns(startedAt, delay) {
    ptimer = setTimeout(async () => {
      if (!live) return;
      const res = await get(patternsUrl(entryId), NONE_YET);
      if (!live) return;
      if (isReport(res)) return showPatterns(res.body);
      if (res.status === 202 && keepPolling(Date.now() - startedAt)) return pollPatterns(startedAt, retryDelayMs(res.retryAfter));
      if (res.status === 202) {
        patterns.status("slow", "This is taking longer than usual. Leave the page open, or come back in a few minutes.");
        return patterns.busy(false);
      }
      failPatterns(res.status);
    }, delay);
  }
  async function findPatterns() {
    patterns.busy(true);
    patterns.status("waiting", patternsState(202).message);
    const res = await post(patternsUrl(entryId));
    if (!live) return;
    if (isReport(res)) return showPatterns(res.body);
    if (res.status === 202) return pollPatterns(Date.now(), retryDelayMs(res.retryAfter));
    failPatterns(res.status);
  }
  async function loadPatterns() { // a finished or still running result from an earlier visit
    const res = await get(patternsUrl(entryId), NONE_YET);
    if (!live) return;
    if (isReport(res)) showPatterns(res.body);
    else if (res.status === 202) { patterns.busy(true); patterns.status("waiting", patternsState(202).message); pollPatterns(Date.now(), retryDelayMs(res.retryAfter)); }
  }
  const show = (res) => {
    report = res.body;
    ui.report(pageView(doc, entryId, report));
    offerShare();
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
  // the progress reel (TICKET-228): the same make, wait, show shape as the report, on its own route
  const reelUrl = reelUrls(entryId).reel;
  const isReel = (r) => r.status === 200 && reelView(r.body, entryId) !== null;
  function showReel(res) {
    ui.reel.show(reelView(res.body, entryId));
    ui.reel.status("done", "");
    ui.reel.busy(false);
  }
  function failReel(status, afterMake = false) {
    const lost = afterMake ? pollFailure(status) : null; // a 404 while polling a make is a reel that died (shown as reel-failed)
    if (lost) { ui.reel.show(lost); ui.reel.status("failed", ""); return ui.reel.busy(false); }
    const s = reelState(status);
    ui.reel.status(s.kind, s.message);
    ui.reel.busy(false);
  }
  function pollReel(startedAt, delay) {
    rtimer = setTimeout(async () => {
      if (!live) return;
      const res = await get(reelUrl, NONE_YET);
      if (!live) return;
      if (isReel(res)) return showReel(res);
      if (res.status === 202 && keepPolling(Date.now() - startedAt)) return pollReel(startedAt, retryDelayMs(res.retryAfter));
      if (res.status === 202) {
        ui.reel.status("slow", "This is taking longer than usual. Leave the page open, or come back in a few minutes.");
        return ui.reel.busy(false);
      }
      failReel(res.status, true);
    }, delay);
  }
  async function makeReel() {
    ui.reel.busy(true);
    ui.reel.status("waiting", reelState(202).message);
    const res = await post(reelUrl);
    if (!live) return;
    if (isReel(res)) return showReel(res);
    if (res.status === 202) return pollReel(Date.now(), retryDelayMs(res.retryAfter));
    failReel(res.status);
  }
  async function setConsent(video, adults) {
    const res = await post(urls.consent, { video, version: CONSENT_VERSION, ...(adults === true ? { meta_adults: true } : {}) });
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
    if (Array.isArray(doc.takes) && doc.takes.length === 0) { // 200 with no takes yet: the empty state, no report request
      return renderHistoryState(screen, "history-mytakes-empty", "No takes kept yet", "When you follow a movement while signed in, your takes show up here.");
    }
    report = doc.report && typeof doc.report === "object" ? doc.report : null; // the server sends a state word ("none", "ready") here
    draw();
    import("./notes.js").then((m) => { if (live) stopNotes = m.mountTakeNotes(container, entryId); }).catch(() => {});
    addPlanCard(screen, entryId, () => live);
    import("./progress-sheet.js").then((m) => { // TICKET-283: a movement with a take in rehab mode links its progress sheet
      const link = live ? m.historyLink(doc, entryId) : null;
      const title = screen.querySelector('[data-testid="history-title"]');
      if (link) { if (title && title.after) title.after(link); else screen.append(link); }
    }).catch(() => {});
    if (policyOn("muse") && patternsGate(doc).ok) await loadPatterns();
    if (!live) return;
    const earlier = await get(reelUrl, NONE_YET); // a reel made in an earlier visit, or one still being cut
    if (!live) return;
    if (isReel(earlier)) showReel(earlier);
    else if (earlier.status === 202) { ui.reel.busy(true); ui.reel.status("waiting", reelState(202).message); pollReel(Date.now(), retryDelayMs(earlier.retryAfter)); }
    if (report) return offerShare();
    const cached = await get(urls.report, NONE_YET); // a finished or still running report from an earlier visit
    if (!live) return;
    if (isReport(cached)) show(cached);
    else if (cached.status === 202) { ui.busy(true); ui.status("waiting", stateForStatus(202).message); poll(Date.now(), retryDelayMs(cached.retryAfter)); }
  })();
  return () => { live = false; stopNotes(); if (timer) clearTimeout(timer); if (ptimer) clearTimeout(ptimer); if (rtimer) clearTimeout(rtimer); };
}

/**
 * The result-page slot, only for a signed-in student: "Since last time" (one line against the previous take of the same
 * movement, section and mode, and personal bests) and "Your takes over time (N)" with 2 or more takes. Anonymous: nothing.
 */
export async function historySlot(section, ctx) {
  const entryId = ctx && ctx.entryId;
  if (!section || !entryId) return null;
  if (!(await fetchMe()).signedIn) return null; // nobody signed in: no history request at all
  const jobId = ctx.jobId && ctx.jobId !== "fixture" ? ctx.jobId : null;
  const [res, since] = await Promise.all([get(historyUrls(entryId).page, NONE_YET), jobId ? get(sinceUrl(jobId), NONE_YET) : null]);
  const n = res.status === 200 && res.body && Array.isArray(res.body.takes) ? res.body.takes.length : 0;
  const view = since && since.status === 200 && since.body ? sinceView(since.body.since) : null;
  if (n < 2 && !view) return null;
  ensureCss(...CSS);
  section.replaceChildren();
  if (view) renderSince(section, view);
  if (n >= 2) renderSlot(section, slotTitle(n), `#/me/${encodeURIComponent(entryId)}`, true);
  if (n >= 2) {
    const recap = await import("./recap.js").catch(() => null); // the plan for the next session, from the stored takes
    if (recap) await recap.addPlan(section, entryId, jobId);
    const focus = await import("./focus.js").catch(() => null); // whether last time's cue came up, with the noise band (TICKET-223 AC-2)
    if (focus) await focus.addFocusResult(section, entryId, jobId);
  }
  return section;
}

/** The "Ask my history" box under the list of movements: only when the server says there is enough to ask about. */
async function mountAsk(host, isLive) {
  const info = await get(ASK_URL, PAGE_OK);
  if (!isLive() || info.status !== 200 || !info.body || !info.body.retention || !info.body.can_ask) return;
  const ui = renderAsk(host, { suggestions: info.body.suggestions || [], maxChars: QUESTION_MAX }, { ask });
  async function ask(text) {
    const bad = questionError(text);
    if (bad) return ui.status("error", bad);
    ui.busy(true);
    ui.status("waiting", "Simon is reading your takes.");
    const res = await call("POST", ASK_URL, { question: String(text).trim() }, { expectStatus: [409, 422, 429] });
    if (!isLive()) return;
    ui.busy(false);
    if (res.status === 200 && res.body) {
      ui.status("done", "");
      return ui.answer(answerView(res.body));
    }
    const s = askState(res.status, res.body);
    ui.status(s.kind, s.message);
  }
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
      return { href: `#/me/${encodeURIComponent(e.entry_id)}`, name: e.name || e.entry_id, line: plural(n, "take", "takes") + (e.synthetic ? ". Seeded demo history" : "") };
    }));
    const box = document.createElement("div"); // the recap offer and across my movements, above the list
    box.setAttribute("data-testid", "me-extras");
    renderListExtras(box, listExtras(res.body));
    const heading = screen.querySelector("h1");
    if (box.children.length && heading) heading.after(box);
    if (entries.length) await mountAsk(screen, () => live);
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
