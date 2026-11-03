// "Takes on this movement" from plain data (model/takes-on.js), on the Me page's row styles (theme/auth.css). No
// fetching and no storage.
import { h, clear } from "../ui.js";

const score = (s) => (s ? [h("strong", { class: "au-score", "data-tone": s.tone, "data-testid": "takes-on-score", text: s.figures }),
  s.letter ? h("span", { class: "au-grade", "data-testid": "takes-on-grade", text: s.letter }) : null] : []);

const open = (r, testid) => (r.href ? h("a", { class: "au-open", href: r.href, "data-testid": testid, text: r.link }) : null);

function mineItem(r, i, t) {
  return h("li", { class: "au-take", "data-testid": `takes-on-mine-${i}`, "data-job": r.jobId },
    h("div", { class: "au-take-head" }, ...score(r.score), r.score ? null : h("span", { class: "au-kind", text: r.state || t.noScore }),
      r.score && r.state ? h("span", { class: "au-kind", text: r.state }) : null, r.when ? h("time", { class: "au-when", text: r.when }) : null),
    open(r, "takes-on-mine-open"));
}

function sharedItem(r, i) {
  return h("li", { class: "au-take", "data-testid": `takes-on-shared-${i}` },
    h("div", { class: "au-take-head" }, ...score(r.score), h("span", { class: "au-kind", text: r.name }),
      r.board ? h("span", { class: "au-when", text: r.board }) : null, r.when ? h("time", { class: "au-when", text: r.when }) : null),
    open(r, "takes-on-shared-open"));
}

/** The section's two cards into `host`; `vm` from model `takesOnView` plus `t` (the words). */
export function renderTakesOn(host, vm) {
  const { t } = vm;
  clear(host);
  const mine = h("section", { class: "au-card", "data-testid": "takes-on-mine" }, h("h2", { text: t.mineTitle }),
    vm.mine.length ? h("ol", { class: "au-takes", "data-testid": "takes-on-mine-list" }, ...vm.mine.map((r, i) => mineItem(r, i, t)))
      : h("p", { class: "au-hint", "data-testid": "takes-on-mine-empty", text: t.mineEmpty }),
    vm.hint ? h("p", { class: "au-hint", "data-testid": "takes-on-signed-out", text: vm.hint }) : null,
    vm.followers ? h("a", { class: "au-open", href: vm.followers, "data-testid": "takes-on-followers", text: t.followers }) : null);
  const shared = h("section", { class: "au-card", "data-testid": "takes-on-shared" }, h("h2", { text: t.sharedTitle }),
    vm.shared.length ? h("ol", { class: "au-takes", "data-testid": "takes-on-shared-list" }, ...vm.shared.map(sharedItem))
      : h("p", { class: "au-hint", "data-testid": "takes-on-shared-empty", text: t.sharedEmpty }));
  host.append(mine, shared);
}

/** A load that failed: one line, so the rest of the watch page stays as it is. */
export function renderTakesOnError(host, { t }) {
  clear(host).append(h("p", { class: "au-hint", role: "status", "data-testid": "takes-on-error", text: t.loadFailed }));
}

/** The Me page card of the takes this browser sent; nothing at all when there are none. */
export function renderDeviceTakes(host, { t, rows }) {
  clear(host);
  if (!rows.length) return;
  host.append(h("section", { class: "au-card", "data-testid": "device-takes" }, h("h2", { text: t.deviceTitle }),
    h("ol", { class: "au-takes", "data-testid": "device-takes-list" }, ...rows.map((r, i) => h("li", { class: "au-take", "data-testid": `device-take-${i}`, "data-job": r.jobId },
      h("div", { class: "au-take-head" }, h("span", { class: "au-kind", text: r.name }), r.when ? h("time", { class: "au-when", text: r.when }) : null),
      open(r, "device-take-open"))))));
}
