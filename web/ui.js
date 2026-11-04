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

const FOCUSABLE = /^(a|button|input|select|textarea|summary)$/i;
/**
 * Move keyboard focus to `el` after the control that had it was hidden or replaced (WCAG 2.4.3, a11y-copy B11 and R1).
 * A native control keeps its own tab stop; any other element gets tabindex -1 first, so it takes focus without joining
 * the tab order. Returns `el`.
 */
export function focusOn(el) {
  if (!el || typeof el.focus !== "function") return el;
  if (!FOCUSABLE.test(el.tagName || el.tag || "") && el.getAttribute("tabindex") === null) el.setAttribute("tabindex", "-1");
  el.focus();
  return el;
}

/** A finite number, else null. */
export const num = (v) => (typeof v === "number" && Number.isFinite(v) ? v : null);
