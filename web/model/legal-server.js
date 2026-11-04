// The legal pages the server writes (/privacy, /terms, /accessibility, /biometric, /dmca, /sub-processors), read so the
// app can show them in its own theme (views/legal.js). Logic only: no DOM. The server stays the one source of the legal
// text; this turns its <main> into the page shape views/legal.js draws. Only headings, paragraphs, lists, tables, links,
// bold and code are kept, as plain text and {text, href} links; nothing from the page is ever inserted as HTML.

export const SERVER_PAGES = ["privacy", "terms", "accessibility", "biometric", "dmca", "sub-processors"];

// shown when the server's page does not load; the app holds no legal text of its own to show instead
export const LEGAL_UNAVAILABLE = { title: "This page did not load", body: "Check your connection, or open the page on its own.", link: "Open the full text" };

const VOID = new Set(["br", "hr", "img", "meta", "link", "input", "wbr"]);
const ENTITIES = { amp: "&", lt: "<", gt: ">", quot: '"', apos: "'", nbsp: "\u00a0" };   // numeric entities are decoded below

function decodeEntities(text) {
  return text.replace(/&(#x[0-9a-f]+|#\d+|[a-z]+);/gi, (all, e) => {
    if (e[0] === "#") {
      const code = e[1] === "x" || e[1] === "X" ? parseInt(e.slice(2), 16) : parseInt(e.slice(1), 10);
      return Number.isFinite(code) ? String.fromCodePoint(code) : all;
    }
    return ENTITIES[e.toLowerCase()] ?? all;
  });
}

/** An address Cloudflare's email protection hid (`data-cfemail` hex: the first byte is the key, XORed into the rest). */
export function decodeCfEmail(hex) {
  if (typeof hex !== "string" || !/^[0-9a-f]{4,}$/i.test(hex) || hex.length % 2) return "";
  const key = parseInt(hex.slice(0, 2), 16);
  let out = "";
  for (let i = 2; i < hex.length; i += 2) out += String.fromCharCode(parseInt(hex.slice(i, i + 2), 16) ^ key);
  return out;
}

/** Where a link on a legal page goes in the app: another legal page in the app, a decoded mail link, or a web page. */
export function mapHref(href) {
  if (typeof href !== "string" || !href) return null;
  const cf = href.match(/\/cdn-cgi\/l\/email-protection#([0-9a-f]+)/i);
  if (cf) {
    const email = decodeCfEmail(cf[1]);
    return email ? `mailto:${email}` : null;
  }
  if (/^(https?:|mailto:)/i.test(href)) return href;
  const local = href.replace(/^\.?\//, "").replace(/^#\//, "");
  if (SERVER_PAGES.includes(local) || /^(about|mission|safety|notices|whitepaper|architecture)$/.test(local)) return `#/${local}`;
  if (local === "" || local === "#/") return "#/";
  return null;   // anything else stays as text
}

function attrsOf(raw) {
  const out = {};
  for (const m of raw.matchAll(/([a-zA-Z_:][-a-zA-Z0-9_:.]*)\s*=\s*("([^"]*)"|'([^']*)')/g)) out[m[1].toLowerCase()] = decodeEntities(m[3] ?? m[4] ?? "");
  return out;
}

/** A small tree of `html`: {tag, attrs, children} and text strings. Tolerates unclosed tags the way pages need. */
export function parseTree(html) {
  const root = { tag: "#root", attrs: {}, children: [] };
  const stack = [root];
  for (const m of String(html).matchAll(/<!--[\s\S]*?-->|<(\/?)([a-zA-Z][a-zA-Z0-9]*)([^>]*?)(\/?)>|([^<]+)/g)) {
    if (m[5] !== undefined) { stack[stack.length - 1].children.push(decodeEntities(m[5])); continue; }
    if (!m[2]) continue;   // a comment
    const tag = m[2].toLowerCase();
    if (m[1]) {   // a closing tag: close up to its opener, if it is open
      const at = stack.map((n) => n.tag).lastIndexOf(tag);
      if (at > 0) stack.length = at;
      continue;
    }
    const node = { tag, attrs: attrsOf(m[3] || ""), children: [] };
    stack[stack.length - 1].children.push(node);
    if (!VOID.has(tag) && !m[4]) stack.push(node);
  }
  return root;
}

const squash = (s) => s.replace(/\s+/g, " ");
// the only elements whose words are kept inside a paragraph, list item or cell; anything else (a script, a style, a
// form) contributes nothing
const INLINE = new Set(["a", "strong", "b", "code", "em", "i", "span", "br", "small", "sup", "sub", "u", "abbr", "time"]);

/** The plain text of `node`, with Cloudflare-hidden addresses decoded. */
function textOf(node) {
  if (typeof node === "string") return node;
  if (node.attrs && node.attrs["data-cfemail"]) return decodeCfEmail(node.attrs["data-cfemail"]);
  if (node.tag === "br") return " ";
  if (node.tag !== "#root" && !INLINE.has(node.tag) && !["h1", "h2", "h3", "p", "li", "td", "th"].includes(node.tag)) return "";
  return node.children.map(textOf).join("");
}

/** A run of words: strings, {text, href} links, {strong} and {code}; empty pieces dropped, spaces collapsed. */
function inlineOf(node) {
  const out = [];
  for (const c of node.children) {
    if (typeof c === "string") out.push(squash(c));
    else if (c.tag === "a") {
      const href = mapHref(c.attrs.href);
      const text = squash(textOf(c)).trim();
      if (text) out.push(href ? { text, href } : text);
    } else if (c.tag === "strong" || c.tag === "b") out.push({ strong: squash(textOf(c)) });
    else if (c.tag === "code") out.push({ code: textOf(c) });
    else if (c.tag === "br") out.push(" ");
    else if (INLINE.has(c.tag)) out.push(...inlineOf(c));   // span, em, i and the like: their words only
  }
  return out.filter((p) => p !== "" && !(typeof p === "object" && !(p.text || p.strong || p.code)));
}

function cells(row, cellTag) {
  return row.children.filter((c) => typeof c !== "string" && (cellTag ? c.tag === cellTag : c.tag === "td" || c.tag === "th")).map(inlineOf);
}

function rowsOf(node) {
  return node.children.filter((c) => typeof c !== "string" && c.tag === "tr");
}

function tableOf(node) {
  const thead = node.children.find((c) => typeof c !== "string" && c.tag === "thead");
  const tbody = node.children.find((c) => typeof c !== "string" && c.tag === "tbody");
  const head = thead ? (rowsOf(thead)[0] ? cells(rowsOf(thead)[0]) : []) : [];
  const rows = [...(tbody ? rowsOf(tbody) : []), ...rowsOf(node)].map((r) => cells(r));
  return { table: { head, rows } };
}

function slug(text, used) {
  let id = squash(text).trim().toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "section";
  for (let n = 2; used.has(id); n += 1) id = `${id.replace(/-\d+$/, "")}-${n}`;
  used.add(id);
  return id;
}

/**
 * The page in `html` (a whole server legal page) as {key, route, title, lead, updated, contents, sections}, the
 * shape views/legal.js draws; null when it has no legal <main> or no title (then the app says the page did not load).
 */
export function parseLegalHtml(html, key) {
  const main = String(html).match(/<main\b[^>]*>([\s\S]*?)<\/main>/i);
  if (!main) return null;
  const tree = parseTree(main[1]);
  let title = "";
  let updated = "";
  const sections = [];
  const used = new Set();
  let current = { id: slug("intro", used), heading: "", body: [] };
  const flush = () => { if (current.heading || current.body.length) sections.push(current); };
  for (const node of tree.children) {
    if (typeof node === "string") continue;
    if (node.tag === "h1") { title = squash(textOf(node)).trim(); continue; }
    if (node.tag === "h2" || node.tag === "h3") {
      flush();
      const heading = squash(textOf(node)).trim();
      current = { id: slug(heading, used), heading, body: [] };
      continue;
    }
    if (node.tag === "p") {
      const text = squash(textOf(node)).trim();
      if (!updated && /^last updated\b/i.test(text)) { updated = text.replace(/\.$/, ""); continue; }
      const words = inlineOf(node);
      if (words.length) current.body.push(words);
      continue;
    }
    if (node.tag === "ul" || node.tag === "ol") {
      const items = node.children.filter((c) => typeof c !== "string" && c.tag === "li").map(inlineOf);
      if (items.length) current.body.push(node.tag === "ol" ? { steps: items } : { list: items });
      continue;
    }
    if (node.tag === "table") current.body.push(tableOf(node));
  }
  flush();
  if (!title) return null;
  return {
    key, route: key, title, lead: "", updated, sections,
    contents: sections.filter((s) => s.heading).map((s) => ({ id: s.id, heading: s.heading })),
  };
}
