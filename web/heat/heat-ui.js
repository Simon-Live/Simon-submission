// The Heat control and its legend in the 3D stage (docs/specs/heat-and-ar.md, TICKET-274).
//
//   const tools = mountHeatControls(host, { heat: view.heat, seek });   // tools: {el, destroy()} or null
//
// heat: `view.heat` of a mesh view (null with no heat data, and then nothing is added). seek(t): moves the result's clock.
// The first press opens the view at `heat.open`, the frame nearest the first reported fault. The legend is the same
// --heat-0 to --heat-4 ramp the body is painted with.
//
// The words say only what the colours are: where your body differed most from the trainer in the frame on screen. They do
// not say the heat shows where the fault is: the check of heat against Part 5's faults was not met (docs/specs/heat.md).
import { h } from "../ui.js";
import { regionLabel } from "./heat-data.js";

export const HEAT_TEXT = {
  toggle: "Heat",
  caption: "Where your body differed most from the trainer in this frame.",
  reopen: "Back to the opening frame",
  low: "Matches the trainer",
  high: "Differs most",
  legend: "Heat scale: from matching the trainer to differing most. Everyone is put on one standard body before the compare.",
  after: "After the movement",
  quiet: "Nothing differs much in this frame.",
  here: (name) => `Differs most here: ${regionLabel(name)}`,
  opens: (source, t) => (source === "fault"
    ? `Opens at your first reported fault, ${t.toFixed(1)} s`
    : `Opens where you differed most from the trainer, ${t.toFixed(1)} s`),
};

export function mountHeatControls(host, { heat, seek = () => {} } = {}) {
  if (!host || !heat) return null;
  const caption = h("p", { class: "st-heat-caption", "data-testid": "heat-caption", text: HEAT_TEXT.caption });
  const readout = h("p", { class: "st-heat-readout", "data-testid": "heat-readout", "aria-live": "polite", text: HEAT_TEXT.opens(heat.open.source, heat.open.t) });
  const legend = h("div", { class: "st-heat-legend", "data-testid": "heat-legend", role: "img", "aria-label": HEAT_TEXT.legend },
    h("span", { class: "st-heat-ramp" }),
    h("span", { class: "st-heat-ends" }, h("span", { text: HEAT_TEXT.low }), h("span", { text: HEAT_TEXT.high })));
  const reopen = h("button", { type: "button", class: "sr-btn st-heat-reopen", "data-testid": "heat-reopen", text: HEAT_TEXT.reopen,
    onclick: () => seek(heat.open.t) });
  const panel = h("div", { class: "st-heat-panel", "data-testid": "heat-panel", hidden: true }, caption, readout, legend, reopen);
  const toggle = h("button", { type: "button", class: "sr-btn st-heat-toggle", "data-testid": "heat-toggle", "aria-pressed": "false",
    text: HEAT_TEXT.toggle });
  let opened = false;
  toggle.addEventListener("click", () => {
    const on = toggle.getAttribute("aria-pressed") !== "true";
    toggle.setAttribute("aria-pressed", String(on));
    panel.hidden = !on;
    heat.setOn(on);
    if (on && !opened) { opened = true; seek(heat.open.t); }
  });
  heat.onRegion((hot) => { readout.textContent = hot && hot.after ? HEAT_TEXT.after : hot ? HEAT_TEXT.here(hot.name) : HEAT_TEXT.quiet; });
  const el = h("div", { class: "st-heat", "data-testid": "heat-tools" }, toggle, panel);
  host.append(el);
  return { el, destroy() { heat.onRegion(null); if (toggle.getAttribute("aria-pressed") === "true") heat.setOn(false); el.remove(); } };
}
