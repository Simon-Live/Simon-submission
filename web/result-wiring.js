// The result screen's additions on the redesign (docs/specs/result-redesign-additions.md): fetch the job's models,
// skeleton and mesh index, build their models (web/model/) and hand them to the views (web/views/). Each part is
// optional: a missing file, an old server or a failed load leaves the screen as it was. Also the stage helper that
// keeps the video and the 3D view in sight when a row seeks them (R5, TICKET-138).
import { getModelsUsed, getSkeleton2d, getMeshIndex } from "./api.js";
import { jointsFor } from "./timeline.js";
import { modelsPanel } from "./model/models-used.js";
import { validSkeleton, mistakesOf, skeletonAt } from "./model/skeleton-frame.js";
import { trainerClock, meshFaults } from "./model/mesh-clock.js";
import { renderModelsUsed } from "./views/models-used.js";
import { mountSkeletonOverlay } from "./views/skeleton-overlay.js";

/** True for a single follower's result of a real job (the example result and group people have no job files). */
export const hasJobFiles = (job, pid) => !!job && job !== "fixture" && !pid;

/** R1: "How this was made" into `holder`; resolves the section, or null when there is nothing to show. */
export async function mountModelsUsed(holder, job, load = getModelsUsed) {
  let panel = null;
  try { panel = modelsPanel(await load(job)); } catch { panel = null; }
  return panel && holder.isConnected !== false ? renderModelsUsed(holder, panel) : null;
}

/** R2: the follower's skeleton over the stage video; resolves the overlay handle or null. */
export async function mountSkeleton(coach, { job, analysis, load = getSkeleton2d }) {
  let doc = null;
  try { doc = await load(job); } catch { doc = null; }
  if (!coach || !coach.video || !coach.video.isConnected || !validSkeleton(doc)) return null;
  const mistakes = mistakesOf(analysis, jointsFor);
  return mountSkeletonOverlay(coach.video, {
    frameFor: (t, w, h, pinned) => skeletonAt(doc, t, w, h, mistakes, pinned),
    toggleHost: coach.el.querySelector(".sr-coach-bar"),
  });
}

const importMeshView = (host, ctx) => import("./mesh-view.js").then((m) => m.mountMeshView(host, ctx));

/**
 * R3: both people's SAM 3D Body meshes in `host` when the job has them (GET mesh.json names both); resolves the mesh
 * view handle, or null so the caller keeps its stick figures.
 */
export async function mountMesh(host, { job, analysis, replay, loadIndex = getMeshIndex, mount = importMeshView }) {
  let idx = null;
  try { idx = await loadIndex(job); } catch { idx = null; }
  if (!idx || typeof idx.trainer !== "string" || typeof idx.you !== "string") return null;
  const ctx = { trainerMeshUrl: idx.trainer, followerMeshUrl: idx.you, faults: meshFaults(mistakesOf(analysis, jointsFor)),
    fps: replay && replay.fps ? replay.fps : null };
  const clock = trainerClock(replay);
  if (clock) ctx.trainerTime = clock;
  try { return await mount(host, ctx); } catch { return null; }
}

const reducedMotion = () => typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;

/** True when a rect lies wholly inside the viewport below `top` (the app's sticky header). */
export const fullyInView = (rect, viewH, top = 0) => rect.top >= top - 1 && rect.bottom <= viewH + 1;

/**
 * R5: bring the stage (video and 3D view) into sight before a row seeks it, unless both already are. The stage's
 * `scroll-margin-top` (theme/results.css) is the header's height, so the scroll stops below the header.
 */
export function showStage(stage, compareEl = null) {
  if (!stage || !stage.isConnected) return;
  const top = parseFloat(getComputedStyle(stage).scrollMarginTop) || 0;
  const viewH = window.innerHeight;
  const video = stage.querySelector(".sr-coach");
  const videoOk = !video || video.hidden || fullyInView(video.getBoundingClientRect(), viewH, top);
  const cmpOk = !compareEl || !compareEl.isConnected || fullyInView(compareEl.getBoundingClientRect(), viewH, top);
  if (videoOk && cmpOk) return;
  stage.scrollIntoView({ block: "start", behavior: reducedMotion() ? "auto" : "smooth" });
}

/**
 * Result-intent.md R4 (TICKET-139): the reveal's last beat. Once the ring has counted up (`startedAt` plus `delayMs`,
 * performance.now() times) and the 3D compare is mostly in sight, the trainer and you slide together into the overlay.
 * `startedAt` null (the reveal does not play: a repeat in this session) or reduced motion leaves the view as it was.
 * The compare's `data-reveal` reads waiting, playing, done or skipped. Returns a stop function.
 */
export function armSlide(compare, { startedAt, delayMs, reduce = reducedMotion() }) {
  const wrap = compare && compare.el;
  if (!wrap || typeof compare.slideTogether !== "function" || wrap.getAttribute("data-mode") !== "side") return () => {};
  if (startedAt == null || reduce) { wrap.setAttribute("data-reveal", "skipped"); return () => {}; }
  let stopped = false;
  let obs = null;
  const begin = () => {
    if (stopped) return;
    if (wrap.getAttribute("data-mode") !== "side") { wrap.setAttribute("data-reveal", "skipped"); return; }   // toggled by hand
    wrap.setAttribute("data-reveal", "playing");
    compare.slideTogether().then((done) => { if (!stopped) wrap.setAttribute("data-reveal", done ? "done" : "skipped"); });
  };
  wrap.setAttribute("data-reveal", "waiting");
  const timer = setTimeout(() => {
    if (stopped) return;
    if (typeof IntersectionObserver !== "function") { begin(); return; }
    obs = new IntersectionObserver((entries) => {
      if (!entries.some((e) => e.isIntersecting)) return;
      obs.disconnect();
      obs = null;
      begin();
    }, { threshold: 0.6 });
    obs.observe(wrap);
  }, Math.max(0, startedAt + delayMs - performance.now()));
  return () => { stopped = true; clearTimeout(timer); if (obs) obs.disconnect(); };
}
