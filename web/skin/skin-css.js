// Loads skin.css (the model picker and the import dialog) once, from wherever one of them mounts: the result picker,
// the import dialog and the "My 3D model" section of the Me page.
export const SKIN_CSS_MARKER = "data-simon-skin-css";

export function ensureSkinStyles(doc = document) {
  if (doc.querySelector(`link[${SKIN_CSS_MARKER}]`)) return;
  const link = doc.createElement("link");
  link.rel = "stylesheet";
  link.href = new URL("./skin.css", import.meta.url).href;
  link.setAttribute(SKIN_CSS_MARKER, "");
  doc.head.append(link);
}
