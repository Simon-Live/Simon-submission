// Export button views: they draw what they are given and fetch or store nothing.
import { h } from "../ui.js";

export const startView = (label, onStart) =>
  h("button", { type: "button", class: "btn secondary ex-start", "data-testid": "export-start", onclick: onStart }, label);

export const busyView = (label) => h("p", { class: "export-msg ex-busy", role: "status", "data-testid": "export-busy" }, h("span", { class: "ex-spin", "aria-hidden": "true" }), label);

export const errorView = (message, retryLabel, onRetry) =>
  h("div", { class: "export-fail" },
    h("p", { class: "export-msg ex-error", role: "alert", "data-testid": "export-error" }, message),
    startView(retryLabel, onRetry));

export const readyView = (url, downloadLabel) =>
  h("div", { class: "export-ready" },
    h("video", { src: url, controls: true, playsinline: true, preload: "metadata", "data-testid": "export-video" }),
    h("a", { class: "btn primary ex-download", href: url, download: "simon-clip.mp4", "data-testid": "export-download" }, downloadLabel));
