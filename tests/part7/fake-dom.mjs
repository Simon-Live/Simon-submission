// A tiny fake DOM for the voice, second-opinion and language-picker unit tests (no jsdom in this repo).
// Supports what web/ui.js `h` and those modules use: attributes, children, events, [data-testid="x"] queries.
export class Node extends EventTarget {
  constructor() { super(); this.children = []; this.parent = null; }
  append(...kids) { for (const k of kids) { k.parent = this; this.children.push(k); } }
  prepend(...kids) { for (const k of kids) k.parent = this; this.children.unshift(...kids); }
  replaceChildren(...kids) { this.children = []; this.append(...kids); }
  get parentElement() { return this.parent; }
  remove() { if (this.parent) { this.parent.children = this.parent.children.filter((c) => c !== this); this.parent = null; } }
  after(...kids) {
    const p = this.parent;
    if (!p) return;
    const at = p.children.indexOf(this) + 1;
    for (const k of kids) k.parent = p;
    p.children.splice(at, 0, ...kids);
  }
}
export class Text extends Node {
  constructor(t) { super(); this.data = t; }
  get textContent() { return this.data; }
}
export class El extends Node {
  constructor(tag) { super(); this.tag = tag; this.attrs = {}; this._text = null; this.value = ""; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  removeAttribute(k) { delete this.attrs[k]; }
  set className(v) { this.attrs.class = v; }
  get className() { return this.attrs.class || ""; }
  set textContent(v) { this._text = String(v); this.children = []; }
  get textContent() { return this._text !== null && !this.children.length ? this._text : this.children.map((c) => c.textContent).join(""); }
  click() { this.dispatchEvent(new Event("click")); }
  matches(sel) {
    const parts = [...sel.matchAll(/\[([\w-]+)(?:="([^"]*)")?\]/g)];
    return parts.length > 0 && parts.every(([, k, v]) => (v === undefined ? k in this.attrs : this.attrs[k] === v));
  }
  querySelectorAll(sel) {
    const out = [];
    const walk = (n) => { for (const c of n.children) { if (c instanceof El) { if (c.matches(sel)) out.push(c); walk(c); } } };
    walk(this);
    return out;
  }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
}

/** Installs document, Node and localStorage globals; returns helpers. */
export function installDom() {
  const store = new Map();
  const head = new El("head");
  globalThis.Node = Node;
  globalThis.document = {
    createElement: (t) => new El(t),
    createTextNode: (t) => new Text(t),
    head,
    querySelector: (sel) => head.querySelector(sel.replace(/^link/, "")),
  };
  globalThis.localStorage = {
    getItem: (k) => (store.has(k) ? store.get(k) : null),
    setItem: (k, v) => { store.set(k, String(v)); },
  };
  return { store, head };
}

export const all = (n, out = []) => { out.push(n); (n.children || []).forEach((c) => all(c, out)); return out; };
export const find = (root, testid) => root.querySelector(`[data-testid="${testid}"]`);
export const findAll = (root, testid) => root.querySelectorAll(`[data-testid="${testid}"]`);
