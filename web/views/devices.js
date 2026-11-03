// The signed-in devices card from plain data (words come in as `t`, rows from model/devices.js), styled by
// theme/profile.css on the brand tokens. No fetching and no storage.
import { h, clear } from "../ui.js";

const heading = (t) => h("h2", { class: "dv-title", "data-testid": "devices-title", tabindex: "-1", text: t.title });

/** The load failed (not a refusal). `onRetry` loads again. */
export function renderDevicesError(host, { t }, onRetry) {
  clear(host).append(heading(t),
    h("div", { class: "dv-error", "data-testid": "devices-error" },
      h("p", { class: "pf-hint", text: t.errorBody }),
      h("button", { type: "button", class: "btn secondary", "data-testid": "devices-retry", text: t.retry, onclick: onRetry })));
}

/** Still loading. */
export function renderDevicesLoading(host, { t }) {
  clear(host).append(heading(t), h("p", { class: "pf-loading", "data-testid": "devices-loading", text: t.loading }));
}

/**
 * The list. `vm`: { t, rows (from normalizeRows, with `line` and `label`), note, noteBad }. `on`: { end(row), endOthers() }, each async; the glue reloads the list. The status line is a polite live region, so a screen reader hears the outcome.
 */
export function renderDevices(host, vm, on) {
  const { t, rows } = vm;
  const note = h("p", { class: "pf-note", role: "status", "aria-live": "polite", "data-testid": "devices-note", text: vm.note || "" });
  if (vm.noteBad) note.setAttribute("data-tone", "bad");
  const list = h("ul", { class: "pf-list dv-list", "data-testid": "devices-list" }, ...rows.map((r, i) => {
    const left = h("span", { class: "dv-main" },
      h("span", { class: "dv-name", "data-testid": `device-name-${i}`, text: r.device }),
      r.current ? h("span", { class: "dv-badge", "data-testid": `device-current-${i}`, text: t.thisDevice }) : null,
      r.line ? h("span", { class: "pf-row-line", text: r.line }) : null);
    const button = r.current ? null : h("button", {
      type: "button", class: "btn secondary dv-end", "data-testid": `device-end-${i}`, "aria-label": r.label, text: t.signOut,
      onclick: async (ev) => { ev.currentTarget.disabled = true; await on.end(r); },
    });
    return h("li", { class: "pf-row dv-row", "data-testid": `device-${i}`, "data-current": r.current ? "true" : "false" }, left, button);
  }));
  const everywhere = rows.some((r) => !r.current)
    ? h("button", { type: "button", class: "btn secondary dv-end-others", "data-testid": "devices-end-others", text: t.signOutOthers,
        onclick: async (ev) => { ev.currentTarget.disabled = true; await on.endOthers(); } })
    : h("p", { class: "pf-empty", "data-testid": "devices-empty", text: t.empty });
  clear(host).append(heading(t), h("p", { class: "pf-hint", text: t.lead }), list, everywhere,
    h("p", { class: "pf-hint", text: t.hint }), note);
}
