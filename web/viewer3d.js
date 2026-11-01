// The WebGL stage for the compare view and the Watch viewer (compare-view.md, TICKET-045).
// One scene, one perspective camera and one orbit state shared by every figure. Drag orbits,
// pinch or wheel zooms. No dependency on another part; three@0.170.0 is vendored in web/vendor.
import * as THREE from "./vendor/three/three.module.min.js";
import { tokenHex } from "./theme-colors.js";
import { FALLBACK_3D as FB } from "./theme-fallbacks.js";

const SIDE_GAP_M = 0.8; // compare-view.md, Modes: figures 0.8 m apart on x
const TARGET = new THREE.Vector3(0, -0.06, 0);
const DEG = Math.PI / 180;
const MIN_EL = -10;
const MAX_EL = 90;
const MIN_DIST = 1.3;
const MAX_DIST = 8;
const BONE_R = 0.02;
const FACE_BONE_R = 0.008;
const JOINT_R = 0.03;
const DIM_OPACITY = 0.3;
export const VIEWS = {
  front: { azimuth: 0, elevation: 8 },
  side: { azimuth: 90, elevation: 8 },
  top: { azimuth: 0, elevation: 90 },
};

export function webglAvailable() {
  try {
    const c = document.createElement("canvas");
    return !!(c.getContext("webgl2") || c.getContext("webgl"));
  } catch {
    return false;
  }
}

const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

/**
 * @param host element that receives the canvas
 * @param opts {joints: string[], bones: [i,j][], tracks: [{color, ghostInOverlay, label}]}
 */
export function createStage(host, { joints, bones, tracks }) {
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  const canvas = renderer.domElement;
  canvas.setAttribute("data-testid", "compare-canvas");
  canvas.setAttribute("tabindex", "0");
  canvas.setAttribute("role", "img");
  canvas.setAttribute("aria-label", "3D view. Drag to rotate, pinch or scroll to zoom.");
  canvas.style.touchAction = "none";
  host.prepend(canvas);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(36, 1, 0.1, 50);
  scene.add(new THREE.HemisphereLight(FB.skyLight, FB.groundLight, 1.9));
  const key = new THREE.DirectionalLight(FB.keyLight, 1.6);
  key.position.set(1.5, 3, 2.5);
  scene.add(key);
  const grid = new THREE.GridHelper(4, 16, tokenHex("--3d-grid", FB["--3d-grid"]), tokenHex("--3d-grid-center", FB["--3d-grid-center"]));
  grid.position.y = -0.95;
  scene.add(grid);

  const hipL = joints.indexOf("left_hip");
  const hipR = joints.indexOf("right_hip");
  const boneGeo = new THREE.CylinderGeometry(1, 1, 1, 10, 1, false);
  const jointGeo = new THREE.SphereGeometry(1, 14, 10);
  const haloMat = new THREE.MeshBasicMaterial({ color: tokenHex("--3d-hot", FB["--3d-hot"]), transparent: true, opacity: 0.4, depthWrite: false });
  const hotMat = new THREE.MeshStandardMaterial({ color: tokenHex("--3d-hot", FB["--3d-hot"]), emissive: tokenHex("--3d-hot", FB.hotGlow), emissiveIntensity: 0.9, roughness: 0.4 });

  const figures = tracks.map((t) => {
    const group = new THREE.Group();
    const mat = new THREE.MeshStandardMaterial({ color: t.color, roughness: 0.55, metalness: 0.05, transparent: true, opacity: 1 });
    // TICKET-065: a joint the camera did not see in this frame is drawn dimmed, never dropped
    const dimMat = new THREE.MeshStandardMaterial({ color: t.color, roughness: 0.55, metalness: 0.05, transparent: true, opacity: DIM_OPACITY, depthWrite: false });
    const boneMeshes = bones.map(([a, b]) => {
      const m = new THREE.Mesh(boneGeo, mat);
      m.userData.r = a <= 4 && b <= 4 ? FACE_BONE_R : BONE_R;
      group.add(m);
      return m;
    });
    const jointMeshes = joints.map((_, i) => {
      const m = new THREE.Mesh(jointGeo, mat);
      m.userData.r = i <= 4 ? FACE_BONE_R * 1.3 : JOINT_R;
      m.scale.setScalar(m.userData.r);
      group.add(m);
      return m;
    });
    const halos = joints.map(() => {
      const h = new THREE.Mesh(jointGeo, haloMat);
      h.visible = false;
      group.add(h);
      return h;
    });
    scene.add(group);
    return { group, mat, dimMat, boneMeshes, jointMeshes, halos, pose: null, dim: new Set(), stats: null, offset: new THREE.Vector3(), pelvis: new THREE.Vector3() };
  });

  const state = { azimuth: 24, elevation: 14, distance: 3.4, mode: tracks.length > 1 ? "side" : "single", highlight: new Set() };
  const listeners = { camera: new Set(), render: new Set() };
  let queued = false;
  let disposed = false;

  const UP = new THREE.Vector3(0, 1, 0);
  const tmpA = new THREE.Vector3();
  const tmpB = new THREE.Vector3();
  const tmpDir = new THREE.Vector3();

  function placeCamera() {
    const a = state.azimuth * DEG;
    const e = state.elevation * DEG;
    camera.position.set(
      TARGET.x + state.distance * Math.cos(e) * Math.sin(a),
      TARGET.y + state.distance * Math.sin(e),
      TARGET.z + state.distance * Math.cos(e) * Math.cos(a),
    );
    camera.up.set(-Math.sin(e) * Math.sin(a), Math.cos(e), -Math.sin(e) * Math.cos(a));
    camera.lookAt(TARGET);
    camera.updateMatrixWorld(true);
  }

  function poseFigure(fig, trackIdx) {
    const pose = fig.pose;
    fig.group.visible = !!pose;
    if (!pose) { fig.stats = null; return; }
    const dim = fig.dim;
    const stats = { joints: 0, dimmed: 0, bones: 0 };
    let cx = 0, cy = 0, cz = 0;
    const hl = pose[hipL], hr = pose[hipR];
    if (hl && hr) { cx = (hl[0] + hr[0]) / 2; cy = (hl[1] + hr[1]) / 2; cz = (hl[2] + hr[2]) / 2; }
    const slot = state.mode === "side" ? (trackIdx === 0 ? -SIDE_GAP_M / 2 : SIDE_GAP_M / 2) : 0;
    fig.offset.set(slot - cx, -cy, -cz);
    fig.pelvis.set(slot, 0, 0);
    const hot = trackIdx === figures.length - 1 ? state.highlight : null;
    pose.forEach((p, i) => {
      const jm = fig.jointMeshes[i];
      const halo = fig.halos[i];
      if (!p) { jm.visible = false; halo.visible = false; return; }
      jm.visible = true;
      stats.joints++;
      if (dim.has(i)) stats.dimmed++;
      jm.position.set(p[0] + fig.offset.x, p[1] + fig.offset.y, p[2] + fig.offset.z);
      const lit = !!hot && hot.has(i);
      jm.material = lit ? hotMat : dim.has(i) ? fig.dimMat : fig.mat;
      jm.scale.setScalar(lit ? jm.userData.r * 1.9 : jm.userData.r);
      halo.visible = lit;
      if (lit) { halo.position.copy(jm.position); halo.scale.setScalar(jm.userData.r * 4.2); }
    });
    bones.forEach(([a, b], k) => {
      const m = fig.boneMeshes[k];
      const pa = pose[a], pb = pose[b];
      if (!pa || !pb) { m.visible = false; return; }
      m.visible = true;
      stats.bones++;
      m.material = dim.has(a) || dim.has(b) ? fig.dimMat : fig.mat;
      tmpA.set(pa[0] + fig.offset.x, pa[1] + fig.offset.y, pa[2] + fig.offset.z);
      tmpB.set(pb[0] + fig.offset.x, pb[1] + fig.offset.y, pb[2] + fig.offset.z);
      tmpDir.subVectors(tmpB, tmpA);
      const len = tmpDir.length() || 1e-6;
      m.position.copy(tmpA).addScaledVector(tmpDir, 0.5);
      m.scale.set(m.userData.r, len, m.userData.r);
      m.quaternion.setFromUnitVectors(UP, tmpDir.multiplyScalar(1 / len));
    });
    fig.stats = stats;
  }

  function applyMaterials() {
    const overlay = state.mode === "overlay";
    figures.forEach((fig, i) => {
      const ghost = overlay && tracks[i].ghostInOverlay;
      fig.mat.opacity = ghost ? 0.32 : 1;
      fig.mat.depthWrite = !ghost;
      fig.mat.needsUpdate = true;
      fig.dimMat.opacity = fig.mat.opacity * DIM_OPACITY;
      fig.dimMat.needsUpdate = true;
    });
  }

  function render() {
    queued = false;
    if (disposed) return;
    figures.forEach((fig, i) => poseFigure(fig, i));
    placeCamera();
    renderer.render(scene, camera);
    listeners.render.forEach((fn) => fn());
  }
  function invalidate() {
    if (queued || disposed) return;
    queued = true;
    requestAnimationFrame(render);
  }
  function emitCamera() {
    listeners.camera.forEach((fn) => fn({ azimuth: state.azimuth, elevation: state.elevation }));
    invalidate();
  }

  function resize() {
    const w = Math.max(1, host.clientWidth);
    const h = Math.max(1, host.clientHeight);
    renderer.setSize(w, h, false);
    canvas.style.width = "100%";
    canvas.style.height = "100%";
    camera.aspect = w / h;
    // keep the figures in frame on a narrow canvas: widen the field when portrait
    camera.fov = w / h < 1 ? 36 / Math.max(0.62, w / h) : 36;
    camera.updateProjectionMatrix();
    invalidate();
  }
  const ro = new ResizeObserver(resize);
  ro.observe(host);

  // Orbit input: one pointer rotates, two pointers pinch.
  const pointers = new Map();
  let pinchStart = null;
  const onDown = (ev) => {
    canvas.setPointerCapture?.(ev.pointerId);
    pointers.set(ev.pointerId, { x: ev.clientX, y: ev.clientY });
    if (pointers.size === 2) {
      const [p, q] = [...pointers.values()];
      pinchStart = { d: Math.hypot(p.x - q.x, p.y - q.y), dist: state.distance };
    }
  };
  const onMove = (ev) => {
    const p = pointers.get(ev.pointerId);
    if (!p) return;
    const dx = ev.clientX - p.x, dy = ev.clientY - p.y;
    p.x = ev.clientX; p.y = ev.clientY;
    if (pointers.size === 1) {
      state.azimuth -= dx * 0.45;
      state.elevation = clamp(state.elevation + dy * 0.35, MIN_EL, MAX_EL);
      emitCamera();
    } else if (pointers.size === 2 && pinchStart) {
      const [a, b] = [...pointers.values()];
      const d = Math.hypot(a.x - b.x, a.y - b.y) || 1;
      state.distance = clamp(pinchStart.dist * (pinchStart.d / d), MIN_DIST, MAX_DIST);
      emitCamera();
    }
  };
  const onUp = (ev) => {
    pointers.delete(ev.pointerId);
    pinchStart = null;
    if (pointers.size === 1) { /* stay in rotate mode with the remaining finger */ }
  };
  const onWheel = (ev) => {
    ev.preventDefault();
    state.distance = clamp(state.distance * Math.exp(ev.deltaY * 0.0015), MIN_DIST, MAX_DIST);
    emitCamera();
  };
  const onKey = (ev) => {
    const step = 8;
    const moves = { ArrowLeft: [step, 0], ArrowRight: [-step, 0], ArrowUp: [0, step], ArrowDown: [0, -step] };
    const m = moves[ev.key];
    if (!m) return;
    ev.preventDefault();
    state.azimuth += m[0];
    state.elevation = clamp(state.elevation + m[1], MIN_EL, MAX_EL);
    emitCamera();
  };
  canvas.addEventListener("pointerdown", onDown);
  canvas.addEventListener("pointermove", onMove);
  canvas.addEventListener("pointerup", onUp);
  canvas.addEventListener("pointercancel", onUp);
  canvas.addEventListener("wheel", onWheel, { passive: false });
  canvas.addEventListener("keydown", onKey);

  applyMaterials();
  resize();

  return {
    canvas,
    /** poses[i] is figure i's joints (null hides the figure); dims[i] lists its joint indices to dim. */
    setPoses(poses, dims = []) {
      poses.forEach((p, i) => {
        if (!figures[i]) return;
        figures[i].pose = p;
        figures[i].dim = new Set(dims[i] || []);
      });
      invalidate();
    },
    /** Per figure, what the last render drew: {joints, dimmed, bones}, or null for a hidden figure. */
    drawStats: () => figures.map((f) => (f.stats ? { ...f.stats } : null)),
    setMode(mode) {
      state.mode = mode;
      applyMaterials();
      invalidate();
    },
    setView(name) {
      const v = VIEWS[name];
      if (!v) return;
      state.azimuth = v.azimuth;
      state.elevation = v.elevation;
      state.distance = 3.4;
      emitCamera();
    },
    /** joint indices lit on the last track (the follower) */
    setHighlight(indices) {
      state.highlight = new Set(indices);
      invalidate();
    },
    getCamera: () => ({ azimuth: state.azimuth, elevation: state.elevation, distance: state.distance }),
    onCamera(fn) { listeners.camera.add(fn); },
    onRender(fn) { listeners.render.add(fn); },
    /** CSS px position of a figure's pelvis within the canvas */
    pelvisScreen(trackIdx) {
      const fig = figures[trackIdx];
      if (!fig) return null;
      placeCamera();
      const v = fig.pelvis.clone().project(camera);
      const w = host.clientWidth, h = host.clientHeight;
      return { x: (v.x * 0.5 + 0.5) * w, y: (-v.y * 0.5 + 0.5) * h };
    },
    jointScreen(trackIdx, jointIdx) {
      const fig = figures[trackIdx];
      const m = fig && fig.jointMeshes[jointIdx];
      if (!m) return null;
      const v = m.position.clone().project(camera);
      return { x: (v.x * 0.5 + 0.5) * host.clientWidth, y: (-v.y * 0.5 + 0.5) * host.clientHeight };
    },
    render,
    dispose() {
      disposed = true;
      ro.disconnect();
      renderer.dispose();
      canvas.remove();
    },
  };
}
