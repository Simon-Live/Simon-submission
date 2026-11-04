// `#/whitepaper`: Simon's whitepaper, the design blueprint (team, 2026-11-03), shown in the app. The document is
// web/whitepaper.html, a copy of the hub's docs/blueprint/index.html without its web-font link, so it loads nothing
// from a third party. It sits in a same-origin frame that grows to its full height, so the page scrolls as one.
import { clear, ensureCss, h } from "./ui.js";

export const WHITEPAPER = {
  title: "Whitepaper",
  lead: "How Simon works, end to end: the product, the pipeline, the AI models, scoring, privacy, and what we are still working on.",
  note: "This is the design document, so it also covers models and services that are off on simon.live, such as Muse Image, Muse Glimmer, Muse Voice Transcribe, the MMS-TTS voices and the SAM 3.1 open weights. Muse Spark is on, and Muse Spark Open runs on Baseten. The live service's list is on ",
  noteLink: "Who processes your data",
  open: "Open in a new tab",
  src: "whitepaper.html",
  frameTitle: "Simon whitepaper",
};

export function mountWhitepaper(el) {
  ensureCss("theme/legal.css", "data-legal-css");
  clear(el);
  const frame = h("iframe", { class: "wp-frame", src: WHITEPAPER.src, title: WHITEPAPER.frameTitle, "data-testid": "whitepaper-frame", loading: "lazy" });
  const fit = () => {
    try {
      const doc = frame.contentDocument;
      if (doc && doc.documentElement) frame.style.height = `${doc.documentElement.scrollHeight}px`;
    } catch { /* not same-origin: the frame keeps its own scroll */ }
  };
  frame.addEventListener("load", () => { fit(); setTimeout(fit, 600); });
  window.addEventListener("resize", fit);
  el.append(h("section", { class: "wp", "data-testid": "whitepaper" },
    h("header", { class: "lg-head" },
      h("h1", { text: WHITEPAPER.title }),
      h("p", { class: "lg-lead", text: WHITEPAPER.lead }),
      h("p", { class: "lg-lead", "data-testid": "whitepaper-note" }, WHITEPAPER.note, h("a", { href: "sub-processors", text: WHITEPAPER.noteLink }), "."),
      h("a", { class: "wp-open", href: WHITEPAPER.src, target: "_blank", rel: "noopener", "data-testid": "whitepaper-open", text: WHITEPAPER.open })),
    frame));
  window.scrollTo(0, 0);
  return () => window.removeEventListener("resize", fit);
}
