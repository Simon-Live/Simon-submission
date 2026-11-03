// `#/about` and `#/safety`: the business pages for simon.live (model/legal.js words,
// views/legal.js drawing). Static words: nothing is fetched.
import { clear, ensureCss } from "./ui.js";
import { PAGES, legalPage } from "./model/legal.js";
import { renderLegal } from "./views/legal.js";

export function mountLegal(el, key) {
  const page = legalPage(key);
  if (!page) return () => {};
  ensureCss("theme/legal.css", "data-legal-css");
  clear(el);
  const others = Object.values(PAGES).filter((p) => p.route !== page.route).map((p) => ({ route: p.route, title: p.title }));
  renderLegal(el, page, others);
  window.scrollTo(0, 0);
  return () => {};
}
