// "Fix it for me" panel (docs/specs/fix-it-for-me.md, TICKET-265), drawn from plain data. Words come in as `vm.t`;
// handlers come in as `on`. No fetching, no storage, no model import, no WebGL: web/skin/corrected-replay.js owns the
// stages and the clock and hands this view the two stage hosts. Styled by theme/fix-it.css on the brand tokens.
import { h } from "../ui.js";

const ICON_PLAY = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5.5v13l11-6.5z"/></svg>';
const ICON_PAUSE = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 5h3.5v14H7zM13.5 5H17v14h-3.5z"/></svg>';

/**
 * `vm`: { t, options: [{index, text}] } where each option is one fixable coaching moment.
 * `on`: { open(i), close(), which("before"|"after"), split(bool), play(), scrub(seconds) }.
 * Returns { root, hostA, hostB, show(state), clock(t, playing, max), label(text), captions(a, b), data(obj) }.
 */
export function renderFixIt(host, vm, on) {
  const { t } = vm;
  const pickId = `fx-pick-${Math.random().toString(36).slice(2, 7)}`;
  const select = vm.options.length > 1
    ? h("select", { id: pickId, class: "fx-select", "data-testid": "fix-it-pick" }, vm.options.map((o) => h("option", { value: String(o.index), text: o.text })))
    : null;
  const open = h("button", { type: "button", class: "btn primary fx-open", "data-testid": "fix-it-button", "aria-expanded": "false", text: t.button });
  const label = h("p", { class: "fx-label", "data-testid": "fix-it-label", text: "" });
  const caption = h("p", { class: "fx-caption", "data-testid": "fix-it-note", text: t.caption });

  const segBtn = (key, text) => h("button", { type: "button", class: "btn secondary fx-seg", "data-testid": `fix-it-${key}`, "aria-pressed": "false", text });
  const before = segBtn("before", t.before);
  const after = segBtn("after", t.after);
  const split = h("button", { type: "button", class: "btn secondary fx-split", "data-testid": "fix-it-split", "aria-pressed": "false", text: t.split });
  const tools = h("div", { class: "fx-tools" }, h("div", { class: "fx-segs", role: "group", "aria-label": `${t.before} or ${t.after}` }, before, after), split);

  const capA = h("figcaption", { class: "fx-cap", "data-testid": "fix-it-caption-a", text: t.youCorrected });
  const capB = h("figcaption", { class: "fx-cap", "data-testid": "fix-it-caption-b", text: t.youCorrected });
  const hostA = h("div", { class: "fx-host", "data-testid": "fix-it-stage-a" });
  const hostB = h("div", { class: "fx-host", "data-testid": "fix-it-stage-b" });
  const figA = h("figure", { class: "fx-fig" }, hostA, capA);
  const figB = h("figure", { class: "fx-fig", hidden: true }, hostB, capB);
  const stages = h("div", { class: "fx-stages", "data-split": "false" }, figA, figB);

  const play = h("button", { type: "button", class: "btn secondary fx-play", "data-testid": "fix-it-play", "aria-label": "Play", "data-playing": "false" });
  play.innerHTML = ICON_PLAY;
  const scrub = h("input", { type: "range", class: "fx-scrub", "data-testid": "fix-it-scrub", min: "0", max: "1", step: "any", value: "0", "aria-label": "Position in this moment" });
  const clockOut = h("output", { class: "fx-clock", "data-testid": "fix-it-clock", text: "0.0 s" });
  const bar = h("div", { class: "fx-bar" }, play, scrub, clockOut);
  const close = h("button", { type: "button", class: "btn secondary fx-close", "data-testid": "fix-it-close", text: t.close });
  const msg = h("p", { class: "fx-msg", role: "status", "data-testid": "fix-it-msg", text: "" });
  const panel = h("div", { class: "fx-panel", "data-testid": "fix-it-panel", hidden: true }, label, caption, msg, tools, stages, bar, close);

  const root = h("section", { class: "fx", "data-testid": "fix-it", "data-open": "false", "aria-label": t.button },
    h("p", { class: "fx-lead", text: t.lead }),
    select ? h("label", { class: "fx-pick", for: pickId }, h("span", { text: t.pick }), select) : null,
    open, panel);
  host.append(root);

  const chosen = () => (select ? Number(select.value) : vm.options[0].index);
  open.addEventListener("click", () => on.open(chosen()));
  if (select) select.addEventListener("change", () => { if (!panel.hidden) on.open(chosen()); });
  close.addEventListener("click", () => on.close());
  before.addEventListener("click", () => on.which("before"));
  after.addEventListener("click", () => on.which("after"));
  split.addEventListener("click", () => on.split(split.getAttribute("aria-pressed") !== "true"));
  play.addEventListener("click", () => on.play());
  scrub.addEventListener("input", () => on.scrub(Number(scrub.value)));

  return {
    root, hostA, hostB, open, close,
    /** Show or hide the panel. */
    visible(on_) {
      panel.hidden = !on_;
      root.setAttribute("data-open", String(on_));
      open.setAttribute("aria-expanded", String(on_));
    },
    /** `which`: "before" | "after" for the one view; `split`: both views at once. */
    show({ which, split: both }) {
      before.setAttribute("aria-pressed", String(!both && which === "before"));
      after.setAttribute("aria-pressed", String(!both && which === "after"));
      before.disabled = after.disabled = both;
      split.setAttribute("aria-pressed", String(both));
      split.textContent = both ? t.single : t.split;
      figB.hidden = !both;
      stages.setAttribute("data-split", String(both));
      capA.textContent = both || which === "before" ? t.you : t.youCorrected;
      capB.textContent = t.youCorrected;
      root.setAttribute("data-which", both ? "split" : which);
    },
    /** The clip position `t` of `max` seconds. */
    clock(pos, playing, max) {
      scrub.max = String(max);
      scrub.value = String(pos);
      clockOut.textContent = `${pos.toFixed(1)} s`;
      play.setAttribute("data-playing", String(playing));
      play.setAttribute("aria-label", playing ? "Pause" : "Play");
      play.innerHTML = playing ? ICON_PAUSE : ICON_PLAY;
    },
    label(text) { label.textContent = text; },
    /** Plain facts for tests and the next reader: data-* on the root. */
    data(obj) { for (const [k, v] of Object.entries(obj)) root.setAttribute(`data-${k}`, String(v)); },
    note(text) { msg.textContent = text; },
    destroy() { root.remove(); },
  };
}
