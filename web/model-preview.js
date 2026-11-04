// The preview stage of "My 3D model" (docs/specs/model-default.md): glue between the 3D stage (viewer3d.js), the
// character loader (skin/character.js), Simon's own sample movement and the view (views/model-preview.js). The
// movement is always the trainer track of the committed example result (`api/fixture-result`), so every model is shown
// on the same real motion; a model's own embedded animation is never played.
import { TEXT } from "./model/model-default.js";
import { renderModelPreview } from "./views/model-preview.js";
import { isProd } from "./policy.js";

/** The motion the preview plays: { model (one figure, compare.js shape), source: "fixture" | "rest", still? }. Prod
 *  answers `api/fixture-result` 404 (prod-hardening.md item 4), so it asks nothing there (byok-ui D3) and, like an
 *  example result that fails to load, gives the still rest pose (TICKET-389): the person's figure is always shown. */
export async function loadMotion({ prod = isProd } = {}) {
  const [cmp, rest] = await Promise.all([import("./compare.js"), import("./model/rest-pose.js")]);
  const posed = () => ({ model: cmp.singleFromReplay(cmp.normalizeReplay(rest.restReplay())), source: "rest", still: true });
  if (prod()) return posed();
  try {
    const api = await import("./api.js");
    const fixture = await api.getFixtureResult();
    return { model: cmp.singleFromReplay(cmp.normalizeReplay(fixture.replay)), source: "fixture" };
  } catch {
    return posed();
  }
}

/** Everything the preview loads, each on first use. Injectable for tests. */
export const defaultDeps = {
  stage: () => import("./viewer3d.js"),
  motion: loadMotion,
  timing: () => import("./compare.js").then((m) => ({ createClock: m.createClock, pickFrames: m.pickFrames, color: m.YOU_COLOR })),
  character: () => import("./skin/character.js").then((m) => m.loadCharacter),
  raf: (fn) => requestAnimationFrame(fn),
  caf: (id) => cancelAnimationFrame(id),
};

/**
 * Mount the preview into `host`. Returns { show(choice, entry, {note}), destroy(), ready }: `show` puts the catalog
 * entry's model on the figure (null entry: the stick figure); `ready` resolves true once the stage plays.
 */
export function mountModelPreview(host, deps = defaultDeps) {
  const t = TEXT;
  let live = true;
  let stage = null;
  let model = null;
  let clock = null;
  let timing = null;
  let frame = 0;
  let looping = false;
  let asked = 0;

  const draw = (time) => {
    const f = timing.pickFrames(time, model).follower;
    stage.setPoses([model.frames[f]], [model.unseen ? model.unseen[f] : []]);
  };
  const step = () => {
    frame = 0;
    if (!live || !clock) return;
    let going = clock.tick();
    if (!going && looping) { clock.play(); going = true; } // the movement plays round and round until paused
    if (going) frame = deps.raf(step);
  };
  function toggle() {
    if (!clock) return;
    looping = !clock.playing;
    clock.toggle();
    if (clock.playing && !frame) frame = deps.raf(step);
  }
  const view = renderModelPreview(host, { t }, { toggle });
  view.setReady(false);

  async function start() {
    let parts;
    try {
      parts = await Promise.all([deps.stage(), deps.motion(), deps.timing()]);
    } catch {
      if (live) view.setStatus(t.noMotion);
      return false;
    }
    if (!live) return false;
    const [stageMod, motion] = parts;
    timing = parts[2];
    if (!stageMod.webglAvailable()) { view.setStatus(t.noWebgl); return false; }
    model = motion.model;
    view.setReady(true); // the box is shown before the stage measures it
    if (motion.still) view.setPlayable(false); // a still pose has nothing to play
    try {
      stage = stageMod.createStage(view.stageHost, { joints: model.joints, bones: model.bones, tracks: [{ color: timing.color, ghostInOverlay: false, label: "You" }] });
    } catch {
      view.setReady(false);
      view.setStatus(t.noWebgl);
      return false;
    }
    view.setMotion(motion.source);
    if (stage.setTake) stage.setTake([model.frames]); // the framing holds the whole movement from its first frame (model-skin.md AC16)
    if (stage.onCamera) stage.onCamera((c) => view.setCamera(c));
    if (stage.getCamera) view.setCamera(stage.getCamera());
    clock = timing.createClock(model.duration, (time, playing) => { draw(time); view.setPlaying(playing); });
    draw(0);
    view.setStatus("");
    return true;
  }
  const ready = start();

  /** Put `entry`'s model on the figure (null: the stick figure). `note` replaces the status line when given. */
  async function show(choice, entry, { note = "" } = {}) {
    const mine = ++asked;
    if (!(await ready) || !live || mine !== asked) return;
    const hasSkins = typeof stage.setSkin === "function";
    if (!entry) {
      if (hasSkins) stage.setSkin(0, null);
      view.setShown("sticks", "");
      view.setStatus(note || t.previewSticks);
      return;
    }
    // the figure of the model before is cleared the moment a new one is picked, so "Loading the preview" never sits over it
    if (hasSkins) stage.setSkin(0, null);
    view.setShown("loading", "");
    view.setStatus(t.previewLoading);
    let adapter = null;
    try { adapter = hasSkins ? await (await deps.character())(entry, { role: "you" }) : null; } catch { adapter = null; }
    if (!live || mine !== asked) { if (adapter && adapter.dispose) adapter.dispose(); return; }
    if (hasSkins) stage.setSkin(0, adapter);
    draw(clock.t);
    view.setShown(adapter ? choice : "sticks", adapter ? entry.id : "");
    view.setStatus(adapter ? note || t.previewModel(entry.name) : t.previewFailed);
  }

  return {
    show, ready,
    destroy() {
      live = false;
      if (frame) deps.caf(frame);
      if (stage) stage.dispose();
    },
  };
}
