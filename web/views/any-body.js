// Any body (docs/specs/any-body.md): the DOM of the view. No fetch, no storage; web/any-body.js wires it.

function h(tag, attrs = {}, ...kids) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === false || v == null) continue;
    if (k === "text") node.textContent = v; else node.setAttribute(k, v === true ? "" : String(v));
  }
  for (const kid of kids) if (kid) node.append(kid);
  return node;
}

export function ensureStyles() {
  if (document.querySelector("link[data-simon-any-body-css]")) return;
  const link = h("link", { rel: "stylesheet", href: new URL("../skin/any-body.css", import.meta.url).href, "data-simon-any-body-css": true });
  document.head.append(link);
}

const ICON_PLAY = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5.5v13l11-6.5z"/></svg>';
const ICON_PAUSE = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 5h3.5v14H7zM13.5 5H17v14h-3.5z"/></svg>';

/** The view's frame: header, the one honest line, the row of figures, the controls, the credit line. */
export function renderShell(root, { duration, backHref, text: TEXT }) {
  const wrap = h("section", { class: "ab simon-viewer", "data-testid": "any-body", "aria-label": TEXT.title });
  const head = h("header", { class: "ab-head" },
    h("h2", { text: TEXT.title }),
    backHref ? h("a", { class: "sr-btn ab-back", href: backHref, text: TEXT.back }) : null);
  const intro = h("p", { class: "ab-intro", text: TEXT.intro });
  const note = h("p", { class: "ab-note", "data-testid": "any-body-note", text: TEXT.honest });
  const grid = h("div", { class: "ab-grid", role: "list", "data-testid": "any-body-grid" });
  const pager = h("div", { class: "ab-pager sr-seg", role: "group", "aria-label": TEXT.pager, "data-testid": "any-body-pager", hidden: true });
  const play = h("button", { type: "button", class: "sr-btn ab-play", "data-testid": "any-body-play", "aria-label": TEXT.play, "data-playing": "false" });
  play.innerHTML = ICON_PLAY;
  const scrub = h("input", { type: "range", class: "ab-scrub", "data-testid": "any-body-scrub", min: 0, max: duration, step: "any", value: 0, "aria-label": TEXT.scrub });
  const clock = h("output", { class: "ab-clock", "data-testid": "any-body-clock", "data-t": "0", text: "0.0 s" });
  const bar = h("div", { class: "ab-bar" }, play, scrub, clock);
  const credit = h("p", { class: "ab-credit", "data-testid": "any-body-credit", "aria-live": "polite", hidden: true });
  wrap.append(head, intro, note, grid, pager, bar, credit);
  root.append(wrap);
  return { wrap, grid, pager, play, scrub, clock, credit };
}

export function setPlaying(play, playing, TEXT) {
  if (play.getAttribute("data-playing") === String(playing)) return;
  play.setAttribute("data-playing", String(playing));
  play.setAttribute("aria-label", playing ? TEXT.pause : TEXT.play);
  play.innerHTML = playing ? ICON_PAUSE : ICON_PLAY;
}

/** One figure's cell: the stage host, the name under it and a slot for its error. */
export function renderCell(grid, index, name) {
  const cell = h("figure", { class: "ab-fig", role: "listitem", "data-testid": `any-body-fig-${index}`, "data-state": "loading", "data-skin-id": "", "data-skin-kind": "", "data-frame": "", "data-drawn-frame": "" });
  const stage = h("div", { class: "ab-stage" });
  const caption = h("figcaption", { class: "ab-name", "data-testid": `any-body-name-${index}`, text: name });
  const error = h("p", { class: "ab-error", role: "status", "data-testid": `any-body-error-${index}`, hidden: true });
  cell.append(stage, caption, error);
  grid.append(cell);
  return { cell, stage, error };
}

export function showError(slot, text) {
  slot.cell.setAttribute("data-state", "error");
  slot.error.textContent = text;
  slot.error.hidden = false;
}

/** Page switch buttons for a narrow screen; `onPick(pageIndex)` scrolls that page into view. */
export function renderPager(pager, pages, onPick) {
  pager.textContent = "";
  pager.hidden = pages.length < 2;
  pages.forEach((page, i) => {
    const label = page.length === 1 ? String(page[0] + 1) : `${page[0] + 1} to ${page[page.length - 1] + 1}`;
    const b = h("button", { type: "button", class: "sr-btn", "data-testid": `any-body-page-${i}`, "aria-pressed": String(i === 0), text: label });
    b.addEventListener("click", () => onPick(i));
    pager.append(b);
  });
}

export function markPage(pager, current) {
  [...pager.children].forEach((b, i) => b.setAttribute("aria-pressed", String(i === current)));
}

export function plainMessage(root, text, backHref, backLabel) {
  root.append(h("section", { class: "ab simon-viewer", "data-testid": "any-body" },
    h("p", { class: "ab-intro", role: "status", "data-testid": "any-body-message", text }),
    backHref ? h("a", { class: "sr-btn ab-back", href: backHref, text: backLabel }) : null));
}
