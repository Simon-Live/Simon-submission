// Watch all (people.md, TICKET-060): every follower's skeleton overlaid on the trainer's ghost in one
// 3D view, one colour each, with show and hide per person. Reuses compare.js (model, frame picking,
// clock) and viewer3d.js (the stage); compare.js itself is unchanged.
import { el } from "./score.js";
import { normalizeReplay, pickFrames, createClock, ensureStyles, bodyReport, logBody, writeDrawStats, MSG_NO_WEBGL, TRAINER_COLOR } from "./compare.js";

export const PALETTE = [0x3ddc97, 0xffc83d, 0xff7a90, 0x5cd6ff, 0xc792ff, 0xff9447, 0x9be15d, 0xf5f5f5];
export const hex = (c) => `#${c.toString(16).padStart(6, "0")}`;
export const colorFor = (i) => PALETTE[i % PALETTE.length];

const ICON_PLAY = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5.5v13l11-6.5z"/></svg>';
const ICON_PAUSE = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 5h3.5v14H7zM13.5 5H17v14h-3.5z"/></svg>';

/**
 * Pure: the figures to draw at time `t`. Entry 0 is the trainer ghost (from the first person's expected
 * track); then one pose per person, null when hidden. `models` come from normalizeReplay.
 */
export function posesAt(t, models, hidden = new Set(), ids = models.map((_, i) => i)) {
  const first = pickFrames(t, models[0]);
  const poses = [models[0].expected[first.expected]];
  models.forEach((m, i) => {
    poses.push(hidden.has(ids[i]) ? null : m.follower[pickFrames(t, m).follower]);
  });
  return poses;
}

/** Pure: per figure of `posesAt`, the joint indices to dim (TICKET-065: unseen joints are dimmed). */
export function dimsAt(t, models, hidden = new Set(), ids = models.map((_, i) => i)) {
  const first = pickFrames(t, models[0]);
  const dims = [models[0].expectedUnseen[first.expected]];
  models.forEach((m, i) => {
    dims.push(hidden.has(ids[i]) ? [] : m.followerUnseen[pickFrames(t, m).follower]);
  });
  return dims;
}

/**
 * Mount the Watch all view. `people` is [{id, label, replay}] (raw replay.json each).
 * People whose replay cannot be read are skipped and named in a note.
 */
export async function mountMultiCompare(root, people) {
  ensureStyles();
  root.classList.add("simon-viewer");
  const wrap = el("section", { class: "sr-cmp pp-multi", "data-testid": "multi-compare", "data-mode": "overlay", "aria-label": "Everyone against the trainer in 3D" });
  root.append(wrap);
  const note = (text) => wrap.append(el("p", { class: "sr-note", role: "status", "data-testid": "multi-note", text }));

  const usable = [];
  const skipped = [];
  for (const p of people) {
    try {
      const model = normalizeReplay(p.replay);
      const base = usable[0] && usable[0].model;
      if (base && (base.joints.length !== model.joints.length || base.bones.length !== model.bones.length)) throw new Error("body");
      usable.push({ ...p, model, color: colorFor(usable.length) });
    } catch { skipped.push(p); }
  }
  if (!usable.length) { note("No take has a 3D replay to show."); return { el: wrap, stage: null, destroy() { wrap.remove(); } }; }

  let stageMod = null;
  try { stageMod = await import("./viewer3d.js"); } catch { stageMod = null; }
  if (!stageMod || !stageMod.webglAvailable()) {
    note(MSG_NO_WEBGL);
    wrap.setAttribute("data-unavailable", "webgl");
    return { el: wrap, stage: null, destroy() { wrap.remove(); } };
  }

  const models = usable.map((u) => u.model);
  const ids = usable.map((u) => u.id);
  const base = models[0];
  const hidden = new Set();
  const host = el("div", { class: "sr-stage" });
  const legend = el("ul", { class: "sr-legend", "aria-label": "Legend" });
  legend.append(el("li", { "data-who": "trainer" }, el("i", { style: `background:${hex(TRAINER_COLOR)}` }), el("span", { text: "Trainer" })));
  host.append(legend);
  wrap.append(host);

  const tracks = [{ color: TRAINER_COLOR, ghostInOverlay: true, label: "Trainer" },
    ...usable.map((u) => ({ color: u.color, ghostInOverlay: false, label: u.label }))];
  let stage;
  try {
    stage = stageMod.createStage(host, { joints: base.joints, bones: base.bones, tracks });
  } catch {
    host.remove();
    note(MSG_NO_WEBGL);
    wrap.setAttribute("data-unavailable", "webgl");
    return { el: wrap, stage: null, destroy() { wrap.remove(); } };
  }
  stage.setMode("overlay");
  // one log line for the view: the trainer's ghost comes from the first person, so only theirs reports it
  const reports = usable.map((u, i) => [u.id, bodyReport(i === 0 ? u.model : { ...u.model, expectedUnseen: [], expectedNever: [] })])
    .filter(([, r]) => r).map(([id, r]) => `${id}: ${r}`);
  logBody("multi-compare", reports.length ? reports.join(" | ") : null);
  stage.onRender(() => writeDrawStats(wrap, stage.drawStats()));

  const duration = Math.max(...models.map((m) => m.duration));
  const playBtn = el("button", { type: "button", class: "sr-btn sr-play", "data-testid": "play", "aria-label": "Play", "data-playing": "false" });
  playBtn.innerHTML = ICON_PLAY;
  const scrub = el("input", { type: "range", class: "sr-scrub", "data-testid": "scrub", min: 0, max: duration, step: "any", value: 0, "aria-label": "Position in the take" });
  const clockEl = el("output", { class: "sr-clock", "data-testid": "clock", "data-t": "0", text: "0.0 s" });
  const toggles = el("ul", { class: "pp-toggles", "aria-label": "Show or hide a person" });
  const buttons = new Map();
  usable.forEach((u) => {
    const b = el("button", { type: "button", class: "pp-toggle", "data-testid": `group-toggle-${u.id}`, "aria-pressed": "true" },
      el("i", { style: `background:${hex(u.color)}` }), el("span", { text: u.label }));
    buttons.set(u.id, b);
    toggles.append(el("li", {}, b));
  });
  wrap.append(el("div", { class: "sr-bar" }, playBtn, scrub, clockEl), toggles);
  if (skipped.length) note(`${skipped.length} take${skipped.length === 1 ? " has" : "s have"} no 3D replay and ${skipped.length === 1 ? "is" : "are"} left out.`);

  const draw = () => stage.setPoses(posesAt(clock.t, models, hidden, ids), dimsAt(clock.t, models, hidden, ids));
  const clock = createClock(duration, (t, playing) => {
    clockEl.textContent = `${t.toFixed(1)} s`;
    clockEl.setAttribute("data-t", String(t));
    scrub.value = String(t);
    if (playBtn.getAttribute("data-playing") !== String(playing)) {
      playBtn.setAttribute("data-playing", String(playing));
      playBtn.setAttribute("aria-label", playing ? "Pause" : "Play");
      playBtn.innerHTML = playing ? ICON_PAUSE : ICON_PLAY;
    }
    draw();
  });
  let raf = 0;
  const loop = () => { raf = 0; if (clock.tick()) raf = requestAnimationFrame(loop); };
  const startLoop = () => { if (!raf) raf = requestAnimationFrame(loop); };
  playBtn.addEventListener("click", () => { clock.toggle(); if (clock.playing) startLoop(); });
  scrub.addEventListener("input", () => clock.seek(Number(scrub.value)));

  const setVisible = (id, on) => {
    if (on) hidden.delete(id); else hidden.add(id);
    const b = buttons.get(id);
    if (b) b.setAttribute("aria-pressed", String(on));
    wrap.setAttribute("data-hidden", [...hidden].join(","));
    draw();
  };
  buttons.forEach((b, id) => b.addEventListener("click", () => setVisible(id, hidden.has(id))));
  wrap.setAttribute("data-people", ids.join(","));
  draw();

  return {
    el: wrap, stage, setVisible,
    seek(s) { clock.seek(Number(s)); },
    play() { clock.play(); startLoop(); },
    pause() { clock.pause(); },
    destroy() { if (raf) cancelAnimationFrame(raf); stage.dispose(); wrap.remove(); },
  };
}
