// Small DOM helpers shared by the web screens (no framework, no build step).

export function h(tag, attrs = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === false || v == null) continue;
    if (k === "class") el.className = v;
    else if (k === "text") el.textContent = v;
    else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
    else if (v === true) el.setAttribute(k, "");
    else el.setAttribute(k, String(v));
  }
  for (const kid of kids.flat()) {
    if (kid == null || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return el;
}

export function clear(el) {
  el.replaceChildren();
  return el;
}

/** m:ss for a number of seconds. */
export function mmss(sec) {
  const s = Math.max(0, Math.floor(sec));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

/** A titled state block: loading, empty, error, not found. */
export function stateBlock(testid, title, body, ...actions) {
  return h("section", { class: "state", "data-testid": testid },
    h("h2", { text: title }),
    body ? h("p", { text: body }) : null,
    actions.length ? h("div", { class: "row" }, actions) : null);
}

export function linkButton(href, label, testid, kind = "secondary") {
  return h("a", { class: `btn ${kind}`, href, "data-testid": testid, text: label });
}

/** Adds `<link rel=stylesheet>` for a css file beside this module once; `marker` is the data attribute that tags it. */
export function ensureCss(file, marker) {
  if (document.querySelector(`link[${marker}]`)) return;
  const link = document.createElement("link");
  link.rel = "stylesheet";
  link.href = new URL(file, import.meta.url).href;
  link.setAttribute(marker, "");
  document.head.append(link);
}

/** A finite number, else null. */
export const num = (v) => (typeof v === "number" && Number.isFinite(v) ? v : null);
