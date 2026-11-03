// "Fix it for me" (docs/specs/fix-it-for-me.md, TICKET-265): the student's own body replays a coaching moment with only
// the faulted limb moved toward the trainer's shape. The body is whatever the model picker shows for You (the person's
// SAM 3D Body skin by default, their generated avatar or a chosen model), because the corrected pose goes through the same
// stage.setPoses and so through the same skin as the take itself. Client side, on the replay the result already holds:
// no request for new data, no GPU work, nothing stored. The math is in model/fix-it.js, the words and DOM in
// views/fix-it.js. It never touches the score and never says the student moved that way.
import { normalizeReplay, pickFrames, createClock, TRAINER_COLOR, YOU_COLOR } from "../compare.js";
import { ensureCss } from "../ui.js";
import { createChooser } from "./picker.js";
import { listModels } from "./catalog.js";
import { blendWeight, clipOf, correctPose, fixableFaults, report, TEXT } from "../model/fix-it.js";
import { renderFixIt } from "../views/fix-it.js";

const safeStorage = () => { try { return window.localStorage; } catch { return null; } };
const reduced = () => typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;
const fixed = (x, n = 1) => String(Math.round(x * 10 ** n) / 10 ** n);

/**
 * Mount the button and panel into `slot`. `ctx`: { job, analysis, replay }. Returns a cleanup function, or undefined when
 * the take has no fault the button can act on (no replay, no arm or leg fault, or a limb that already matches): then
 * nothing is drawn at all.
 */
export function mountFixIt(slot, ctx) {
  let model;
  try { model = normalizeReplay(ctx && ctx.replay); } catch { return undefined; }
  const faults = fixableFaults(ctx.analysis, model, pickFrames);
  if (!faults.length) return undefined;
  ensureCss("theme/fix-it.css", "data-fixit-css");

  const index = new Map(model.joints.map((n, i) => [n, i]));
  const state = { fault: faults[0], which: "after", split: false, clip: null, clock: null, raf: 0, token: 0, stages: [], deps: null };
  const view = renderFixIt(slot, { t: TEXT, options: faults.map((f) => ({ index: f.index, text: `${f.limbs.join(" and ")}: ${f.fault.cue || f.fault.text || `at ${fixed(f.at)} s`}` })) }, {
    open: (i) => open(i),
    close: () => close(),
    which: (w) => { state.which = w; view.show(state); draw(); },
    split: (b) => setSplit(b),
    play: () => { if (!state.clock) return; state.clock.toggle(); if (state.clock.playing) loop(); },
    scrub: (v) => state.clock && state.clock.seek(v),
  });

  /** The storage and catalog the picker uses, read once: a saved choice for You (per take, or the account default) applies here too. */
  async function deps() {
    if (state.deps) return state.deps;
    let storage = safeStorage();
    try { storage = await import("../model-default.js").then((m) => m.youStorage(safeStorage(), undefined, { job: ctx.job })); } catch { /* keep the device storage */ }
    let entries = [];
    try { const found = await listModels(); entries = [...found.library, ...found.mine]; } catch { /* sticks and Person only */ }
    state.deps = { storage, entries };
    return state.deps;
  }

  async function buildStage(host, legend) {
    const mod = await import("../viewer3d.js");
    if (!mod.webglAvailable()) throw new Error("webgl");
    const tracks = [{ color: TRAINER_COLOR, ghostInOverlay: true, label: "Trainer" }, { color: YOU_COLOR, ghostInOverlay: false, label: "You" }];
    const stage = mod.createStage(host, { joints: model.joints, bones: model.bones, tracks });
    stage.setMode("overlay");
    const chips = document.createElement("ul");
    chips.className = "fx-legend";
    chips.setAttribute("aria-label", "Legend");
    for (const [name, color] of [[TEXT.trainer, TRAINER_COLOR], [legend, YOU_COLOR]]) {
      const li = document.createElement("li");
      const dot = document.createElement("i");
      dot.style.background = `#${color.toString(16).padStart(6, "0")}`;
      const span = document.createElement("span");
      span.textContent = name;
      li.append(dot, span);
      chips.append(li);
    }
    host.append(chips);
    const { storage, entries } = await deps();
    const chooser = createChooser({ stage, tracks: [{ role: "trainer", label: "Trainer" }, { role: "you", label: "You" }], job: ctx.job, entries, deps: { storage } });
    const handle = { stage, host, chips, ready: chooser.restore().catch(() => []) };
    state.stages.push(handle);
    return handle;
  }

  const disposeStages = () => {
    for (const s of state.stages.splice(0)) { s.stage.dispose(); s.chips.remove(); }
  };

  /** Draw the clip's moment: the trainer's matched frame as the ghost, the take as it was, the take with the limb moved. */
  function draw() {
    if (!state.clip || !state.stages.length) return;
    const t = state.clip.start + (state.clock ? state.clock.t : 0);
    const { follower, expected } = pickFrames(t, model);
    const own = model.follower[follower];
    const trainer = model.expected[expected];
    const win = state.fault.win;
    const w = blendWeight(t, win);
    const shown = correctPose(own, trainer, index, state.fault.chains, w);
    const [a, b] = state.stages;
    const pick = state.split || state.which === "before" ? own : shown;
    a.stage.setPoses([trainer, pick]);
    const aMoved = report(own, pick, trainer, index, state.fault.chains).moved;
    if (state.split && b) b.stage.setPoses([trainer, shown]);
    const r = report(own, shown, trainer, index, state.fault.chains);
    view.data({
      t: fixed(t, 3), weight: fixed(w, 3), "moved-deg": fixed(r.moved), "toward-deg": fixed(r.toward), "outside-m": fixed(r.outside, 6),
      "before-toward-deg": fixed(report(own, own, trainer, index, state.fault.chains).toward), "peak-at": fixed(state.fault.peak.at, 3), "peak-deg": fixed(state.fault.peak.gap),
      "a-moved-deg": fixed(aMoved), "b-moved-deg": state.split ? fixed(r.moved) : "-", clip: `${fixed(state.clip.start, 3)},${fixed(state.clip.end, 3)}`,
      "window": `${fixed(win.start, 3)},${fixed(win.end, 3)}`, "fault-at": fixed(state.fault.at, 3), limbs: state.fault.limbs.join(","),
      "shown-a": state.split || state.which === "before" ? "before" : "after", "shown-b": state.split ? "after" : "-",
    });
  }

  const onClock = (t, playing) => { view.clock(t, playing, state.clip.end - state.clip.start); draw(); };
  const loop = () => {
    if (state.raf || !state.clock) return;
    const step = () => { state.raf = 0; if (state.clock && state.clock.tick()) state.raf = requestAnimationFrame(step); };
    state.raf = requestAnimationFrame(step);
  };
  const stopClock = () => { if (state.raf) cancelAnimationFrame(state.raf); state.raf = 0; if (state.clock) state.clock.pause(); };

  async function open(i) {
    const fault = faults.find((f) => f.index === i) || faults[0];
    const mine = ++state.token;
    stopClock();
    disposeStages();
    state.fault = fault;
    state.split = false;
    state.which = "after";
    state.clip = clipOf(fault.win, model.duration);
    view.visible(true);
    view.label(fault.label);
    view.note("");
    view.show(state);
    try {
      const first = await buildStage(view.hostA, TEXT.you);
      await first.ready;
      if (mine !== state.token) return;
    } catch {
      disposeStages();
      view.note(TEXT.noWebgl);
      return;
    }
    state.clock = createClock(state.clip.end - state.clip.start, onClock);
    const at = Math.max(0, fault.peak.at - state.clip.start);
    if (reduced()) state.clock.seek(at); else { state.clock.seek(0); state.clock.play(); loop(); }
    view.root.setAttribute("data-ready", "true");
    draw();
  }

  async function setSplit(both) {
    state.split = both;
    view.show(state);
    if (both && state.stages.length < 2) {
      const mine = state.token;
      try {
        const second = await buildStage(view.hostB, TEXT.youCorrected);
        await second.ready;
        if (mine !== state.token) return;
      } catch {
        state.split = false;
        view.show(state);
        view.note(TEXT.noWebgl);
        return;
      }
    }
    draw();
  }

  function close() {
    state.token++;
    stopClock();
    disposeStages();
    state.clock = null;
    view.root.removeAttribute("data-ready");
    view.visible(false);
    view.open.focus();
  }

  return () => { state.token++; stopClock(); disposeStages(); view.destroy(); };
}
