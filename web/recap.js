// "Across my movements" (#/me/all), the monthly recap (#/me/recap) and the next-session plan card
// (docs/specs/history-all.md): glue between the routes, the models and the views. Opt-in like history.js:
// signed out, every call answers 401 and the page says so.
import { ensureCss } from "./ui.js";
import { call } from "./me-api.js";
import { keepPolling, retryDelayMs } from "./model/history.js";
import { ACROSS_URLS, acrossView, modelView, planUrl, planView, planWithCatalog, recapReportUrl, recapUrl, recapView } from "./model/recap.js";
import { getEntry } from "./api.js";
import { renderAcross, renderPlan, renderRecap } from "./views/recap.js";
import { renderHistoryState } from "./views/history.js";
import { loadProgress, saveProgress } from "./practice.js";

const CSS = ["theme/history.css", "data-history-css"];
const NORMAL = { expectStatus: [401, 404, 422] }; // signed out, not enough movements, no report yet: normal answers
const get = (url) => call("GET", url, undefined, NORMAL);
const post = (url, data) => call("POST", url, data || {}, NORMAL);
const WAITING = "Simon is reading your takes. This takes up to a minute and a half.";
const TEXT = {
  401: ["Sign in to see this", "Sign in to see your takes over time."],
  422: ["Not enough yet", "Keep takes of at least 2 movements to read across them."],
};

function problem(screen, status) {
  const [title, body] = TEXT[status] || ["This did not load", "Try again in a moment."];
  renderHistoryState(screen, "history-error", title, body);
}

/** Runs a model call and polls until its report is there; `show(body)` draws it. Returns a stop function. */
function runner(ui, { start, read, show, live }) {
  let timer = null;
  const fail = (status) => {
    ui.busy(false);
    ui.status("error", status === 409 ? "Simon needs to keep your takes before it can read them. Turn on keeping takes in your account." : status === 422 ? TEXT[422][1] : "The reading could not start. Try again in a moment.");
  };
  const poll = (startedAt, delay) => {
    timer = setTimeout(async () => {
      if (!live()) return;
      const res = await read();
      if (!live()) return;
      if (res.status === 200 && res.body) { ui.busy(false); ui.status("done", ""); return show(res.body); }
      if (res.status === 202 && keepPolling(Date.now() - startedAt)) return poll(startedAt, retryDelayMs(res.retryAfter));
      if (res.status === 202) { ui.busy(false); return ui.status("slow", "This is taking longer than usual. Leave the page open, or come back in a few minutes."); }
      fail(res.status);
    }, delay);
  };
  return {
    async run() {
      ui.busy(true);
      ui.status("waiting", WAITING);
      const res = await start();
      if (!live()) return;
      if (res.status === 200 && res.body) { ui.busy(false); ui.status("done", ""); return show(res.body); }
      if (res.status === 202) return poll(Date.now(), retryDelayMs(res.retryAfter));
      fail(res.status);
    },
    stop() { if (timer) clearTimeout(timer); },
  };
}

function shell(container) {
  ensureCss(...CSS);
  const screen = document.createElement("section");
  screen.className = "screen";
  container.append(screen);
  return screen;
}

/** `#/me/all`. Returns the cleanup function. */
export function mountAcross(container) {
  const screen = shell(container);
  let alive = true;
  let job = null;
  const live = () => alive;
  function draw(body) {
    const ui = renderAcross(screen, acrossView(body), { onRun: () => job.run(), onLeaveOut });
    job = runner(ui, { start: () => post(ACROSS_URLS.report), read: () => get(ACROSS_URLS.report), live, show: (doc) => ui.model(modelView(doc)) });
    if (body.report === "ready" || body.report === "running") job.run();
  }
  async function load() {
    const res = await get(ACROSS_URLS.page);
    if (!alive) return;
    if (res.status !== 200 || !res.body) return problem(screen, res.status);
    draw(res.body);
  }
  async function onLeaveOut(entryId, leave) {
    const boxes = [...screen.querySelectorAll("input[data-entry]")];
    const left = boxes.filter((b) => (b.getAttribute("data-entry") === entryId ? leave : !b.checked)).map((b) => b.getAttribute("data-entry"));
    const res = await post(ACROSS_URLS.prefs, { left_out: left });
    if (!alive) return;
    if (job) job.stop();
    if (res.status === 200 && res.body) draw({ ...res.body, report: "none" });
    else problem(screen, res.status);
  }
  load();
  return () => { alive = false; if (job) job.stop(); };
}

/** `#/me/recap[?month=YYYY-MM]`. Returns the cleanup function. */
export function mountRecap(container, month) {
  const screen = shell(container);
  let alive = true;
  let job = null;
  const live = () => alive;
  async function draw(body) {
    const vm = recapView(body);
    const ui = renderRecap(screen, vm, { onRun: () => job.run(), onLeaveOut });
    job = runner(ui, {
      start: () => post(recapReportUrl(vm.month)), read: () => get(recapReportUrl(vm.month)), live,
      show: async () => { const again = await get(recapUrl(vm.month)); if (alive && again.status === 200) draw(again.body); },
    });
    if (vm.modelState === "ready") ui.model(vm.model);
    else if (vm.modelState === "running") job.run();
  }
  async function onLeaveOut(entryId, leave) {
    const boxes = [...screen.querySelectorAll("input[data-entry]")];
    const left = boxes.filter((b) => (b.getAttribute("data-entry") === entryId ? leave : !b.checked)).map((b) => b.getAttribute("data-entry"));
    const res = await post(ACROSS_URLS.prefs, { left_out: left });
    if (!alive) return;
    const again = res.status === 200 || res.status === 422 ? await get(recapUrl(month)) : res;
    if (alive && again.status === 200) draw(again.body);
  }
  (async () => {
    const res = await get(recapUrl(month));
    if (!alive) return;
    if (res.status !== 200 || !res.body) return problem(screen, res.status);
    draw(res.body);
  })();
  return () => { alive = false; if (job) job.stop(); };
}

/** Practise this section: mark the ladder step in the practice progress, then open the follow screen. */
export function practiseStep({ entryId, step }, go = (hash) => { location.hash = hash; }) {
  const progress = loadProgress(entryId);
  saveProgress(entryId, { ...progress, on: true, focus: step });
  go(`#/follow/${encodeURIComponent(entryId)}`);
}

/** Adds the plan card to `box` for a movement (after a take: pass the job). Nothing is added when there is no plan. */
export async function addPlan(box, entryId, jobId) {
  const res = await get(planUrl(entryId, jobId));
  const vm = res.status === 200 ? await planWithCatalog(planView(res.body, entryId), async (id) => (await getEntry(id)) != null) : null;
  if (!vm) return false;
  ensureCss(...CSS);
  renderPlan(box, vm, practiseStep);
  return true;
}
