/* Run page of the Part 2 web app (docs/specs/run-app.md "Pages", TICKET-025).
 * Pick a sample or upload a video or photo, run it on the server's queue, follow its progress, then see the
 * frames with the overlay beside one person at a time in 3D, and download pose3d.json and tracks.json.
 * Every URL is relative. window.app holds read-only hooks for the verify suite (the page contract).
 */
(function () {
  'use strict';

  const $ = id => document.getElementById(id);
  const POLL_MS = 1000;
  const FINISHED = new Set(['done', 'failed', 'cancelled']);
  const STAGES = { frames: 'reading frames', track: 'tracking people', pose: 'estimating 3D poses', write: 'writing files' };
  const TEXT = {
    tooLarge: 'The file is too large. Videos can be up to 200 MB and photos up to 20 MB.',
    noFile: 'Choose a video or photo first, or pick a sample.',
    offline: 'The server could not be reached. Check your connection and try again.',
    failed: 'The run stopped with an error. Try another file, or try again later.',
    gone: 'This job is no longer on the server. Run it again.',
    noCaps: 'This server could not say what it can run. Reload the page to try again.',
    noBackend: 'No backend is available here right now.',
    noResult: 'The result could not be loaded. Reload the page to try again.',
  };

  const app = window.app = {
    ready: false, output: null, job: null, runs: 0,
    frame: 0, frameCount: 0, playing: false, people: [], colors: {}, person: null, viewerPeople: [],
    camera: () => [0, 0, 0], target: () => [0, 0, 0],
  };

  const viewer = Viewer.create($('viewer')), overlay = Overlay.create($('overlay'));
  const state = { caps: null, jobId: null, timer: null, misses: 0, result: null, person: null };

  Object.defineProperties(app, {
    frame: { get: () => viewer.frame() }, frameCount: { get: () => viewer.frameCount() },
    playing: { get: () => viewer.playing() },
    people: { get: () => (state.result ? overlay.people() : []) },
    colors: { get: () => (state.result ? overlay.colors() : {}) },
    person: { get: () => state.person },
    viewerPeople: { get: () => viewer.people() },
  });
  app.camera = () => viewer.camera();
  app.target = () => viewer.target();

  // ---- small helpers ---------------------------------------------------------------------------

  async function getJSON(url) {
    const r = await fetch(url, { cache: 'no-store' });
    if (!r.ok) { const e = new Error('status ' + r.status); e.status = r.status; throw e; }
    return r.json();
  }

  function make(tag, text, parent) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (parent) parent.append(node);
    return node;
  }

  const setStatus = text => { $('status').textContent = text; };
  function showAlert(text) { const a = $('alert'); a.textContent = text || ''; a.hidden = !text; }
  function showNotice(text) { const n = $('notice'); n.textContent = text || ''; n.hidden = !text; }
  const checked = name => document.querySelector(`input[name="${name}"]:checked`);

  // ---- the form --------------------------------------------------------------------------------

  function fillSamples(samples) {
    const box = $('sample-options');
    box.replaceChildren();
    samples.forEach((s, i) => {
      const label = make('label', undefined, box), input = make('input', undefined, label);
      label.className = 'choice';
      input.type = 'radio'; input.name = 'input'; input.id = 'input-sample-' + s.id; input.value = s.id;
      input.dataset.mode = s.mode; input.checked = i === 0;
      label.append(' ' + s.title);
    });
    if (!samples.length) $('input-file').checked = true;
  }

  function fillSelect(select, entries) {
    select.replaceChildren();
    for (const e of entries) {
      let text = e.name === 'automatic' && e.runs ? `${e.label} (now ${e.runs})` : e.label;
      if (e.approximate) text += ', 3D approximate';
      if (!e.available) text += ` (not available: ${e.reason})`;
      const o = make('option', text, select);
      o.value = e.name; o.disabled = !e.available;
    }
    const first = entries.find(e => e.available);
    if (first) select.value = first.name;
    return Boolean(first);
  }

  function syncForm() {
    const busy = state.jobId !== null;
    const isClass = checked('mode') && checked('mode').value === 'class';
    $('tracker-select').disabled = !isClass || !state.caps;
    $('tracker-hint').hidden = isClass;
    const anyBackend = state.caps && state.caps.backends.some(b => b.available);
    $('run-button').disabled = busy || !anyBackend;
    $('cancel-button').disabled = !busy;
  }

  function onInputChange(e) {
    const t = e.target;
    if (t.name === 'input' && t.dataset.mode) $('mode-' + t.dataset.mode).checked = true;
    if (t.id === 'file-input' && t.files.length) $('input-file').checked = true;
    syncForm();
  }

  function formData() {
    const fd = new FormData(), mode = checked('mode').value, input = checked('input');
    fd.append('mode', mode);
    fd.append('backend', $('backend-select').value);
    if (mode === 'class') fd.append('tracker', $('tracker-select').value);
    if (!input || input.value === 'file') {
      const file = $('file-input').files[0];
      if (!file) return { error: TEXT.noFile };
      const limits = state.caps.limits, photo = /^image\//.test(file.type);
      if (file.size > (photo ? limits.photo_mb : limits.video_mb) * 1e6) return { error: TEXT.tooLarge };
      fd.append('file', file, 'upload');          // the server never uses the visitor's file name
    } else {
      fd.append('sample', input.value);
    }
    return { fd };
  }

  function post(fd) {
    return new Promise(resolve => {
      const x = new XMLHttpRequest();
      x.open('POST', 'api/jobs');
      x.upload.onprogress = e => { if (e.lengthComputable) setStatus(`Uploading: ${Math.round(100 * e.loaded / e.total)}%.`); };
      x.onload = () => {
        let body = null;
        try { body = JSON.parse(x.responseText); } catch (err) { body = null; }
        resolve({ status: x.status, body });
      };
      x.onerror = x.onabort = x.ontimeout = () => resolve({ status: 0, body: null });
      x.send(fd);
    });
  }

  async function submit(e) {
    e.preventDefault();
    if (state.jobId !== null || !state.caps) return;
    showAlert(''); showNotice('');
    app.job = null;                                   // the hook follows the new run only
    const { fd, error } = formData();
    if (error) { showAlert(error); app.runs += 1; return; }
    $('result').hidden = true; state.result = null; state.person = null; overlay.clear();
    $('run-button').disabled = true;
    setStatus(checked('input') && checked('input').value !== 'file' ? 'Sending the request.' : 'Uploading: 0%.');
    const r = await post(fd);
    if (r.status !== 202 || !r.body || !r.body.id) {
      setStatus('');
      showAlert(r.body && r.body.error ? r.body.error : TEXT.offline);
      app.runs += 1; syncForm();
      return;
    }
    state.jobId = r.body.id; state.misses = 0;
    app.job = { id: r.body.id, state: r.body.state, progress: { stage: null, done: 0, total: 0 }, backend: null, tracker: null };
    syncForm();
    poll();
  }

  // ---- following a job -------------------------------------------------------------------------

  function statusText(job) {
    const p = job.progress || {};
    if (job.state === 'queued') return job.position > 0 ? `Queued. Jobs ahead of yours: ${job.position}.` : 'Queued. Yours is next.';
    if (job.state === 'waiting-gpu') return 'Waiting for the GPU to have enough free memory.';
    if (job.state === 'running') {
      if (!p.stage) return 'Running.';
      return `Running: ${STAGES[p.stage] || p.stage}` + (p.total ? `, ${p.done} of ${p.total}.` : '.');
    }
    if (job.state === 'done') return job.started && job.ended ? `Done in ${Math.max(1, Math.round(job.ended - job.started))} s.` : 'Done.';
    if (job.state === 'cancelled') return 'Cancelled.';
    return 'The job failed.';
  }

  function track(job) {
    app.job = { id: job.id, state: job.state, progress: job.progress, backend: job.backend, tracker: job.tracker,
      lifter: job.lifter, notice: job.notice, fallback: job.fallback, error: job.error, position: job.position };
    setStatus(statusText(job));
  }

  async function poll() {
    const id = state.jobId;
    if (id === null) return;
    let job;
    try {
      job = await getJSON('api/jobs/' + encodeURIComponent(id));
    } catch (e) {
      if (e.status === 404) { finish(null, TEXT.gone); return; }
      state.misses += 1;
      if (state.misses >= 3) setStatus('Lost contact with the server. Trying again.');
      state.timer = setTimeout(poll, POLL_MS * Math.min(5, state.misses + 1));
      return;
    }
    if (id !== state.jobId) return;
    state.misses = 0;
    track(job);
    if (FINISHED.has(job.state)) finish(job);
    else state.timer = setTimeout(poll, POLL_MS);
  }

  async function finish(job, message) {
    clearTimeout(state.timer);
    state.jobId = null;
    app.runs += 1;
    syncForm();
    if (!job) { setStatus(''); showAlert(message); return; }
    showNotice(job.notice);
    if (job.state === 'failed') showAlert(job.error || TEXT.failed);
    if (job.state === 'done') await showResult(job);
  }

  async function cancel() {
    const id = state.jobId;
    if (id === null) return;
    $('cancel-button').disabled = true;
    try {
      const r = await fetch('api/jobs/' + encodeURIComponent(id) + '/cancel', { method: 'POST', cache: 'no-store' });
      if (!r.ok) {
        const body = await r.json().catch(() => null);
        if (r.status !== 409) showAlert(body && body.error ? body.error : TEXT.offline);
      }
    } catch (e) {
      showAlert(TEXT.offline);
    }
    clearTimeout(state.timer);
    poll();
  }

  // ---- the result ------------------------------------------------------------------------------

  function showPerson(id) {
    const r = state.result, keep = viewer.frame(), playing = viewer.playing();
    state.person = id;
    viewer.setScene(id === null ? Viewer.buildScene(r.pose3d, r.camera, 'canonical') : Overlay.personScene(r.pose3d, r.camera, id));
    viewer.setFrame(keep);
    if (playing) viewer.play();
    overlay.pick(id);
    if (id !== null) $('person-select').value = String(id);
  }

  function showFrame() {
    const r = state.result;
    if (!r) return;
    const i = viewer.frame(), f = r.pose3d.frames[i];
    $('frame-slider').value = i;
    overlay.setFrame(i);
    const here = overlay.people();
    $('frame-info').textContent = f
      ? `${i + 1} of ${r.pose3d.frames.length}, ${(f.t_ms / 1000).toFixed(2)} s` + (here.length ? '' : ', nobody found') : '';
    Overlay.markPresent($('legend'), here);
    const img = $('frame-img'), url = r.frames[i];
    img.hidden = !url;
    if (url && img.getAttribute('src') !== url) img.src = url;
    img.alt = f ? 'Picture for frame ' + f.frame : '';
  }

  function resultLine(job, frames) {
    const tracker = job.tracker || (job.mode === 'single' ? 'none (one person mode)' : 'not recorded');
    let text = `Backend: ${job.backend}. Tracker: ${tracker}. Lifter: ${job.lifter || 'none'}. `;
    text += `${frames} ${frames === 1 ? 'frame' : 'frames'}.`;
    if (job.approximate) text += ' 3D approximate: the CPU backend misses the 3D accuracy bar.';
    return text;
  }

  async function showResult(job) {
    const base = 'api/jobs/' + encodeURIComponent(job.id) + '/files/';
    let pose3d, camera;
    try {
      [pose3d, camera] = await Promise.all([getJSON(base + 'pose3d.json'), getJSON(base + 'camera.json')]);
    } catch (e) {
      showAlert(TEXT.noResult); return;
    }
    const ids = Overlay.ids(pose3d), multi = job.mode === 'class' || ids.length > 1;
    state.result = { job, pose3d, camera, ids, frames: pose3d.frames.map(f => base + 'frames/' + f.frame + '.jpg') };
    $('result').hidden = false;
    viewer.resize(); overlay.resize();
    overlay.setData(pose3d, camera);
    Overlay.fillLegend($('legend'), ids, overlay.colors());
    Overlay.fillPicker($('person-select'), ids);
    $('legend').hidden = $('person-picker').hidden = !multi;
    viewer.setFrame(0);
    showPerson(ids.length ? ids[0] : null);
    const slider = $('frame-slider');
    slider.max = Math.max(0, pose3d.frames.length - 1); slider.disabled = pose3d.frames.length < 2;
    $('result-line').textContent = resultLine(job, pose3d.frames.length);
    $('download-tracks').hidden = !job.files.includes('tracks.json');
    showFrame();
  }

  function download(name) {
    const r = state.result;
    if (!r) return;
    const a = document.createElement('a');
    a.href = 'api/jobs/' + encodeURIComponent(r.job.id) + '/files/' + name;
    a.download = name;
    document.body.append(a);
    a.click();
    a.remove();
  }

  // ---- start -----------------------------------------------------------------------------------

  async function init() {
    let caps;
    try { caps = await getJSON('api/capabilities'); } catch (e) { setStatus(''); showAlert(TEXT.noCaps); return; }
    state.caps = caps;
    fillSamples(caps.samples);
    const anyBackend = fillSelect($('backend-select'), caps.backends);
    fillSelect($('tracker-select'), caps.trackers);
    $('backend-select').disabled = !anyBackend;
    setStatus(anyBackend ? '' : TEXT.noBackend);
    syncForm();
    app.ready = true;
  }

  $('run-form').addEventListener('change', onInputChange);
  $('run-form').addEventListener('submit', submit);
  $('cancel-button').addEventListener('click', cancel);
  $('person-select').addEventListener('change', () => showPerson(Overlay.idOf($('person-select').value, state.result.ids)));
  $('download-pose3d').addEventListener('click', () => download('pose3d.json'));
  $('download-tracks').addEventListener('click', () => download('tracks.json'));
  Viewer.bindControls(viewer, $);
  viewer.on('frame', showFrame);
  init().catch(() => { setStatus(''); showAlert('This page could not finish loading. Reload it to try again.'); });
})();
