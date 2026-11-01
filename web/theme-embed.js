// Puts the brand theme on a same-origin frame (Part 6's catalog page in the Watch screen): adds tokens.css and
// theme/catalog-embed.css to the frame's document once it loads. A frame that cannot be reached keeps its look.
const SHEETS = ["theme/tokens.css", "theme/catalog-embed.css"];

export function themeFrame(frame) {
  const apply = () => {
    let doc = null;
    try { doc = frame.contentDocument; } catch { return; }
    if (!doc || !doc.head || doc.head.querySelector("link[data-simon-theme]")) return;
    for (const file of SHEETS) {
      const link = doc.createElement("link");
      link.rel = "stylesheet";
      link.href = new URL(file, document.baseURI).href;
      link.dataset.simonTheme = "";
      doc.head.append(link);
    }
  };
  frame.addEventListener("load", apply);
  apply();
}
