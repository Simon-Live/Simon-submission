/* 2D overlay for the Part 2 web app: each person's projected joints and bones drawn over the frame picture,
 * one colour per id (the palette and rule of part2.demo.color_for, through Viewer.colorFor), a legend listing
 * the ids with their colours, and a person picker that sends one id to the 3D panel (docs/specs/run-app.md).
 *
 * Projection as part2.canonical.project_pose3d: p_cam = R p + t with the person's camera.json pose, then
 * u = fx x / z + cx and v = fy y / z + cy with camera.json K. Pixels are those of camera.json image_size; the
 * picture is shown with object-fit: contain, so the overlay applies the same fit.
 */
(function (root, factory) {
  const api = factory(root);
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.Overlay = api;
})(typeof self !== 'undefined' ? self : globalThis, function (root) {
  'use strict';

  const V = root.Viewer || (typeof require === 'function' ? require('./viewer.js') : null);
  const JOINTS = V.JOINTS, BONES = V.BONES;
  const tone = BONES.map(([a, b]) => {   // left bones in the colour, right bones darker, midline grey (as in 3D)
    const names = [JOINTS[a], JOINTS[b]];
    return names.some(n => n.startsWith('left')) ? 'main' : names.some(n => n.startsWith('right')) ? 'dark' : 'grey';
  });

  // ---- data ------------------------------------------------------------------------------------

  /* {"<frame>:<id>": [[u, v] or null per joint]} for every person with a camera pose in that frame. */
  function project(pose3d, camera) {
    const K = camera.K, cams = new Map(), out = {};
    for (const f of camera.frames || []) for (const c of f.people) cams.set(f.frame + ':' + c.id, c);
    for (const f of pose3d.frames) {
      for (const p of f.people) {
        const c = cams.get(f.frame + ':' + p.id);
        if (!c || !p.joints) continue;
        const R = c.R, t = c.t;
        out[f.frame + ':' + p.id] = JOINTS.map(name => {
          const j = p.joints[name];
          if (!j) return null;
          const x = R[0][0] * j.x + R[0][1] * j.y + R[0][2] * j.z + t[0];
          const y = R[1][0] * j.x + R[1][1] * j.y + R[1][2] * j.z + t[1];
          const z = R[2][0] * j.x + R[2][1] * j.y + R[2][2] * j.z + t[2];
          return z > 1e-6 ? [x / z * K[0][0] + K[0][2], y / z * K[1][1] + K[1][2]] : null;
        });
      }
    }
    return out;
  }

  function ids(pose3d) {
    const seen = new Set();
    for (const f of pose3d.frames) for (const p of f.people) seen.add(p.id);
    return [...seen].sort((a, b) => (typeof a === 'number' && typeof b === 'number') ? a - b : String(a).localeCompare(String(b)));
  }

  /* pose3d with only person `id` in each frame (every frame kept, so frame indices stay aligned). */
  function onlyPerson(pose3d, id) {
    return { ...pose3d, frames: pose3d.frames.map(f => ({ ...f, people: f.people.filter(p => p.id === id) })) };
  }

  /* The 3D scene of one person in the canonical frame (x left, y up, z anterior), as for a one-person output. */
  function personScene(pose3d, camera, id) {
    return V.buildScene(onlyPerson(pose3d, id), camera, 'canonical');
  }

  /* Where a w x h picture lands in a box of bw x bh with object-fit: contain. */
  function fit(w, h, bw, bh) {
    const s = Math.min(bw / w, bh / h);
    return { s, ox: (bw - w * s) / 2, oy: (bh - h * s) / 2 };
  }

  // ---- drawing ---------------------------------------------------------------------------------

  function create(canvas) {
    const ctx = canvas.getContext('2d');
    const st = { pose3d: null, size: [1, 1], points: {}, ids: [], colors: {}, frame: 0, picked: null, w: 1, h: 1, dpr: 1 };

    function current() { return st.pose3d ? st.pose3d.frames[st.frame] : null; }

    function drawn() {
      const f = current();
      return f ? f.people.filter(p => st.points[f.frame + ':' + p.id]).map(p => p.id) : [];
    }

    function drawPerson(f, id, k) {
      const pts = st.points[f.frame + ':' + id];
      const colour = st.colors[id], big = st.picked === null || st.picked === id;
      const at = q => [(k.ox + q[0] * k.s) * st.dpr, (k.oy + q[1] * k.s) * st.dpr];
      ctx.lineCap = 'round';
      ctx.lineWidth = (big ? 3 : 1.5) * st.dpr;
      BONES.forEach(([a, b], i) => {
        if (!pts[a] || !pts[b]) return;
        const p = at(pts[a]), q = at(pts[b]);
        ctx.strokeStyle = tone[i] === 'main' ? colour : tone[i] === 'dark' ? V.shade(colour) : '#bbb';
        ctx.beginPath(); ctx.moveTo(p[0], p[1]); ctx.lineTo(q[0], q[1]); ctx.stroke();
      });
      ctx.fillStyle = colour;
      for (const q of pts) {
        if (!q) continue;
        const p = at(q);
        ctx.beginPath(); ctx.arc(p[0], p[1], (big ? 3 : 2) * st.dpr, 0, 7); ctx.fill();
      }
      if (st.ids.length > 1) {
        const top = pts.filter(Boolean).reduce((m, q) => (q[1] < m[1] ? q : m), [0, Infinity]);
        const p = at(top);
        ctx.font = `${12 * st.dpr}px system-ui, sans-serif`;
        ctx.lineWidth = 3 * st.dpr; ctx.strokeStyle = 'rgba(0,0,0,0.6)';
        ctx.strokeText('id ' + id, p[0] + 6 * st.dpr, p[1] - 8 * st.dpr);
        ctx.fillText('id ' + id, p[0] + 6 * st.dpr, p[1] - 8 * st.dpr);
      }
    }

    function draw() {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      const f = current();
      if (!f) return;
      const k = fit(st.size[0], st.size[1], st.w, st.h);
      const order = drawn().sort((a, b) => (a === st.picked) - (b === st.picked));   // the picked person on top
      for (const id of order) drawPerson(f, id, k);
    }

    function resize() {
      const r = canvas.getBoundingClientRect ? canvas.getBoundingClientRect() : { width: st.w, height: st.h };
      st.dpr = root.devicePixelRatio || 1;
      st.w = Math.max(1, r.width); st.h = Math.max(1, r.height);
      const w = Math.round(st.w * st.dpr), h = Math.round(st.h * st.dpr);
      if (canvas.width !== w) canvas.width = w;
      if (canvas.height !== h) canvas.height = h;
      draw();
    }

    if (typeof root.ResizeObserver === 'function') new root.ResizeObserver(resize).observe(canvas);
    else if (root.addEventListener) root.addEventListener('resize', resize);
    resize();

    return {
      setData(pose3d, camera) {
        st.pose3d = pose3d; st.points = project(pose3d, camera);
        st.size = (camera && camera.image_size) || [1, 1];
        st.ids = ids(pose3d); st.colors = {};
        for (const id of st.ids) st.colors[id] = V.colorFor(id);
        st.frame = 0; st.picked = null; draw();
      },
      clear() { st.pose3d = null; st.points = {}; st.ids = []; st.colors = {}; draw(); },
      setFrame(i) { st.frame = i; draw(); },
      pick(id) { st.picked = id; draw(); },
      people: drawn,
      ids: () => st.ids.slice(),
      colors: () => ({ ...st.colors }),
      points: (i, id) => { const f = st.pose3d && st.pose3d.frames[i]; return f ? st.points[f.frame + ':' + id] || null : null; },
      resize, draw,
    };
  }

  // ---- legend and person picker ----------------------------------------------------------------

  function fillLegend(list, idList, colors) {
    const doc = list.ownerDocument;
    list.replaceChildren();
    for (const id of idList) {
      const li = doc.createElement('li'), swatch = doc.createElement('span'), label = doc.createElement('span');
      li.dataset.id = String(id);
      swatch.className = 'swatch'; swatch.style.background = colors[id];
      label.textContent = 'id ' + id;
      li.append(swatch, label);
      list.append(li);
    }
  }

  function markPresent(list, present) {
    const here = new Set(present.map(String));
    for (const li of list.children) li.classList.toggle('absent', !here.has(li.dataset.id));
  }

  function fillPicker(select, idList) {
    const doc = select.ownerDocument;
    select.replaceChildren();
    for (const id of idList) {
      const o = doc.createElement('option');
      o.value = String(id); o.textContent = 'id ' + id;
      select.append(o);
    }
  }

  /* The id an option value names (ids are integers in pose3d.json; any other id is kept as text). */
  function idOf(value, idList) { return idList.find(id => String(id) === value); }

  return { project, ids, onlyPerson, personScene, fit, create, fillLegend, markPresent, fillPicker, idOf };
});
