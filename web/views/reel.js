// "Your progress reel" card on the history page, from a view model (web/model/reel.js). No fetching, no storage: the
// glue passes the handlers in. Styled by theme/history.css on the brand tokens.
import { policyOn } from "../policy.js";
import { h, clear } from "../ui.js";
import { renderReceipt } from "./receipt.js";

/**
 * @param {{canMake: boolean, hint: string, disclosure: string}} panel
 * @param {{onMake(): void}} hooks
 * @param {{open(url: string, at: number, label: string): void}} player the page's clip player (a moment opens its take)
 * @returns handles `status(kind, text)`, `busy(bool)`, `show(view)` and the card `el`.
 */
export function renderReelCard(panel, hooks, player) {
  const make = h("button", { type: "button", class: "btn primary hs-run", "data-testid": "reel-make", text: "Make my progress reel",
    onclick: () => hooks.onMake(), disabled: !panel.canMake, hidden: !policyOn("muse") });
  const status = h("p", { class: "hs-status", role: "status", "aria-live": "polite", "data-testid": "reel-status", hidden: true });
  const body = h("div", { class: "hs-reel-body", "data-testid": "reel-body" });
  const el = h("section", { class: "hs-card hs-reel", "data-testid": "reel-card" },
    h("h2", { text: "Your progress reel" }),
    h("p", { class: "hs-text", text: "Simon watches up to 5 of your kept clips and joins the moments that tell the story of your progress into one short film." }),
    h("div", { class: "hs-run-row" }, make, panel.hint ? h("p", { class: "hs-hint", "data-testid": "reel-hint", text: panel.hint }) : null),
    status, body,
    h("p", { class: "hs-hint", "data-testid": "reel-disclosure", text: panel.disclosure }));
  return {
    el,
    status(kind, text) {
      status.hidden = !text;
      if (text) status.removeAttribute("hidden"); else status.setAttribute("hidden", "");
      status.setAttribute("data-kind", kind);
      status.textContent = text || "";
    },
    busy(on) { make.disabled = on || !panel.canMake; make.setAttribute("aria-busy", on ? "true" : "false"); },
    show(view) {
      clear(body);
      if (!view) return;
      if (view.failed) { body.append(h("p", { class: "hs-reason", "data-testid": "reel-failed", text: view.reason })); return; }
      const video = h("video", { class: "hs-video", controls: true, playsinline: true, preload: "metadata", src: view.videoUrl, "data-testid": "reel-video",
        "aria-label": "Your progress reel" });
      const moments = h("ol", { class: "hs-list", "data-testid": "reel-moments" }, view.moments.map((m, i) =>
        h("li", { class: "hs-obs", "data-testid": `reel-moment-${i}` },
          h("p", { class: "hs-text", text: m.text }),
          h("div", { class: "hs-cites" },
            h("span", { class: "hs-kind", text: m.role }),
            h("button", { type: "button", class: "hs-cite", "data-testid": `reel-cite-${i}`, "data-take": m.cite.take, "data-at-s": m.cite.at,
              disabled: !m.cite.clip, text: m.cite.text, "aria-label": `${m.cite.text}. Open this clip at that moment.`,
              onclick: m.cite.clip ? () => player.open(m.cite.clip, m.cite.at, m.cite.text) : null }),
            h("span", { class: "hs-tag", text: m.tag })))));
      body.append(
        ...(view.seeded ? [h("p", { class: "hs-seeded", "data-testid": "reel-seeded", text: view.seededLabel })] : []),
        video,
        h("p", { class: "hs-hint", "data-testid": "reel-length", text: view.lengthText }),
        h("a", { class: "btn", href: view.videoUrl, download: view.downloadName, "data-testid": "reel-download", text: "Download the reel" }),
        moments, ...(view.sent ? [renderReceipt(view.sent, { testid: "reel-sent" })] : []));
    },
  };
}
