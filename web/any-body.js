// Any body (docs/specs/any-body.md): one take's normalized motion on several body models at once, from one clock.
// Each figure has its own stage, so a model that fails shows a named error in its own slot while the others play.
import { createClock, normalizeReplay, ensureStyles as ensureResultStyles, YOU_COLOR } from "./compare.js";
import { getFixtureResult, getReplay } from "./api.js";
import { listModels } from "./skin/catalog.js";
import { createChooser } from "./skin/picker.js";
import { TEXT, bodiesFor, perView, pagesOf, poseAt, slotError } from "./model/any-body.js";
import { ensureStyles, renderShell, renderCell, renderPager, markPage, setPlaying, showError, plainMessage } from "./views/any-body.js";

const realJob = (job) => (job && job !== "fixture" ? job : null);

/**
 * Mount the view into `root` for a replay `model` (normalizeReplay). `entries` (the library and the caller's models) are
 * fetched when not given. `deps` replaces the skin loaders in tests. Resolves {el, cells(), seek, play, pause, destroy}.
 */
export async function mountAnyBody(root, { model, job = null, entries = null, fetchImpl, deps = {}, backHref = null } = {}) {
  ensureResultStyles();
  ensureStyles();
  const stageMod = await import("./viewer3d.js").catch(() => null);
  if (!stageMod || !stageMod.webglAvailable()) { plainMessage(root, TEXT.noWebgl, backHref, TEXT.back); return null; }
  let list = entries;
  if (!list) {
    try { const found = await listModels(fetchImpl); list = [...found.library, ...found.mine]; } catch { list = []; }
  }
  const bodies = bodiesFor(list);
  const ui = renderShell(root, { duration: model.duration, backHref, text: TEXT });
  const cells = bodies.map((body, i) => ({ body, slot: renderCell(ui.grid, i, body.name), stage: null, chooser: null, frame: null }));
  const jobId = realJob(job);
  const credits = () => [...new Set(cells.flatMap((c) => (c.chooser ? c.chooser.credits() : [])).filter(Boolean))];

  // ---- the clock: one frame of the take, drawn on every figure ----
  const draw = () => {
    const { frame, pose, dim } = poseAt(model, clock.t);
    cells.forEach((c) => {
      if (!c.stage) return;
      c.stage.setPoses([pose], [dim]);
      c.frame = frame;
      c.slot.cell.setAttribute("data-frame", String(frame));
    });
  };
  const onClock = (t, playing) => {
    ui.clock.textContent = `${t.toFixed(1)} s`;
    ui.clock.setAttribute("data-t", String(t));
    ui.scrub.value = String(t);
    setPlaying(ui.play, playing, TEXT);
    draw();
  };
  const clock = createClock(model.duration, onClock);
  let raf = 0;
  const loop = () => { raf = 0; if (clock.tick()) raf = requestAnimationFrame(loop); };
  const start = () => { if (!raf) raf = requestAnimationFrame(loop); };
  ui.play.addEventListener("click", () => { clock.toggle(); if (clock.playing) start(); });
  ui.scrub.addEventListener("input", () => clock.seek(Number(ui.scrub.value)));

  // ---- the stages ----
  const stamp = (c, stats) => {
    const skin = stats && stats.skin;
    c.slot.cell.setAttribute("data-skin-kind", skin ? String(skin.kind) : "skeleton");
    c.slot.cell.setAttribute("data-skin-id", skin ? String(skin.id) : c.body.choice);
    if (c.frame != null) c.slot.cell.setAttribute("data-drawn-frame", String(c.frame));
  };
  cells.forEach((c) => {
    c.slot.cell.setAttribute("data-skin-id", c.body.choice);
    c.slot.cell.setAttribute("data-skin-kind", "skeleton");
    try {
      c.stage = stageMod.createStage(c.slot.stage, { joints: model.joints, bones: model.bones, tracks: [{ color: YOU_COLOR, ghostInOverlay: false, label: c.body.name }] });
    } catch {
      showError(c.slot, slotError(c.body.name));
      return;
    }
    c.stage.canvas.setAttribute("aria-label", `${c.body.name}, 3D view. Drag to rotate, pinch or scroll to zoom.`);
    c.stage.canvas.setAttribute("data-testid", `any-body-canvas-${cells.indexOf(c)}`);
    c.stage.setView("front");
    c.stage.onRender(() => stamp(c, c.stage.drawStats()[0]));
    c.chooser = createChooser({ stage: c.stage, tracks: [{ role: "you", label: c.body.name, job: jobId, person: "you" }], job: jobId, entries: list, deps });
  });
  draw();
  const settled = Promise.all(cells.map(async (c) => {
    if (!c.chooser) return;
    let res;
    try { res = await c.chooser.choose(0, c.body.choice, { remember: false }); } catch { res = { ok: false }; }
    if (res.ok) c.slot.cell.setAttribute("data-state", "ready"); else showError(c.slot, slotError(c.body.name));
    c.stage.render();
  }));
  settled.then(() => {
    const text = credits().join(" ");
    ui.credit.textContent = text;
    ui.credit.hidden = !text;
    ui.wrap.setAttribute("data-ready", "true");
  });

  // ---- narrow screens: two figures at a time, a swipe or the switch moves on ----
  let page = 0;
  let pages = [];
  const layout = () => {
    const per = perView(ui.wrap.clientWidth || window.innerWidth, cells.length);
    ui.grid.style.setProperty("--ab-per", String(per));
    ui.wrap.setAttribute("data-per", String(per));
    pages = pagesOf(cells.length, per);
    renderPager(ui.pager, pages, (i) => { ui.grid.scrollTo({ left: i * ui.grid.clientWidth, behavior: "auto" }); });
    page = Math.min(page, pages.length - 1);
    markPage(ui.pager, page);
  };
  const onScroll = () => {
    const width = ui.grid.clientWidth || 1;
    const now = Math.min(pages.length - 1, Math.max(0, Math.round(ui.grid.scrollLeft / width)));
    if (now !== page) { page = now; markPage(ui.pager, page); }
  };
  ui.grid.addEventListener("scroll", onScroll, { passive: true });
  const ro = new ResizeObserver(layout);
  ro.observe(ui.wrap);
  layout();
  onClock(0, false);

  return {
    el: ui.wrap,
    ready: settled,
    cells: () => cells.map((c) => ({ choice: c.body.choice, name: c.body.name, state: c.slot.cell.getAttribute("data-state") })),
    time: () => clock.t,
    seek(t) { clock.seek(Number(t)); },
    play() { clock.play(); start(); },
    pause() { clock.pause(); },
    destroy() {
      if (raf) cancelAnimationFrame(raf);
      ro.disconnect();
      cells.forEach((c) => { if (c.stage) c.stage.dispose(); });
      ui.wrap.remove();
    },
  };
}

/** `#/any-body/<job>`: loads the take's replay and mounts the view. Returns the cleanup function. */
export function mountAnyBodyRoute(el, job) {
  let live = true;
  let handle = null;
  const back = `#/result/${encodeURIComponent(job)}`;
  const load = job === "fixture" ? getFixtureResult().then((r) => r.replay) : getReplay(job);
  load.then((replay) => {
    if (!live) return;
    let model = null;
    try { model = normalizeReplay(replay); } catch { model = null; }
    if (!model) { plainMessage(el, TEXT.noReplay, back, TEXT.back); return; }
    return mountAnyBody(el, { model, job, backHref: back }).then((h) => { if (live) handle = h; else if (h) h.destroy(); });
  }).catch(() => { if (live) plainMessage(el, TEXT.noReplay, back, TEXT.back); });
  return () => { live = false; if (handle) handle.destroy(); };
}

/** The Any body button in a result's 3D view tools (result.js). Nothing when the view has no tools row. */
export function mountAnyBodyLink(compareEl, job) {
  const tools = compareEl && compareEl.querySelector(".sr-tools");
  if (!tools || tools.querySelector("[data-testid=any-body-open]")) return null;
  const a = document.createElement("a");
  a.className = "sr-btn ab-open";
  a.setAttribute("data-testid", "any-body-open");
  a.href = `#/any-body/${encodeURIComponent(job || "fixture")}`;
  a.textContent = TEXT.open;
  tools.append(a);
  return a;
}
