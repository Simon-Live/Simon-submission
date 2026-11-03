// The class handout from a view model (web/model/handout.js), styled by theme/teacher.css; it prints on paper colours
// with the app's bar and buttons hidden. No fetching and no storage: the print action comes in as `onPrint`.
import { h, clear, stateBlock, linkButton } from "../ui.js";
import { svg } from "./svg.js";

function qrImage({ d, side, label }) {
  return svg("svg", { class: "ho-qr", viewBox: `0 0 ${side} ${side}`, role: "img", "aria-label": label, "shape-rendering": "crispEdges", "data-testid": "handout-qr" },
    svg("title", {}, label),
    svg("rect", { class: "ho-qr-paper", width: side, height: side }),
    svg("path", { class: "ho-qr-ink", d, "data-testid": "handout-qr-path" }));
}

/** Fill `screen` with the handout of `vm` (from `handoutView`); `onPrint` runs when the print button is pressed. */
export function renderHandout(screen, vm, onPrint) {
  clear(screen).classList.add("ho");
  screen.append(
    h("p", { class: "ho-back ho-screen-only" }, h("a", { href: vm.back.href, "data-testid": "handout-back", text: vm.back.text })),
    h("article", { class: "ho-sheet", "data-testid": "handout" },
      h("h1", { class: "ho-title", "data-testid": "handout-title", text: vm.title }),
      h("p", { class: "ho-lede", text: vm.lede }),
      qrImage(vm.qr),
      h("p", { class: "ho-link" }, h("span", { class: "ho-link-label", text: vm.linkLabel }),
        h("a", { class: "ho-link-url", href: vm.link, "data-testid": "handout-link", text: vm.link })),
      h("ol", { class: "ho-steps" }, vm.steps.map((text) => h("li", { text })))),
    h("div", { class: "ho-actions ho-screen-only" },
      h("button", { type: "button", class: "btn primary", "data-testid": "handout-print", text: vm.print, onclick: onPrint })));
}

/** The error block: the movement is not found or did not load. */
export function renderHandoutError(screen, missing) {
  clear(screen).append(stateBlock("handout-error", missing ? "This movement is not found" : "The handout did not load",
    missing ? "The link may be wrong." : "Try again in a moment.", linkButton("#/", "Back to movements", "back-home")));
}
