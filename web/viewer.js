/* Canvas 3D skeleton viewer for the Part 2 web app. No library.
 * Extracted from the inline viewer in part2/demo.py (docs/specs/run-app.md, AC-A01, AC-A03).
 *
 * World frame is the canonical frame of CONTRACT.md: x the subject's left, y up, z anterior, metres.
 * One person is drawn person-centred (hips at the origin). Several people are placed in the camera's
 * scene with camera.json (p_cam = R p + t), flipped to y up, so Front (camera on +z) looks the way the
 * original camera looked.
 */
(function (root, factory) {
  const api = factory(root);
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.Viewer = api;
})(typeof self !== 'undefined' ? self : globalThis, function (root) {
  'use strict';

  const JOINTS = [
    'nose', 'left_eye', 'right_eye', 'left_ear', 'right_ear',
    'left_shoulder', 'right_shoulder', 'left_elbow', 'right_elbow', 'left_wrist', 'right_wrist',
    'left_hip', 'right_hip', 'left_knee', 'right_knee', 'left_ankle', 'right_ankle',
  ];
  const BONE_NAMES = [
    ['left_ear', 'left_eye'], ['left_eye', 'nose'], ['nose', 'right_eye'], ['right_eye', 'right_ear'],
    ['left_shoulder', 'right_shoulder'], ['left_shoulder', 'left_elbow'], ['left_elbow', 'left_wrist'],
    ['right_shoulder', 'right_elbow'], ['right_elbow', 'right_wrist'],
    ['left_shoulder', 'left_hip'], ['right_shoulder', 'right_hip'], ['left_hip', 'right_hip'],
    ['left_hip', 'left_knee'], ['left_knee', 'left_ankle'], ['right_hip', 'right_knee'], ['right_knee', 'right_ankle'],
  ];
  const BONES = BONE_NAMES.map(([a, b]) => [JOINTS.indexOf(a), JOINTS.indexOf(b)]);
  // Same palette and rule as part2.demo.color_for, so ids keep their colour in every demo.
  const PALETTE = ['#E69F00', '#56B4E9', '#009E73', '#F0E442', '#0072B2', '#D55E00', '#CC79A7', '#999999',
    '#7F3C8D', '#11A579', '#3969AC', '#F2B701'];

  const HOME = { az: -0.6, el: 0.25 };   // radians; azimuth 0 is Front, elevation pi/2 is Top
  const FOCAL = 1.37;                    // times the shorter canvas side: a 40 degree field of view
  const NEAR = 0.05;                     // metres in front of the camera
  const ZOOM = { min: 0.3, max: 5 };     // distance limits, times the home distance
  const AXES = {
    canonical: { labels: ['x left', 'y up', 'z front'], length: 0.3 },
    scene: { labels: ['x right', 'y up', 'z toward camera'], length: 0.6 },
  };

  // ---- colour ----------------------------------------------------------------------------------

  function crc32(str) {
    let c = 0xFFFFFFFF;
    for (const b of new TextEncoder().encode(str)) {
      c ^= b;
      for (let k = 0; k < 8; k++) c = (c >>> 1) ^ (0xEDB88320 & -(c & 1));
    }
    return (c ^ 0xFFFFFFFF) >>> 0;
  }

  function colorFor(id) {
    const s = String(id);
    const n = /^-?\d+$/.test(s) ? parseInt(s, 10) : crc32(s);
    return PALETTE[((n % PALETTE.length) + PALETTE.length) % PALETTE.length];
  }

  function shade(hex) {                  // darker tone of the person colour for the right side
    const n = parseInt(hex.slice(1), 16), f = 0.55;
    return `rgb(${(n >> 16) * f | 0},${(n >> 8 & 255) * f | 0},${(n & 255) * f | 0})`;
  }

  const boneTone = BONES.map(([a, b]) => {   // left bones in the colour, right bones darker, midline grey
    const names = [JOINTS[a], JOINTS[b]];
    return names.some(n => n.startsWith('left')) ? 'main' : names.some(n => n.startsWith('right')) ? 'dark' : 'grey';
  });

  // ---- scene from pose3d.json and camera.json --------------------------------------------------

  function sortedIds(pose3d) {
    const seen = new Set();
    for (const f of pose3d.frames) for (const p of f.people) seen.add(p.id);
    return [...seen].sort((a, b) => (typeof a === 'number' && typeof b === 'number')
      ? a - b : String(a).localeCompare(String(b)));
  }

  function jointPoints(person) {
    const pts = [], conf = [];
    for (const name of JOINTS) {
      const j = person.joints && person.joints[name];
      if (!j) return null;
      pts.push([j.x, j.y, j.z]);
      conf.push(j.conf);
    }
    return { pts, conf };
  }

  function toScene(pts, cam) {           // p_cam = R p + t (OpenCV), then y up and z toward the camera
    const R = cam.R, t = cam.t;
    return pts.map(([x, y, z]) => [
      R[0][0] * x + R[0][1] * y + R[0][2] * z + t[0],
      -(R[1][0] * x + R[1][1] * y + R[1][2] * z + t[1]),
      -(R[2][0] * x + R[2][1] * y + R[2][2] * z + t[2]),
    ]);
  }

  function cameraIndex(camera) {
    const index = new Map();
    for (const f of (camera && camera.frames) || []) for (const c of f.people) index.set(f.frame + ':' + c.id, c);
    return index;
  }

  function quantile(sorted, q) {
    return sorted.length ? sorted[Math.min(sorted.length - 1, Math.floor(q * sorted.length))] : 0;
  }

  function homeView(frames, placement) {
    const cols = [[], [], []];
    for (const f of frames) for (const p of f.people) for (const q of p.pts) q.forEach((v, i) => cols[i].push(v));
    cols.forEach(c => c.sort((a, b) => a - b));
    const target = cols.map(c => quantile(c, 0.5));
    const dists = [];
    for (const f of frames) for (const p of f.people) {
      for (const q of p.pts) dists.push(Math.hypot(q[0] - target[0], q[1] - target[1], q[2] - target[2]));
    }
    dists.sort((a, b) => a - b);
    const radius = quantile(dists, 0.9) || 1;
    const half = Math.min(6, Math.max(1, Math.ceil(radius * 2) / 2));
    return {
      az: HOME.az, el: HOME.el, target, radius,
      dist: Math.max(3, (placement === 'scene' ? 3 : 4) * radius),
      floor: quantile(cols[1], 0.02),
      grid: { half, step: half > 1.5 ? 0.5 : 0.25 },
      axes: AXES[placement],
    };
  }

  /* pose3d and camera are the parsed files. placement: 'canonical', 'scene' or undefined (canonical for
   * one person, scene for several). Returns {ids, colors, placement, frames: [{frame, t_ms, people:
   * [{id, pts, conf}]}], home}. A person without a camera pose is left out of a scene frame. */
  function buildScene(pose3d, camera, placement) {
    const ids = sortedIds(pose3d);
    const mode = placement || (ids.length > 1 ? 'scene' : 'canonical');
    const cams = mode === 'scene' ? cameraIndex(camera) : null;
    const frames = pose3d.frames.map(f => {
      const people = [];
      for (const p of f.people) {
        const j = jointPoints(p);
        const c = cams && cams.get(f.frame + ':' + p.id);
        if (!j || (cams && !c)) continue;
        people.push({ id: p.id, pts: cams ? toScene(j.pts, c) : j.pts, conf: j.conf });
      }
      return { frame: f.frame, t_ms: f.t_ms, people };
    });
    const colors = {};
    for (const id of ids) colors[id] = colorFor(id);
    return { ids, colors, placement: mode, frames, home: homeView(frames, mode) };
  }

  // ---- camera math -----------------------------------------------------------------------------

  const snap = v => (Math.abs(v) < 1e-12 ? 0 : v);

  /* Camera position for azimuth az (0 puts it on +z, pi/2 on +x) and elevation el (pi/2 puts it on +y). */
  function orbitPosition(az, el, dist, target) {
    const ce = snap(Math.cos(el)), se = snap(Math.sin(el)), ca = snap(Math.cos(az)), sa = snap(Math.sin(az));
    return [target[0] + dist * ce * sa, target[1] + dist * se, target[2] + dist * ce * ca];
  }

  function viewBasis(az, el) {            // unit vectors: right, up, and back (toward the camera)
    const ce = snap(Math.cos(el)), se = snap(Math.sin(el)), ca = snap(Math.cos(az)), sa = snap(Math.sin(az));
    return { r: [ca, 0, -sa], u: [-se * sa, ce, -se * ca], b: [ce * sa, se, ce * ca] };
  }

  const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];

  function toView(p, cam) {              // x right, y up, distance along the view direction
    const v = [p[0] - cam.target[0], p[1] - cam.target[1], p[2] - cam.target[2]];
    return [dot(v, cam.r), dot(v, cam.u), cam.dist - dot(v, cam.b)];
  }

  function toScreen(q, cam) {
    const s = cam.focal / q[2];
    return [cam.cx + q[0] * s, cam.cy - q[1] * s];
  }

  function clipSegment(a, b) {           // keep the part of a view-space segment in front of the camera
    if (a[2] < NEAR && b[2] < NEAR) return null;
    if (a[2] >= NEAR && b[2] >= NEAR) return [a, b];
    const [p, q] = a[2] < NEAR ? [a, b] : [b, a];
    const k = (NEAR - p[2]) / (q[2] - p[2]);
    const c = [p[0] + (q[0] - p[0]) * k, p[1] + (q[1] - p[1]) * k, NEAR];
    return a[2] < NEAR ? [c, b] : [a, c];
  }

  // ---- drawing ---------------------------------------------------------------------------------

  function line(ctx, cam, a, b) {
    const seg = clipSegment(toView(a, cam), toView(b, cam));
    if (!seg) return;
    const p = toScreen(seg[0], cam), q = toScreen(seg[1], cam);
    ctx.beginPath(); ctx.moveTo(p[0], p[1]); ctx.lineTo(q[0], q[1]); ctx.stroke();
  }

  function drawGrid(ctx, cam, scene, floor) {
    const { half, step } = scene.home.grid;
    const cx = Math.round(cam.target[0] / step) * step, cz = Math.round(cam.target[2] / step) * step;
    ctx.strokeStyle = 'rgba(136,136,136,0.27)'; ctx.lineWidth = cam.dpr;
    for (let g = -half; g <= half + 1e-9; g += step) {
      line(ctx, cam, [cx + g, floor, cz - half], [cx + g, floor, cz + half]);
      line(ctx, cam, [cx - half, floor, cz + g], [cx + half, floor, cz + g]);
    }
  }

  function drawAxes(ctx, cam, scene) {
    const { labels, length } = scene.home.axes;
    const dirs = [[length, 0, 0], [0, length, 0], [0, 0, length]], colours = ['#d33', '#3a3', '#36d'];
    const o = cam.target;
    ctx.font = `${11 * cam.dpr}px system-ui, sans-serif`;
    dirs.forEach((d, i) => {
      const end = [o[0] + d[0], o[1] + d[1], o[2] + d[2]];
      ctx.strokeStyle = ctx.fillStyle = colours[i]; ctx.lineWidth = 2 * cam.dpr;
      line(ctx, cam, o, end);
      const q = toView(end, cam);
      if (q[2] >= NEAR) { const s = toScreen(q, cam); ctx.fillText(labels[i], s[0] + 4 * cam.dpr, s[1]); }
    });
  }

  function personBones(person, cam) {    // view-space bones with their tone and mean distance
    const v = person.pts.map(p => toView(p, cam));
    return BONES.map(([a, b], i) => ({ seg: clipSegment(v[a], v[b]), tone: boneTone[i], person, z: (v[a][2] + v[b][2]) / 2 }))
      .filter(b => b.seg);
  }

  function drawPeople(ctx, cam, scene, people) {
    const bones = [];
    for (const p of people) bones.push(...personBones(p, cam));
    bones.sort((u, v) => v.z - u.z);     // far first
    ctx.lineCap = 'round';
    for (const b of bones) {
      const colour = scene.colors[b.person.id];
      ctx.strokeStyle = b.tone === 'main' ? colour : b.tone === 'dark' ? shade(colour) : '#bbb';
      ctx.lineWidth = Math.min(10, Math.max(1.5, 0.035 * cam.ppm / b.z)) * cam.dpr;
      const p = toScreen(b.seg[0], cam), q = toScreen(b.seg[1], cam);
      ctx.beginPath(); ctx.moveTo(p[0], p[1]); ctx.lineTo(q[0], q[1]); ctx.stroke();
    }
    for (const person of people) drawJoints(ctx, cam, person);
    if (scene.ids.length > 1) for (const person of people) drawLabel(ctx, cam, scene, person);
  }

  function drawJoints(ctx, cam, person) {
    person.pts.forEach((pt, i) => {
      const q = toView(pt, cam);
      if (q[2] < NEAR) return;
      const s = toScreen(q, cam);
      ctx.fillStyle = person.conf[i] < 0.5 ? 'rgba(255,255,255,0.45)' : '#fff';
      ctx.beginPath(); ctx.arc(s[0], s[1], Math.min(6, Math.max(1.2, 0.02 * cam.ppm / q[2])) * cam.dpr, 0, 7); ctx.fill();
    });
  }

  function drawLabel(ctx, cam, scene, person) {
    const q = toView(person.pts[0], cam);
    if (q[2] < NEAR) return;
    const s = toScreen(q, cam);
    ctx.font = `${12 * cam.dpr}px system-ui, sans-serif`;
    ctx.lineWidth = 3 * cam.dpr; ctx.strokeStyle = 'rgba(0,0,0,0.6)'; ctx.fillStyle = scene.colors[person.id];
    const text = 'id ' + person.id, x = s[0] + 8 * cam.dpr, y = s[1] - 10 * cam.dpr;
    ctx.strokeText(text, x, y); ctx.fillText(text, x, y);
  }

  // ---- the viewer ------------------------------------------------------------------------------

  const defaultTimers = { set: (fn, ms) => setInterval(fn, ms), clear: id => clearInterval(id) };
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

  function frameInterval(frames) {
    const dt = [];
    for (let i = 1; i < frames.length; i++) dt.push(frames[i].t_ms - frames[i - 1].t_ms);
    dt.sort((a, b) => a - b);
    return clamp(dt.length ? dt[Math.floor(dt.length / 2)] : 100, 40, 500);
  }

  function create(canvas, options) {
    const timers = (options && options.timers) || defaultTimers;
    const ctx = canvas.getContext('2d');
    const st = { scene: null, frame: 0, az: HOME.az, el: HOME.el, dist: 3, target: [0, 0, 0], timer: null, w: 300, h: 300, dpr: 1, queued: false };
    const listeners = { frame: [], play: [], camera: [] };
    const emit = name => listeners[name].forEach(fn => fn());
    const home = () => st.scene && st.scene.home;

    function cameraState() {
      const basis = viewBasis(st.az, st.el), ppm = FOCAL * Math.min(st.w, st.h);   // CSS px per metre at 1 m
      return { ...basis, target: st.target, dist: st.dist, dpr: st.dpr, ppm, focal: ppm * st.dpr, cx: st.w * st.dpr / 2, cy: st.h * st.dpr / 2 };
    }

    function draw() {
      st.queued = false;
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      if (!st.scene) return;
      const cam = cameraState(), frame = st.scene.frames[st.frame], people = frame ? frame.people : [];
      const floor = people.length ? Math.min(...people.flatMap(p => p.pts.map(q => q[1]))) : home().floor;
      drawGrid(ctx, cam, st.scene, floor);
      drawAxes(ctx, cam, st.scene);
      if (people.length) drawPeople(ctx, cam, st.scene, people);
      else drawNote(cam);
    }

    function drawNote(cam) {
      ctx.fillStyle = '#888'; ctx.font = `${13 * cam.dpr}px system-ui, sans-serif`; ctx.textAlign = 'center';
      ctx.fillText('Nobody was found in this frame.', cam.cx, cam.cy * 1.8);
      ctx.textAlign = 'start';
    }

    function redraw() {                  // one draw per animation frame, however many events arrive
      if (typeof root.requestAnimationFrame !== 'function') return draw();
      if (st.queued) return;
      st.queued = true;
      root.requestAnimationFrame(draw);
    }

    function resize() {
      const r = canvas.getBoundingClientRect ? canvas.getBoundingClientRect() : { width: st.w, height: st.h };
      st.dpr = root.devicePixelRatio || 1;
      st.w = Math.max(1, r.width); st.h = Math.max(1, r.height);
      const w = Math.round(st.w * st.dpr), h = Math.round(st.h * st.dpr);
      if (canvas.width !== w) canvas.width = w;
      if (canvas.height !== h) canvas.height = h;
      redraw();
    }

    function setCamera(az, el, dist) {
      st.az = az; st.el = clamp(el, -Math.PI / 2, Math.PI / 2);
      if (dist !== undefined) { const d = home().dist; st.dist = clamp(dist, d * ZOOM.min, d * ZOOM.max); }
      emit('camera'); redraw();
    }

    function setFrame(i) {
      if (!st.scene) return;
      st.frame = clamp(Math.round(i), 0, st.scene.frames.length - 1);
      emit('frame'); redraw();
    }

    function step(delta) {
      const n = st.scene ? st.scene.frames.length : 0;
      if (n) setFrame(((st.frame + delta) % n + n) % n);
    }

    function pause() {
      if (!st.timer) return;
      timers.clear(st.timer); st.timer = null; emit('play');
    }

    function play() {
      if (st.timer || !st.scene || st.scene.frames.length < 2) return;
      st.timer = timers.set(() => step(1), frameInterval(st.scene.frames));
      emit('play');
    }

    function reset() {
      const h = home();
      if (!h) return;
      st.target = h.target.slice();
      st.az = h.az; st.el = h.el; st.dist = h.dist;
      emit('camera'); redraw();
    }

    function setScene(scene) {
      pause();
      st.scene = scene; st.frame = 0;
      reset(); emit('frame');
    }

    const VIEWS = { front: [0, 0], side: [Math.PI / 2, 0], top: [0, Math.PI / 2] };
    function view(name) { const v = VIEWS[name]; if (v && st.scene) setCamera(v[0], v[1]); }

    attachPointer(canvas, st, setCamera, home);
    if (typeof root.ResizeObserver === 'function') new root.ResizeObserver(resize).observe(canvas);
    else if (root.addEventListener) root.addEventListener('resize', resize);
    resize();

    return {
      setScene, setFrame, step, play, pause, reset, view, resize, draw,
      toggle: () => (st.timer ? pause() : play()),
      on: (name, fn) => listeners[name].push(fn),
      camera: () => orbitPosition(st.az, st.el, st.dist, st.target),
      target: () => st.target.slice(),
      distance: () => st.dist,
      frame: () => st.frame,
      frameCount: () => (st.scene ? st.scene.frames.length : 0),
      playing: () => st.timer !== null,
      current: () => (st.scene && st.scene.frames[st.frame]) || null,
      people: () => (st.scene && st.scene.frames[st.frame] ? st.scene.frames[st.frame].people.map(p => p.id) : []),
      colors: () => (st.scene ? { ...st.scene.colors } : {}),
    };
  }

  /* Drag to orbit, wheel to zoom, two fingers to pinch. Pointer events cover mouse, pen and touch. */
  function attachPointer(canvas, st, setCamera, home) {
    const pointers = new Map();
    let drag = null, pinch = null;
    const spread = () => { const [a, b] = [...pointers.values()]; return Math.hypot(a.x - b.x, a.y - b.y) || 1; };
    const rebase = () => {               // a new baseline whenever the set of pointers changes
      const first = pointers.values().next().value;
      drag = pointers.size === 1 ? { x: first.x, y: first.y, az: st.az, el: st.el } : null;
      pinch = pointers.size === 2 ? { d: spread(), dist: st.dist } : null;
    };

    canvas.addEventListener('pointerdown', e => {
      if (canvas.setPointerCapture) canvas.setPointerCapture(e.pointerId);
      pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
      rebase();
    });
    canvas.addEventListener('pointermove', e => {
      if (!pointers.has(e.pointerId) || !home()) return;
      pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
      if (pinch) setCamera(st.az, st.el, pinch.dist * pinch.d / spread());
      else if (drag) setCamera(drag.az - (e.clientX - drag.x) * 0.01, drag.el + (e.clientY - drag.y) * 0.01);
    });
    const end = e => { pointers.delete(e.pointerId); rebase(); };
    canvas.addEventListener('pointerup', end);
    canvas.addEventListener('pointercancel', end);
    canvas.addEventListener('wheel', e => {
      e.preventDefault();
      if (home()) setCamera(st.az, st.el, st.dist * Math.exp(e.deltaY * 0.001));
    }, { passive: false });
  }

  return { JOINTS, BONES, PALETTE, colorFor, shade, buildScene, orbitPosition, viewBasis, create };
});
