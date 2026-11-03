// Follow capture: the trainer and the camera side by side (docs/specs/follow-side-by-side.md, TICKET-291).
// Measures the row, asks web/model/follow-layout.js for the layout and box height, and puts both on the row
// (`data-layout`, `--follow-box-h`; rules in web/reference.css). When the countdown or the recording starts, the row
// is scrolled to just under the sticky header so both boxes are whole while the person moves.
import { followLayout } from "./model/follow-layout.js";

export const GAP = 12;
const BUSY = new Set(["counting", "recording"]);

const reducedMotion = () => typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;

/** The sticky header's height, 0 when there is none or it scrolls away with the page. */
export function headerHeight(doc = document) {
  const bar = doc.querySelector("header.bar") || doc.querySelector("header");
  if (!bar) return 0;
  const pos = getComputedStyle(bar).position;
  return pos === "sticky" || pos === "fixed" ? Math.ceil(bar.getBoundingClientRect().height) : 0;
}

/** @param root the capture box (or any element holding the `.ref-row`) @returns {destroy, apply} or null */
export function mountFollowSide(root) {
  const row = root.querySelector(".ref-row");
  if (!row) return null;
  const cam = row.querySelector(".cam");
  let lastWidth = -1;

  function apply() {
    const rowWidth = row.clientWidth;
    if (!rowWidth) return null;
    lastWidth = rowWidth;
    const ref = row.querySelector(".ref");
    const stage = ref && ref.querySelector(".ref-stage");
    const between = ref && stage ? Math.max(0, ref.getBoundingClientRect().height - stage.getBoundingClientRect().height) : 0;
    const out = followLayout({ width: window.innerWidth, height: window.innerHeight, rowWidth, headerH: headerHeight(), gap: GAP, between });
    row.dataset.layout = out.layout;
    row.dataset.shape = out.aspect < 1 ? "tall" : "wide";
    row.style.setProperty("--follow-box-h", `${out.boxH}px`);
    row.style.setProperty("--follow-gap", `${GAP}px`);
    return out;
  }

  /** Bring the row under the sticky header unless both boxes are already whole on screen. */
  function frame() {
    const top = row.getBoundingClientRect().top;
    const head = headerHeight();
    const boxes = [cam, row.querySelector(".ref-stage")].filter(Boolean).map((b) => b.getBoundingClientRect());
    const whole = boxes.every((b) => b.top >= head && b.bottom <= window.innerHeight);
    if (whole) return;
    window.scrollTo({ top: Math.max(0, window.scrollY + top - head - 8), behavior: reducedMotion() ? "auto" : "smooth" });
  }

  const onResize = () => apply();
  window.addEventListener("resize", onResize);
  // the row's width, or the header's height (the test-server banner arrives after the first paint), changes the boxes
  const bar = document.querySelector("header.bar") || document.querySelector("header");
  let lastHead = -1;
  const ro = typeof ResizeObserver === "function" ? new ResizeObserver(() => {
    const head = headerHeight();
    if (row.clientWidth !== lastWidth || head !== lastHead) { lastHead = head; apply(); }
  }) : null;
  if (ro) { ro.observe(row); if (bar) ro.observe(bar); }
  let was = cam ? cam.dataset.state : "";
  const mo = cam && typeof MutationObserver === "function" ? new MutationObserver(() => {
    const now = cam.dataset.state;
    if (BUSY.has(now) && !BUSY.has(was)) frame();
    was = now;
  }) : null;
  if (mo) mo.observe(cam, { attributes: true, attributeFilter: ["data-state"] });
  apply();

  return {
    apply,
    frame,
    destroy() {
      window.removeEventListener("resize", onResize);
      if (ro) ro.disconnect();
      if (mo) mo.disconnect();
      delete row.dataset.layout;
    },
  };
}
