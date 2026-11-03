// The site footer on every screen (docs/specs/version-footer.md, TICKET-326): the live version behind one tap, the
// app's links, where the source and feedback go, and the Meta model credit. The data comes from GET api/version; a failed fetch shows "Version
// unavailable" and the rest of the footer, and never throws into the page.
import { getVersion } from "./api.js";
import { h } from "./ui.js";
import { copyText } from "./share-card.js";
import { FOOTER_TEXT, FOOTER_LINKS, footerBuild, footerRows, buildInfoText, buildLabel } from "./model/footer.js";

/** The version block: a <details> whose summary is the environment, build date and short sha; or the unavailable line. */
export function versionBlock(fb, copy = copyText) {
  const t = FOOTER_TEXT;
  if (!fb) return h("p", { class: "sf-build sf-unknown", "data-testid": "footer-version", text: t.unavailable });
  const summary = h("summary", { "data-testid": "footer-version", "aria-label": `${t.detailsLabel}: ${[fb.environment, fb.version && `${t.build} ${buildLabel(fb.version)}`, fb.short].filter(Boolean).join(", ")}` },
    fb.environment ? h("span", { class: "sf-env", "data-testid": "footer-env", text: fb.environment }) : null,
    fb.version ? h("span", { class: "sf-version", "data-testid": "footer-build-name" }, `${t.build} ${fb.version} `,
      h("span", { class: "sf-note", text: t.buildNote })) : null,
    fb.short ? h("code", { class: "sf-sha", "data-testid": "footer-sha", text: fb.short }) : null);
  const list = h("dl", { class: "sf-rows" }, ...footerRows(fb).flatMap(([k, v]) => [h("dt", { text: k }), h("dd", { text: v })]));
  const status = h("p", { class: "sf-status", role: "status", "aria-live": "polite", "data-testid": "footer-copy-status", text: "" });
  const button = h("button", { type: "button", class: "btn secondary sf-copy", "data-testid": "footer-copy", text: t.copy,
    onclick: async () => { status.textContent = (await copy(buildInfoText(fb))) ? t.copied : t.copyFailed; } });
  const panel = h("div", { class: "sf-details", "data-testid": "footer-build-details" }, list, h("div", { class: "sf-actions" }, button, status));
  return h("details", { class: "sf-build", "data-testid": "footer-build" }, summary, panel);
}

/** The links row: app pages only. */
export function linksNav() {
  return h("nav", { class: "sf-links", "aria-label": FOOTER_TEXT.linksLabel },
    ...FOOTER_LINKS.map((l) => h("a", { href: l.href, "data-testid": l.testid, text: l.label })));
}

/** Draw the whole footer into `el` for `build` (the api/version body, or null when it did not load); `pending` keeps
 * the version slot empty while api/version is still on its way, so the links show at once. */
export function renderFooter(el, build, copy = copyText, { pending = false } = {}) {
  const version = pending ? h("p", { class: "sf-build", "data-testid": "footer-version-pending" }) : versionBlock(footerBuild(build), copy);
  const inner = h("div", { class: "sf-inner" }, version, linksNav(),
    h("p", { class: "sf-credit", "data-testid": "footer-feedback", text: FOOTER_TEXT.feedback }),
    h("p", { class: "sf-credit", "data-testid": "footer-source", text: FOOTER_TEXT.source }),
    h("p", { class: "sf-credit", "data-testid": "footer-credit", text: FOOTER_TEXT.credit }));
  el.replaceChildren(inner);
  el.hidden = false;
  return el;
}

/** Fill the footer once at start. Resolves to true when the version loaded; never rejects. */
export async function mountFooter(el, fetchVersion = getVersion) {
  if (!el) return false;
  try { renderFooter(el, null, copyText, { pending: true }); } catch { /* the full render below tries again */ }
  let build = null;
  try { build = await fetchVersion(); } catch { build = null; }
  try { renderFooter(el, build); } catch { return false; }
  return Boolean(footerBuild(build));
}
