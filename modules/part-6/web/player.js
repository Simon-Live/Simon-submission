// The 3D player: takes the normalized animation, draws the figure with three.js, owns the playback
// clock and the camera, and exposes window.simonPlayer.state() for the done-check.
import * as THREE from 'three';
import { OrbitControls } from './vendor/three/OrbitControls.js';

// The one solid colour the scene clears to. The canvas carries it as data-bg.
export const BACKGROUND = '#172033';

const JOINTS = [
  'nose', 'left_eye', 'right_eye', 'left_ear', 'right_ear', 'left_shoulder', 'right_shoulder',
  'left_elbow', 'right_elbow', 'left_wrist', 'right_wrist', 'left_hip', 'right_hip',
  'left_knee', 'right_knee', 'left_ankle', 'right_ankle',
];
const FACE_JOINTS = 5;
const BONES = [
  ['left_shoulder', 'right_shoulder'], ['left_hip', 'right_hip'],
  ['left_shoulder', 'left_hip'], ['right_shoulder', 'right_hip'],
  ['left_shoulder', 'left_elbow'], ['right_shoulder', 'right_elbow'],
  ['left_elbow', 'left_wrist'], ['right_elbow', 'right_wrist'],
  ['left_hip', 'left_knee'], ['right_hip', 'right_knee'],
  ['left_knee', 'left_ankle'], ['right_knee', 'right_ankle'],
  ['nose', 'left_eye'], ['nose', 'right_eye'],
  ['left_eye', 'left_ear'], ['right_eye', 'right_ear'],
];
// Left and right use the thumbnail hues (teal and coral), lightened for the dark stage.
const SIDE_COLORS = { left: '#19b3a3', right: '#f0735c', centre: '#cbd5e1' };
const FRAME_FLOATS = JOINTS.length * 3;

const DEG = Math.PI / 180;
const FOV = 45;
const DEFAULT_VIEW = { azimuth: 30, polar: 75, distance: 3.2 };
const DISTANCE_LIMITS = { min: 1, max: 8 };
const TOP_POLAR_DEG = 0.5;
const JOINT_RADIUS = { face: 0.02, body: 0.034 };
const BONE_RADIUS = { face: 0.007, body: 0.014 };

// ---- animation data -------------------------------------------------------------------

// A normalized joint is [x, y, z]; the frame holds the 17 joints in JOINTS order, as a list or
// as an object keyed by joint name (web/formats.js, AC-F04).
function jointOf(joints, index) {
  return Array.isArray(joints) ? joints[index] : joints[JOINTS[index]];
}

function readFrame(frame, into, offset) {
  const joints = frame && frame.joints;
  if (!joints) return null;
  let lowestAnkle = Infinity;
  for (let j = 0; j < JOINTS.length; j += 1) {
    const point = jointOf(joints, j);
    if (!point || point.length < 3 || ![point[0], point[1], point[2]].every(Number.isFinite)) return null;
    into.set([point[0], point[1], point[2]], offset + j * 3);
    if (JOINTS[j].endsWith('_ankle')) lowestAnkle = Math.min(lowestAnkle, point[1]);
  }
  return lowestAnkle;
}

// Takes the normalized animation of web/formats.js ({fps, frames: [{joints}]}). Returns
// {fps, frameCount, duration, positions, floorY}, or null when it is unusable.
export function parseAnimation(raw) {
  if (!raw || !(raw.fps > 0) || !Array.isArray(raw.frames) || raw.frames.length === 0) return null;
  const positions = new Float32Array(raw.frames.length * FRAME_FLOATS);
  let floorY = Infinity;
  for (let i = 0; i < raw.frames.length; i += 1) {
    const ankleY = readFrame(raw.frames[i], positions, i * FRAME_FLOATS);
    if (ankleY === null) return null;
    floorY = Math.min(floorY, ankleY);
  }
  const frameCount = raw.frames.length;
  return { fps: raw.fps, frameCount, duration: frameCount / raw.fps, positions, floorY };
}

// ---- clock (AC-007) -------------------------------------------------------------------

class Clock {
  constructor(duration, fps) {
    this.duration = duration;
    this.endSlack = 0.5 / fps;
    this.base = 0;
    this.t0 = 0;
    this.speed = 1;
    this.playing = false;
    this.held = false;
  }

  position(now) {
    if (!this.playing || this.held) return this.base;
    return Math.min(this.duration, Math.max(0, this.base + (this.speed * (now - this.t0)) / 1000));
  }

  rebase(now) {
    this.base = this.position(now);
    this.t0 = now;
  }

  play(now) {
    if (this.position(now) >= this.duration - this.endSlack) this.base = 0;
    else this.rebase(now);
    this.t0 = now;
    this.playing = true;
  }

  pause(now) {
    this.rebase(now);
    this.playing = false;
  }

  setSpeed(speed, now) {
    this.rebase(now);
    this.speed = speed;
  }

  seek(seconds, now) {
    this.base = Math.min(this.duration, Math.max(0, seconds));
    this.t0 = now;
  }

  hold(on, now) {
    this.rebase(now);
    this.held = on;
  }

  finish() {
    this.base = this.duration;
    this.playing = false;
  }
}

// ---- scene ----------------------------------------------------------------------------

function buildScene(floorY) {
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(BACKGROUND);
  scene.add(new THREE.HemisphereLight(0xffffff, 0x2a3550, 1.6));
  const key = new THREE.DirectionalLight(0xffffff, 2.4);
  key.position.set(2.5, 4, 3);
  scene.add(key);
  const grid = new THREE.GridHelper(4, 20, 0x5a688d, 0x2d3a58);
  grid.position.y = floorY;
  scene.add(grid);
  return scene;
}

function sideOf(name) {
  if (name.startsWith('left_')) return 'left';
  return name.startsWith('right_') ? 'right' : 'centre';
}

function boneSide(from, to) {
  const [a, b] = [sideOf(from), sideOf(to)];
  if (a === b) return a;
  if (a === 'centre') return b;
  return b === 'centre' ? a : 'centre';
}

function buildFigure(scene) {
  const sphere = new THREE.SphereGeometry(1, 20, 14);
  const cylinder = new THREE.CylinderGeometry(1, 1, 1, 14, 1);
  const materials = {};
  for (const [side, color] of Object.entries(SIDE_COLORS)) {
    materials[side] = new THREE.MeshStandardMaterial({ color, roughness: 0.5, metalness: 0.05 });
  }
  const joints = JOINTS.map((name, index) => {
    const mesh = new THREE.Mesh(sphere, materials[sideOf(name)]);
    mesh.scale.setScalar(index < FACE_JOINTS ? JOINT_RADIUS.face : JOINT_RADIUS.body);
    scene.add(mesh);
    return mesh;
  });
  const bones = BONES.map(([from, to]) => {
    const a = JOINTS.indexOf(from);
    const b = JOINTS.indexOf(to);
    const mesh = new THREE.Mesh(cylinder, materials[boneSide(from, to)]);
    scene.add(mesh);
    const face = a < FACE_JOINTS || b < FACE_JOINTS;
    return { mesh, a, b, radius: face ? BONE_RADIUS.face : BONE_RADIUS.body };
  });
  return { joints, bones };
}

const UP = new THREE.Vector3(0, 1, 0);
const viewMatrix = new THREE.Matrix4();
const frustum = new THREE.Frustum();
const fromPoint = new THREE.Vector3();
const span = new THREE.Vector3();

function placeBone(bone, positions, base) {
  fromPoint.fromArray(positions, base + bone.a * 3);
  span.fromArray(positions, base + bone.b * 3).sub(fromPoint);
  const length = span.length();
  bone.mesh.visible = length > 1e-6;
  if (!bone.mesh.visible) return;
  bone.mesh.position.copy(fromPoint).addScaledVector(span, 0.5);
  bone.mesh.scale.set(bone.radius, length, bone.radius);
  bone.mesh.quaternion.setFromUnitVectors(UP, span.divideScalar(length));
}

function poseFigure(figure, positions, frame) {
  const base = frame * FRAME_FLOATS;
  figure.joints.forEach((mesh, j) => {
    mesh.position.fromArray(positions, base + j * 3);
    mesh.visible = true;
  });
  figure.bones.forEach((bone) => placeBone(bone, positions, base));
}

// Counts the joint meshes that sit inside the camera frustum of the draw just made.
function countJointsInView(figure, camera) {
  frustum.setFromProjectionMatrix(viewMatrix.multiplyMatrices(camera.projectionMatrix, camera.matrixWorldInverse));
  return figure.joints.filter((mesh) => mesh.visible && frustum.containsPoint(mesh.position)).length;
}

function disposeScene(scene) {
  scene.traverse((object) => {
    if (object.geometry) object.geometry.dispose();
    const materials = [].concat(object.material || []);
    materials.forEach((material) => material.dispose());
  });
}

// ---- camera ---------------------------------------------------------------------------

function configureControls(controls) {
  controls.enableDamping = false;
  controls.enablePan = false;
  controls.minDistance = DISTANCE_LIMITS.min;
  controls.maxDistance = DISTANCE_LIMITS.max;
  controls.target.set(0, 0, 0);
}

// Puts the camera at the given spherical position around the target at once, no tween.
function snapCamera(camera, controls, azimuthDeg, polarDeg, distance) {
  const azimuth = azimuthDeg * DEG;
  const polar = polarDeg * DEG;
  camera.position.set(
    distance * Math.sin(polar) * Math.sin(azimuth),
    distance * Math.cos(polar),
    distance * Math.sin(polar) * Math.cos(azimuth),
  ).add(controls.target);
  controls.update();
}

function watchSize(canvas, onSize) {
  const apply = () => {
    if (canvas.clientWidth && canvas.clientHeight) onSize(canvas.clientWidth, canvas.clientHeight);
  };
  const observer = new ResizeObserver(apply);
  observer.observe(canvas);
  apply();
  return () => observer.disconnect();
}

// ---- player ---------------------------------------------------------------------------

// hooks: onFrame({position, playing, speed}) after every draw, onPlaying(playing) on change.
export function createPlayer(canvas, data, hooks = {}) {
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, preserveDrawingBuffer: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  const scene = buildScene(data.floorY);
  const figure = buildFigure(scene);
  const camera = new THREE.PerspectiveCamera(FOV, 1, 0.1, 100);
  camera.position.set(0, 0, DEFAULT_VIEW.distance);
  const controls = new OrbitControls(camera, canvas);
  configureControls(controls);
  const clock = new Clock(data.duration, data.fps);
  let last = { frame: 0, position: 0, joints: 0 };
  let drawnFrame = -1;
  let raf = 0;
  let disposed = false;

  const stopWatching = watchSize(canvas, (width, height) => {
    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
  });

  function draw(now = performance.now()) {
    const position = clock.position(now);
    const frame = Math.min(data.frameCount - 1, Math.max(0, Math.round(position * data.fps)));
    if (frame !== drawnFrame) {
      poseFigure(figure, data.positions, frame);
      drawnFrame = frame;
    }
    controls.update();
    renderer.render(scene, camera);
    last = { frame, position, joints: countJointsInView(figure, camera) };
    if (hooks.onFrame) hooks.onFrame({ position, playing: clock.playing, speed: clock.speed });
  }

  function notifyPlaying() {
    if (hooks.onPlaying) hooks.onPlaying(clock.playing);
  }

  function loop() {
    raf = requestAnimationFrame(loop);
    const now = performance.now();
    if (clock.playing && clock.position(now) >= data.duration) {
      clock.finish();
      notifyPlaying();
    }
    draw(now);
  }

  function state() {
    const now = performance.now();
    const position = clock.position(now);
    return {
      position_s: position,
      speed: clock.speed,
      playing: clock.playing && position < data.duration,
      frame: last.frame,
      frame_position_s: last.position,
      fps: data.fps,
      frame_count: data.frameCount,
      duration_s: data.duration,
      joints_drawn: last.joints,
      azimuth_deg: controls.getAzimuthalAngle() / DEG,
      polar_deg: controls.getPolarAngle() / DEG,
      distance: controls.getDistance(),
      now_ms: now,
    };
  }

  const player = {
    duration: data.duration,
    fps: data.fps,
    play() {
      clock.play(performance.now());
      notifyPlaying();
      draw();
    },
    pause() {
      clock.pause(performance.now());
      notifyPlaying();
      draw();
    },
    toggle() {
      if (clock.playing) player.pause();
      else player.play();
    },
    setSpeed(speed) {
      clock.setSpeed(speed, performance.now());
      draw();
    },
    seek(seconds) {
      clock.seek(seconds, performance.now());
      draw();
    },
    hold(on) {
      clock.hold(on, performance.now());
    },
    view(name) {
      const distance = controls.getDistance();
      const views = {
        front: () => snapCamera(camera, controls, 0, 90, distance),
        side: () => snapCamera(camera, controls, 90, 90, distance),
        top: () => snapCamera(camera, controls, controls.getAzimuthalAngle() / DEG, TOP_POLAR_DEG, distance),
        reset: () => snapCamera(camera, controls, DEFAULT_VIEW.azimuth, DEFAULT_VIEW.polar, DEFAULT_VIEW.distance),
      };
      views[name]();
      draw();
    },
    state,
    dispose() {
      if (disposed) return;
      disposed = true;
      cancelAnimationFrame(raf);
      stopWatching();
      controls.dispose();
      disposeScene(scene);
      renderer.dispose();
      renderer.forceContextLoss();
      if (window.simonPlayer && window.simonPlayer.state === state) window.simonPlayer = null;
    },
  };

  player.view('reset');
  window.simonPlayer = { state };
  raf = requestAnimationFrame(loop);
  return player;
}
