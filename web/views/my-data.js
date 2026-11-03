// The "Download my data" card of the Me page from plain data (words come in as `t`), styled by theme/auth.css.
// No fetching and no storage: `on.download()` resolves to { ok, text }.
import { h, clear } from "../ui.js";

/** Draw the card into `host` (a section beside Delete my data). Returns { button, note }. */
export function renderDownload(host, { t }, on) {
  clear(host).classList.add("au-card");
  host.setAttribute("data-testid", "me-export-card");
  const note = h("p", { class: "au-note", role: "status", "aria-live": "polite", "data-testid": "me-export-note", text: "" });
  const button = h("button", { class: "btn secondary au-submit", type: "button", "data-testid": "me-export", text: t.button });
  button.addEventListener("click", async () => {
    button.disabled = true;
    note.setAttribute("data-tone", "ok");
    note.textContent = t.working;
    const out = await on.download();
    button.disabled = false;
    note.setAttribute("data-tone", out.ok ? "ok" : "bad");
    note.textContent = out.text;
  });
  host.append(h("h2", { text: t.title }), h("p", { class: "au-hint", text: t.lead }), button, note);
  return { button, note };
}
