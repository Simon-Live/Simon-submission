// The public viewer `#/shared/<token>` (docs/specs/share.md): the snapshot and nothing else. No sign-in, no account detail.
import { h, clear, ensureCss, stateBlock, linkButton } from "../ui.js";
import { call } from "../me-api.js";
import { authorLine } from "./author-line.js";
import { creditBlock } from "../source-credit.js"; // TICKET-322

const css = () => ensureCss("theme/share.css", "data-share-css");

/** The take's score as its result shows it ("0 score out of 100, grade F") and the result's warning box, word for word. */
function scoreAndWarnings(r) {
  const out = [h("p", { class: "sh-score", "data-testid": "shared-score", "data-grade": r.grade, "data-unit": r.unit, "aria-label": r.label },
    h("strong", { text: r.text }), r.caption ? h("span", { class: "sh-of", "data-testid": "shared-score-caption", text: ` ${r.caption}` }) : null,
    h("span", { class: "sh-grade", "data-testid": "shared-grade", text: `, grade ${r.grade}` }))];
  if (r.warnings.length) {
    out.push(h("section", { class: "sh-warning", role: "status", "data-testid": "shared-warning", "data-codes": r.warnings.map((w) => w.code).join(",") },
      h("h2", { text: r.warningTitle }),
      ...r.warnings.flatMap((w) => [h("p", { class: "sh-text", "data-testid": `shared-warning-${w.code}`, text: w.text }),
        w.tip ? h("p", { class: "sh-hint", "data-testid": `shared-warning-tip-${w.code}`, text: w.tip }) : null])));
  }
  return out;
}

/** Draw a snapshot into `el`. The owner's preview and the viewer page use this one renderer. `model` is the share model, injected by web/share.js. */
export function renderSnapshot(el, snap, model) {
  if (snap && snap.kind === "progress_sheet" && model.renderSheet) return model.renderSheet(el, snap); // TICKET-283: its own view
  const vm = model.viewModel(snap, model);   // the model carries the result's warnings hooks (web/share.js)
  const kids = [h("h1", { class: "sh-title", "data-testid": "shared-title", text: vm.heading }), h("p", { class: "sh-by", "data-testid": "shared-by", text: vm.byline })];
  const by = model.bylines ? model.bylines(vm.attribution) : { author: null, trainer: null };
  const line = authorLine([by.author, by.trainer], "shared-author"); // the server already applied the share's name choice
  if (line) kids.push(line);
  const credit = creditBlock(snap && snap.source, "shared-source"); // TICKET-322: the take's source and licence
  if (credit) kids.push(credit);
  if (vm.result) kids.push(...scoreAndWarnings(vm.result));
  else if (vm.score) { // a snapshot made before the score fix: drawn as it always was
    kids.push(h("p", { class: "sh-score", "data-testid": "shared-score" }, h("strong", { text: String(vm.score.value) }), vm.score.grade ? h("span", { class: "sh-grade", text: ` ${vm.score.grade}` }) : null));
  }
  if (vm.on) kids.push(h("p", { class: "sh-hint", "data-testid": "shared-date", text: vm.on }));
  if (vm.faults.length) kids.push(h("ul", { class: "sh-list", "data-testid": "shared-faults" }, vm.faults.map((f) => h("li", { text: f }))));
  if (vm.summary) kids.push(h("p", { class: "sh-text", "data-testid": "shared-summary", text: vm.summary }));
  if (vm.trends.length) kids.push(h("ul", { class: "sh-list", "data-testid": "shared-trends" }, vm.trends.map((t) => h("li", { text: t }))));
  if (vm.rows.length) {
    kids.push(h("ol", { class: "sh-takes", "data-testid": "shared-takes" }, vm.rows.map((r) =>
      h("li", {}, h("strong", { text: `Take ${r.take}` }), ` ${r.score ?? ""}${r.grade ? ` ${r.grade}` : ""}${r.on ? `, ${r.on}` : ""}`))));
  }
  if (vm.clip) kids.push(h("video", { class: "sh-clip", "data-testid": "shared-clip", src: vm.clip, controls: true, playsinline: true, preload: "metadata" }));
  if (vm.until) kids.push(h("p", { class: "sh-hint", "data-testid": "shared-until", text: vm.until }));
  clear(el).append(...kids);
  return vm;
}

/** `#/shared/<token>`. Returns the cleanup function. */
export function mountShared(el, token, model) {
  const { TEXT, viewerUrl } = model;
  css();
  let live = true;
  let drawn = null; // a progress sheet's replay stops with the page (TICKET-283)
  const page = h("section", { class: "screen sh", "data-testid": "shared-page" }, h("p", { text: "Loading" }));
  el.append(page);
  (async () => {
    const res = await call("GET", viewerUrl(token), undefined, { expectStatus: [404, 410, 429] });
    if (!live) return;
    if (res.status === 200 && res.body && typeof res.body === "object") {
      drawn = renderSnapshot(page, res.body, model);
      page.append(h("p", { class: "sh-foot" }, h("a", { href: "#/", text: TEXT.home })));
    } else if (res.status === 410) { // a link this server made that ended: the plain line, not "not found"
      const stopped = res.body?.ended === "revoked";
      clear(page).append(stateBlock("shared-ended", stopped ? TEXT.stoppedByOwner : TEXT.expired, stopped ? TEXT.stoppedByOwnerBody : TEXT.expiredBody, linkButton("#/", TEXT.home, "shared-home")));
    } else if (res.status === 404) {
      clear(page).append(stateBlock("shared-gone", TEXT.gone, TEXT.goneBody, linkButton("#/", TEXT.home, "shared-home")));
    } else {
      clear(page).append(stateBlock("shared-error", TEXT.gone, TEXT.loadFailed, linkButton("#/", TEXT.home, "shared-home")));
    }
  })();
  return () => { live = false; if (drawn && typeof drawn.stop === "function") drawn.stop(); };
}
