// Glue for "Ask this take" (TICKET-269, Part 7 half): joins the model (model/take-ask.js) and the view (views/take-ask.js) to
// the route and to the result page's player. Opt-in and owner-only: a signed-out viewer, a take that is not theirs, a private
// take or a person who keeps no takes sees nothing at all. Nothing is stored in the browser.
import { ensureCss } from "./ui.js";
import { call } from "./me-api.js";
import { fetchMe } from "./auth.js";
import * as m from "./model/take-ask.js";
import { renderTakeAsk } from "./views/take-ask.js";
import { isOrphaned } from "./orphan-take.js";

const QUIET = { expectStatus: [401, 404, 409, 422, 429] }; // normal answers of this feature, not anomalies
const STEP_MS = 700;
const reduced = () => typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;
const wait = (ms) => new Promise((r) => setTimeout(r, ms));

/** The result page slot. `ctx` = { job, pid, analysis, jobRecord, view() }; `view()` gives { jump(t), highlight(names) } or null. */
export function mountTakeAsk(slot, ctx) {
  if (!ctx || !ctx.job || ctx.job === "fixture" || ctx.pid) return undefined;
  if (ctx.jobRecord && ctx.jobRecord.attribution && ctx.jobRecord.attribution.mine === false) return undefined; // someone else's take
  if (isOrphaned(ctx.jobRecord)) return undefined; // TICKET-331: the trainer deleted the movement, so there is no one to ask
  let live = true;
  const url = m.takeAskUrl(ctx.job);
  const go = (t) => { const v = ctx.view && ctx.view(); if (v) v.jump(t); };
  (async () => {
    const me = await fetchMe().catch(() => null);
    if (!me || !me.signedIn || !live) return;
    const info = await call("GET", url, undefined, QUIET);
    if (!live || info.status !== 200 || !info.body || !info.body.can_ask) return;
    ensureCss("theme/take-ask.css", "data-take-ask-css");
    const host = document.createElement("div");
    host.className = "sr-take-ask";
    slot.append(host);
    const ui = renderTakeAsk(host, { t: m.TEXT, suggestions: info.body.suggestions || [], remaining: info.body.remaining, maxChars: m.QUESTION_MAX }, { ask, go });
    async function play(steps) {
      const shown = [];
      for (const step of steps) {
        if (!live) return;
        const v = ctx.view && ctx.view();
        if (v) { if (step.tool === "seek") v.jump(step.t); else v.highlight(step.joints); }
        shown.push(step);
        ui.steps(shown.map((s) => s.label), shown.map((s) => s.tool));
        if (!reduced()) await wait(STEP_MS);
      }
    }
    async function ask(text) {
      const bad = m.questionError(text);
      if (bad) return ui.status("error", bad);
      ui.busy(true);
      ui.steps([]);
      ui.status("waiting", m.TEXT.waiting);
      const res = await call("POST", url, { question: String(text).trim() }, QUIET);
      if (!live) return;
      ui.busy(false);
      if (res.status !== 200 || !res.body) {
        const s = m.stateForStatus(res.status, res.body);
        return ui.status(s.kind, s.message);
      }
      ui.status("done", "");
      ui.answer(m.takeAnswerView(res.body));
      await play(m.stepsOf(res.body.actions));
    }
  })().catch(() => {});
  return () => { live = false; slot.replaceChildren(); };
}
