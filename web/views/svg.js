// A tiny SVG element builder shared by the history views. Attributes are set as strings; a string child is the text.
const SVG_NS = "http://www.w3.org/2000/svg";

export function svg(tag, attrs = {}, ...kids) {
  const el = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, String(v));
  for (const kid of kids) {
    if (typeof kid === "string") el.textContent = kid;
    else if (kid) el.append(kid);
  }
  return el;
}
