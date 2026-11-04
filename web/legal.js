// `#/about`, `#/safety` and the legal pages (`#/privacy`, `#/terms`, ...): the business pages for simon.live (model/legal.js
// words, views/legal.js drawing). A legal page's text comes only from the server (/privacy, /terms and the others,
// part7/legal_pages.py), fetched and shown in the app's theme (model/legal-server.js). If it does not load, the app says
// so and links the server's page; it has no legal text of its own to show.
import { clear, ensureCss } from "./ui.js";
import { PAGES, legalPage } from "./model/legal.js";
import { SERVER_PAGES, LEGAL_UNAVAILABLE, parseLegalHtml } from "./model/legal-server.js";
import { renderLegal, renderLegalUnavailable } from "./views/legal.js";

const others = (route) => Object.values(PAGES).filter((p) => p.route !== route).map((p) => ({ route: p.route, title: p.title }));

function show(el, page) {
  clear(el);
  renderLegal(el, page, others(page.route));
  window.scrollTo(0, 0);
}

/** The server's legal page for `key`, read for the app, or null (no such page here, a network error, an odd answer). */
export async function serverPage(key, fetchFn = globalThis.fetch) {
  if (!SERVER_PAGES.includes(key) || typeof fetchFn !== "function") return null;
  try {
    const res = await fetchFn(key, { credentials: "same-origin", headers: { Accept: "text/html" } });
    if (!res || !res.ok || !/text\/html/i.test(res.headers?.get?.("content-type") || "")) return null;
    return parseLegalHtml(await res.text(), key);
  } catch {
    return null;
  }
}

export function mountLegal(el, key, fetchFn) {
  ensureCss("theme/legal.css", "data-legal-css");
  if (!SERVER_PAGES.includes(key)) {
    const page = legalPage(key);
    if (page) show(el, page);
    return () => {};
  }
  let live = true;
  serverPage(key, fetchFn).then((page) => {
    if (!live) return;
    if (page) return show(el, page);
    clear(el);
    renderLegalUnavailable(el, key, LEGAL_UNAVAILABLE);
    window.scrollTo(0, 0);
  });
  return () => { live = false; };
}
