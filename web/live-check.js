// Live check: MediaPipe Pose (Google, Apache-2.0) in the browser while the camera is on. It draws the person's
// joints on the preview, says whether the whole body is in view, and on Follow, while recording, compares joint
// angles with the trainer's animation at the same moment. It runs on this device (no frame leaves it) and is
// approximate: the score after the take (SAM 3D Body and Parts 3 to 5) is the one that counts, and the note says so.
// Client 22d09a7 / c76b618 (TICKET-187): integrated from the serverless-modal branch. One reconciliation: the check
// starts OFF and the toggle turns it on (remembered per browser), because starting it loads Google's MediaPipe code
// and model (several megabytes) before the person chooses it. LIC-H5 and LEG-H2: the code, its wasm and the model are
// vendored under web/vendor/mediapipe/ at pinned versions with hashes (web/vendor/README.md), so no request leaves this
// site. A `loadVision` option replaces the import (tests serve a stub).
import { h } from "./ui.js";
import { getEntryFile } from "./api.js";
import { referenceTime } from "./reference.js";
import { tokenValue } from "./theme-colors.js";

export const VISION = new URL("./vendor/mediapipe", import.meta.url).href; // @mediapipe/tasks-vision 0.10.14
export const MODEL = `${VISION}/models/pose_landmarker_lite.task`; // pose_landmarker_lite float16 v1 (Apache-2.0 model card)
const PREF = "simon.liveCheck";
const STEP_MS = 66; // about 15 checks a second is plenty for cues and keeps phones cool
export const OFF_DEG = 25; // a joint further than this from the trainer's angle is flagged
export const TEXT = {
  note: "Live check is approximate guidance from your device. Your results after the take are more accurate.",
  offNote: "It draws your joints on the preview and, on Follow, flags a joint that is off the trainer. Turning it on loads Google's MediaPipe from this site into this browser; no frame leaves your device.",
  loading: "Live check is starting…",
  unavailable: "Live check is not available in this browser.",
  inView: "Whole body in view",
  noBody: "No one in view",
  toggleOn: "Live check: on",
  toggleOff: "Live check: off",
};

// MediaPipe's 33 landmarks, by the canonical names Parts 2 to 5 use (both are the subject's own left and right).
export const MP = {
  nose: 0, left_shoulder: 11, right_shoulder: 12, left_elbow: 13, right_elbow: 14, left_wrist: 15, right_wrist: 16,
  left_hip: 23, right_hip: 24, left_knee: 25, right_knee: 26, left_ankle: 27, right_ankle: 28,
};
const BONES = [[11, 12], [11, 13], [13, 15], [12, 14], [14, 16], [11, 23], [12, 24], [23, 24], [23, 25], [25, 27], [24, 26], [26, 28]];
// [label, a, vertex, b]: the angle at the vertex between the segments to a and to b
export const ANGLES = [
  ["left elbow", "left_shoulder", "left_elbow", "left_wrist"],
  ["right elbow", "right_shoulder", "right_elbow", "right_wrist"],
  ["left shoulder", "left_hip", "left_shoulder", "left_elbow"],
  ["right shoulder", "right_hip", "right_shoulder", "right_elbow"],
  ["left hip", "left_shoulder", "left_hip", "left_knee"],
  ["right hip", "right_shoulder", "right_hip", "right_knee"],
  ["left knee", "left_hip", "left_knee", "left_ankle"],
  ["right knee", "right_hip", "right_knee", "right_ankle"],
];
const NEEDED = [["head", ["nose"]], ["shoulders", ["left_shoulder", "right_shoulder"]], ["hips", ["left_hip", "right_hip"]],
  ["feet", ["left_ankle", "right_ankle"]]];

/** Angle in degrees at `v` between `a` and `b` ({x, y, z} each); null when a point is missing. */
export function angle(a, v, b) {
  if (!a || !v || !b) return null;
  const u = [a.x - v.x, a.y - v.y, a.z - v.z], w = [b.x - v.x, b.y - v.y, b.z - v.z];
  const nu = Math.hypot(...u), nw = Math.hypot(...w);
  if (!nu || !nw) return null;
  const c = (u[0] * w[0] + u[1] * w[1] + u[2] * w[2]) / (nu * nw);
  return (Math.acos(Math.max(-1, Math.min(1, c))) * 180) / Math.PI;
}

/** MediaPipe world landmarks (metres, hips at the origin, y down) as canonical joints, y up. */
export function liveJoints(world) {
  const out = {};
  for (const [name, i] of Object.entries(MP)) {
    const p = world.at(i);
    if (p) out[name] = { x: p.x, y: -p.y, z: p.z, v: p.visibility ?? 1 };
  }
  return out;
}

/**
 * The animation's joints at `t` seconds (frames at its fps) as {name: {x, y, z}}, or null. Both layouts Part 4
 * writes: simon.animation.v1 (`frames[].joints.<name>` = [x, y, z]) and the older simon.animation/1
 * (`frames[].people[0].joints.<name>` = {x, y, z}).
 */
export function animationJoints(anim, t) {
  const frames = anim && anim.frames;
  if (!frames || !frames.length) return null;
  const i = Math.max(0, Math.min(frames.length - 1, Math.round(t * (anim.fps || 30))));
  const frame = frames.at(i);
  const joints = frame.joints || ((frame.people || []).at(0) || {}).joints;
  if (!joints) return null;
  const out = {};
  for (const [name, p] of Object.entries(joints)) {
    out[name] = Array.isArray(p) ? { x: p.at(0), y: p.at(1), z: p.at(2) } : p;
  }
  return out;
}

const swapSide = (name) => name.replace(/^left_/, "@").replace(/^right_/, "left_").replace(/^@/, "right_");

/**
 * Joints whose angle differs from the trainer's by more than `off` degrees, worst first:
 * [{label, joint, diff}], diff = follower minus trainer. `mirrored`: the follower mirrors the trainer, so the
 * follower's left is compared with the trainer's right. Low-visibility live joints are skipped.
 */
export function compareAngles(live, ref, mirrored = true, off = OFF_DEG) {
  const out = [];
  for (const [label, a, v, b] of ANGLES) {
    if ([a, v, b].some((n) => !live[n] || live[n].v < 0.5)) continue;
    const r = (n) => ref[mirrored ? swapSide(n) : n];
    const mine = angle(live[a], live[v], live[b]);
    const theirs = angle(r(a), r(v), r(b));
    if (mine == null || theirs == null) continue;
    const diff = mine - theirs;
    if (Math.abs(diff) > off) out.push({ label, joint: v, diff });
  }
  return out.sort((x, y) => Math.abs(y.diff) - Math.abs(x.diff));
}

/** One short cue: a smaller angle than the trainer's is more bent. */
export function cueFor(miss) {
  return miss.diff < 0 ? `Straighten your ${miss.label}` : `Bend your ${miss.label} more`;
}

/** What is out of view, from normalized landmarks (x, y in 0..1); "" when the whole body is in. */
export function outOfView(points) {
  if (!points || !points.length) return TEXT.noBody;
  const seen = (i) => { const p = points.at(i); return p && (p.visibility ?? 1) > 0.5 && p.x > 0.01 && p.x < 0.99 && p.y > 0.01 && p.y < 0.99; };
  const missing = NEEDED.filter(([, names]) => !names.every((n) => seen(MP[n]))).map(([part]) => part);
  return missing.length ? `Step back: your ${missing.join(" and ")} ${missing.length > 1 ? "are" : "is"} out of view` : "";
}

function loadPref() { try { return localStorage.getItem(PREF) === "on"; } catch { return false; } }
function savePref(on) { try { localStorage.setItem(PREF, on ? "on" : "off"); } catch { /* private window */ } }

/**
 * A live check for one capture widget. `entry` (Follow) enables the comparison with the trainer's animation;
 * `reference` (reference.js) tells whether the follower mirrors the trainer and whether a practice section loops.
 * Returns {el, attach(stage, video), start(), stop(), recording(startedAtMs | null), destroy()}.
 */
export function mountLiveCheck({ entry = null, reference = null, loadVision = (url) => import(`${url}/vision_bundle.mjs`) } = {}) {
  let on = loadPref();
  let landmarker = null, loading = null, failed = false;
  let video = null, stage = null, canvas = null, raf = 0, last = 0, running = false, startedAt = null;
  let anim = null;
  let lastDebug = 0;
  const debug = (() => { try { return localStorage.getItem("simon.liveDebug") === "1"; } catch { return false; } })();
  const chip = h("p", { class: "live-chip", "data-testid": "live-status", role: "status", hidden: true });
  const cue = h("p", { class: "live-cue", "data-testid": "live-cue", "aria-live": "polite", hidden: true });
  const toggle = h("button", { type: "button", class: "btn secondary live-toggle", "data-testid": "live-toggle", onclick: () => setOn(!on) });
  const note = h("p", { class: "hint live-note", "data-testid": "live-note", text: TEXT.offNote });
  const el = h("div", { class: "live-bar" }, toggle, note);

  if (entry && entry.animation) {
    getEntryFile(entry.id, entry.animation)
      .then((a) => { anim = a; console.info("[live] trainer animation:", (a.frames || []).length, "frames at", a.fps, "fps"); })
      .catch((e) => console.warn("[live] no animation:", e && e.message));
  } else if (entry) {
    console.info("[live] this movement has no animation to compare with");
  }

  function setOn(next) {
    on = next;
    savePref(on);
    toggle.textContent = on ? TEXT.toggleOn : TEXT.toggleOff;
    toggle.setAttribute("aria-pressed", String(on));
    note.textContent = on ? TEXT.note : TEXT.offNote;
    if (on) start(); else stop(true);
  }

  async function ensureModel() {
    if (landmarker || failed) return landmarker;
    if (!loading) {
      chip.hidden = false;
      chip.textContent = TEXT.loading;
      loading = (async () => {
        const vision = await loadVision(VISION);
        const files = await vision.FilesetResolver.forVisionTasks(`${VISION}/wasm`);
        return vision.PoseLandmarker.createFromOptions(files, {
          baseOptions: { modelAssetPath: MODEL, delegate: "GPU" }, runningMode: "VIDEO", numPoses: 1,
        });
      })().then((lm) => { landmarker = lm; console.info("[live] pose model ready"); return lm; })
        .catch((e) => { failed = true; console.warn("[live] pose model failed:", e && e.message); chip.textContent = TEXT.unavailable; return null; });
    }
    return loading;
  }

  function attach(st, vid) {
    stage = st;
    video = vid;
    canvas = h("canvas", { class: "live-canvas mirror", "aria-hidden": "true", "data-testid": "live-canvas" });
    stage.append(canvas, chip, cue);
    setOn(on);
  }

  async function start() {
    if (!on || !video || !video.srcObject) return;
    const lm = await ensureModel();
    if (!lm || running || !on) return;
    running = true;
    raf = requestAnimationFrame(tick);
  }

  function stop(clearAll = false) {
    running = false;
    cancelAnimationFrame(raf);
    if (canvas) canvas.getContext("2d").clearRect(0, 0, canvas.width, canvas.height);
    cue.hidden = true;
    if (clearAll || !failed) chip.hidden = true;
  }

  // The video is drawn with object-fit: contain, so landmarks map into the letterboxed picture, not the whole stage.
  function fit() {
    const W = stage.clientWidth, H = stage.clientHeight, vw = video.videoWidth, vh = video.videoHeight;
    const dpr = window.devicePixelRatio || 1;
    if (canvas.width !== Math.round(W * dpr) || canvas.height !== Math.round(H * dpr)) {
      canvas.width = Math.round(W * dpr);
      canvas.height = Math.round(H * dpr);
    }
    const s = Math.min(W / vw, H / vh);
    return { dpr, s, dx: (W - vw * s) / 2, dy: (H - vh * s) / 2, vw, vh };
  }

  const colors = { bone: tokenValue("--live-bone"), ok: tokenValue("--live-ok"), off: tokenValue("--live-off") };
  function draw(points, bad) {
    const g = canvas.getContext("2d");
    const { dpr, s, dx, dy, vw, vh } = fit();
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.clearRect(0, 0, canvas.width, canvas.height);
    const P = (i) => { const p = points.at(i); return p && { x: dx + p.x * vw * s, y: dy + p.y * vh * s, v: p.visibility ?? 1 }; };
    g.lineWidth = 3;
    g.strokeStyle = colors.bone; // brand: theme/tokens.css (--live-*)
    for (const [i, j] of BONES) {
      const a = P(i), b = P(j);
      if (!a || !b || a.v < 0.5 || b.v < 0.5) continue;
      g.beginPath(); g.moveTo(a.x, a.y); g.lineTo(b.x, b.y); g.stroke();
    }
    for (const [name, i] of Object.entries(MP)) {
      const p = P(i);
      if (!p || p.v < 0.5) continue;
      g.fillStyle = bad.has(name) ? colors.off : colors.ok;
      g.beginPath(); g.arc(p.x, p.y, bad.has(name) ? 8 : 5, 0, Math.PI * 2); g.fill();
    }
  }

  function tick(now) {
    if (!running) return;
    raf = requestAnimationFrame(tick);
    if (now - last < STEP_MS || !video || video.readyState < 2 || !video.videoWidth) return;
    last = now;
    let res;
    try { res = landmarker.detectForVideo(video, now); } catch (e) { console.warn("[live] detect failed:", e && e.message); return; }
    const points = (res.landmarks || []).at(0) || [];
    const world = (res.worldLandmarks || []).at(0) || [];
    const away = outOfView(points);
    chip.hidden = false;
    chip.dataset.ok = String(!away);
    chip.textContent = away || TEXT.inView;
    let misses = [];
    const section = reference && reference.el && reference.el.dataset.section;
    if (anim && startedAt != null && world.length && !section) {
      const dur = (anim.frames.length || 1) / (anim.fps || 30);
      const ref = animationJoints(anim, referenceTime(Date.now() - startedAt, 0, dur));
      if (ref) misses = compareAngles(liveJoints(world), ref, reference ? reference.mirrored() : true);
      if (debug && now - lastDebug > 1000) {
        lastDebug = now;
        const lj = liveJoints(world);
        console.debug("[live] angles (you / trainer):", ANGLES.map(([label, a, v, b]) =>
          `${label} ${Math.round(angle(lj[a], lj[v], lj[b]) ?? -1)}/${ref ? Math.round(angle(ref[a], ref[v], ref[b]) ?? -1) : "-"}`).join(", "));
      }
    }
    cue.hidden = !misses.length;
    if (misses.length) cue.textContent = misses.slice(0, 2).map(cueFor).join(" · ");
    draw(points, new Set(misses.map((m) => m.joint)));
  }

  return {
    el,
    attach,
    start,
    stop: () => stop(false),
    /** The recording clock: compare with the trainer from `ms` (Date.now() at the start), or stop comparing. */
    recording(ms) { startedAt = ms; if (ms == null) cue.hidden = true; },
    destroy() { stop(true); if (landmarker) { try { landmarker.close(); } catch { /* already closed */ } } },
  };
}
