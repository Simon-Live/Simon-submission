// `#/architecture`: the three diagrams of docs/ARCHITECTURE.md, drawn by the vendored Mermaid 11.17.2
// (web/vendor/mermaid, loaded on this page only). Words in model/architecture.js, drawing in views/architecture.js.
import { getArchitecture } from "./api.js";
import { clear, ensureCss } from "./ui.js";
import { ARCH_PAGE, MERMAID_SRC, architectureView, mermaidTheme } from "./model/architecture.js";
import { IMPACT_ROUTE } from "./model/impact.js";
import { renderArchitecture, showSvg, showFailed } from "./views/architecture.js";
import { showLoading } from "./progress.js";
import { tokenValue } from "./theme-colors.js";

let loading = null;
/** The Mermaid global, loaded once with a script tag (the bundle is a classic script, not a module). */
function loadMermaid() {
  if (globalThis.mermaid) return Promise.resolve(globalThis.mermaid);
  loading ||= new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = new URL(MERMAID_SRC, import.meta.url).href;
    s.onload = () => (globalThis.mermaid ? resolve(globalThis.mermaid) : reject(new Error("mermaid did not load")));
    s.onerror = () => { loading = null; reject(new Error("mermaid did not load")); };
    document.head.append(s);
  });
  return loading;
}

async function draw(diagrams, figures, isLive) {
  const mermaid = await loadMermaid();
  mermaid.initialize(mermaidTheme(tokenValue));
  for (const d of diagrams) {
    if (!isLive()) return;
    try {
      const { svg } = await mermaid.render(`${d.id}-svg`, d.source);
      if (isLive()) showSvg(figures[d.id], svg, d.title);
    } catch {
      if (isLive()) showFailed(figures[d.id], ARCH_PAGE.failed);
    }
  }
}

export function mountArchitecture(el) {
  let live = true;
  ensureCss("theme/impact.css", "data-impact-css");
  showLoading(el, "Loading the diagrams");
  getArchitecture().catch((err) => ({ unreachable: !(err && err.status === 404) })).then((doc) => {
    if (!live) return;
    clear(el);
    const diagrams = architectureView(doc);
    const empty = doc && doc.unreachable ? ARCH_PAGE.unreachable : ARCH_PAGE.missing;
    const { figures } = renderArchitecture(el, { ...ARCH_PAGE, missing: empty }, diagrams, IMPACT_ROUTE);
    if (diagrams.length) {
      draw(diagrams, figures, () => live).catch(() => {
        for (const d of diagrams) if (live) showFailed(figures[d.id], ARCH_PAGE.failed);
      });
    }
  });
  return () => { live = false; };
}
