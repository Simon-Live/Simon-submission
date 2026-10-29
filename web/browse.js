/* Browse page and contract page of the Part 2 web app (docs/specs/run-app.md).
 * Every URL is relative, so the app runs at the root and under a gateway prefix.
 * window.app holds read-only hooks for the verify suite ("Page contract shared with the verify suite").
 */
(function () {
  'use strict';

  const $ = id => document.getElementById(id);
  const app = window.app = {
    ready: false, output: null, job: null, runs: 0,
    frame: 0, frameCount: 0, playing: false, people: [], colors: {},
    camera: () => [0, 0, 0], target: () => [0, 0, 0],
  };

  async function getJSON(url) {
    const r = await fetch(url, { cache: 'no-store' });
    if (!r.ok) throw new Error('status ' + r.status);
    return r.json();
  }

  async function getText(url) {
    const r = await fetch(url, { cache: 'no-store' });
    if (!r.ok) throw new Error('status ' + r.status);
    return r.text();
  }

  function make(tag, text, parent) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (parent) parent.append(node);
    return node;
  }

  const setStatus = text => { $('status').textContent = text; };
  function showAlert(text) { const a = $('alert'); a.textContent = text; a.hidden = !text; }

  // ---- browse page -----------------------------------------------------------------------------

  function initBrowse() {
    const viewer = Viewer.create($('viewer'));
    const view = { frames: [], pictures: false, token: 0 };
    const slider = $('frame-slider'), img = $('frame-img'), select = $('output-select');

    Object.defineProperties(app, {
      frame: { get: () => viewer.frame() }, frameCount: { get: () => viewer.frameCount() },
      playing: { get: () => viewer.playing() }, people: { get: () => viewer.people() },
      colors: { get: () => viewer.colors() },
    });
    app.camera = () => viewer.camera();
    app.target = () => viewer.target();

    function showPicture(i) {
      const url = view.frames[i] && view.frames[i].url;
      img.hidden = !url;
      $('frame-empty').hidden = view.pictures;
      if (url && img.getAttribute('src') !== url) img.src = url;
      img.alt = url ? 'Picture for frame ' + (view.frames[i].frame) : '';
    }

    function showFrame() {
      const i = viewer.frame(), f = viewer.current();
      slider.value = i;
      $('frame-info').textContent = f
        ? `${i + 1} of ${viewer.frameCount()}, ${(f.t_ms / 1000).toFixed(2)} s` + (f.people.length ? '' : ', nobody found') : '';
      const here = new Set(viewer.people().map(String));
      for (const li of $('legend').children) li.classList.toggle('absent', !here.has(li.dataset.id));
      showPicture(i);
    }

    function fillLegend(scene) {
      const legend = $('legend');
      legend.replaceChildren();
      legend.hidden = scene.ids.length < 2;
      for (const id of scene.ids) {
        const li = make('li', undefined, legend);
        li.dataset.id = String(id);
        make('span', undefined, li).className = 'swatch';
        li.firstChild.style.background = scene.colors[id];
        make('span', 'id ' + id, li);
      }
    }

    function fillSource(o) {
      const line = $('source-line');
      line.replaceChildren();
      const s = o.source;
      let text = s ? `Clip: ${s.title}${s.author ? ' by ' + s.author : ''} (${s.licence}). ` : 'Clip: not recorded. ';
      text += `Backend: ${o.backend || 'not recorded'}. Tracker: ${o.tracker || (o.mode === 'single' ? 'none' : 'not recorded')}. `;
      text += `${o.people} ${o.people === 1 ? 'person' : 'people'}, ${o.frames} frames. `;
      line.append(text);
      if (s && s.url) { const a = make('a', 'Clip page', line); a.href = s.url; a.rel = 'noopener'; }
    }

    async function showOutput(id) {
      const token = ++view.token;
      setStatus('Loading this output.'); showAlert('');
      let data;
      try { data = await getJSON('api/outputs/' + encodeURIComponent(id)); } catch (e) {
        if (token === view.token) { setStatus(''); showAlert('This output could not be loaded. Pick another one or reload the page.'); }
        return;
      }
      if (token !== view.token) return;               // a newer pick is loading
      const scene = Viewer.buildScene(data.pose3d, data.camera);
      view.frames = data.frames; view.pictures = data.output.has_pictures;
      viewer.setScene(scene);
      slider.max = Math.max(0, scene.frames.length - 1); slider.disabled = scene.frames.length < 2;
      fillLegend(scene); fillSource(data.output); showFrame();
      select.value = id; history.replaceState(null, '', '#' + encodeURIComponent(id));
      app.output = id; setStatus('');
    }

    async function init() {
      let outputs;
      try { outputs = await getJSON('api/outputs'); } catch (e) {
        setStatus(''); showAlert('The outputs could not be loaded. Reload the page to try again.'); return;
      }
      if (!outputs.length) { setStatus('No outputs are available on this server.'); return; }
      for (const o of outputs) make('option', `${o.title} (${o.id})`, select).value = o.id;
      select.disabled = false;
      select.addEventListener('change', () => showOutput(select.value));
      const wanted = decodeURIComponent(location.hash.slice(1));
      await showOutput(outputs.some(o => o.id === wanted) ? wanted : outputs[0].id);
      app.ready = true;
    }

    wireControls(viewer, slider);
    viewer.on('frame', showFrame);
    viewer.on('play', () => { $('play-toggle').textContent = viewer.playing() ? 'Pause' : 'Play'; });
    return init();
  }

  function wireControls(viewer, slider) {
    for (const name of ['front', 'side', 'top']) $('view-' + name).addEventListener('click', () => viewer.view(name));
    $('view-reset').addEventListener('click', () => viewer.reset());
    $('play-toggle').addEventListener('click', () => viewer.toggle());
    slider.addEventListener('input', () => viewer.setFrame(+slider.value));
    document.addEventListener('keydown', e => {
      const tag = e.target.tagName;
      if (e.altKey || e.ctrlKey || e.metaKey || tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA') return;
      if (e.key === 'ArrowRight') { e.preventDefault(); viewer.step(1); }
      else if (e.key === 'ArrowLeft') { e.preventDefault(); viewer.step(-1); }
      else if (e.key === ' ' && tag !== 'BUTTON') { e.preventDefault(); viewer.toggle(); }
    });
  }

  // ---- contract page ---------------------------------------------------------------------------

  function renderSchemas(schemas) {
    $('schemas-empty').hidden = schemas.length > 0;
    for (const s of schemas) {
      const tr = make('tr', undefined, $('schemas').tBodies[0]);
      tr.dataset.schema = s.name;
      make('td', s.name, tr); make('td', s.version, tr); make('td', s.direction, tr);
      const a = make('a', s.file, make('td', undefined, tr));
      a.href = s.file; a.download = String(s.file).split('/').pop(); a.dataset.schema = s.name;
    }
  }

  function cellText(v) { return v === null || v === undefined ? '' : typeof v === 'object' ? JSON.stringify(v) : String(v); }

  function renderCompat(rows) {
    $('compat-empty').hidden = rows.length > 0;
    const columns = [];
    for (const row of rows) for (const k of Object.keys(row)) if (!columns.includes(k)) columns.push(k);
    const head = make('tr', undefined, $('compat').tHead);
    for (const k of columns) { const th = make('th', k.replace(/_/g, ' ').replace(/^./, c => c.toUpperCase()), head); th.scope = 'col'; }
    for (const row of rows) {
      const tr = make('tr', undefined, $('compat').tBodies[0]);
      for (const k of columns) make('td', cellText(row[k]), tr);
    }
  }

  // A small Markdown reader for CONTRACT.md: headings, tables, lists, quotes, fences, code, bold, links.
  // Text goes in as text nodes, so nothing in the file can add markup.
  const INLINE = /`([^`]+)`|\*\*([^*]+)\*\*|\[([^\]]+)\]\(([^)\s]+)\)/g;

  function inline(parent, text) {
    let last = 0;
    for (const m of text.matchAll(INLINE)) {
      parent.append(text.slice(last, m.index));
      if (m[1] !== undefined) make('code', m[1], parent);
      else if (m[2] !== undefined) make('strong', m[2], parent);
      else if (/^https?:\/\//.test(m[4])) { const a = make('a', m[3], parent); a.href = m[4]; a.rel = 'noopener'; }
      else make('span', m[3], parent);
      last = m.index + m[0].length;
    }
    parent.append(text.slice(last));
  }

  const cells = row => row.trim().replace(/^\||\|$/g, '').split('|').map(c => c.trim());
  const isRule = s => /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(s || '');
  const startsBlock = s => /^(```|#{1,6}\s|>|\s*[-*]\s|\s*\d+\.\s|\|)/.test(s);

  function renderTable(parent, lines, i) {
    const wrap = make('div', undefined, parent); wrap.className = 'table-wrap';
    const table = make('table', undefined, wrap), tr = make('tr', undefined, make('thead', undefined, table));
    for (const c of cells(lines[i])) inline(make('th', undefined, tr), c);
    const body = make('tbody', undefined, table);
    for (i += 2; i < lines.length && lines[i].trim().startsWith('|'); i++) {
      const row = make('tr', undefined, body);
      for (const c of cells(lines[i])) inline(make('td', undefined, row), c);
    }
    return i;
  }

  function renderList(parent, lines, i) {
    const ordered = /^\s*\d+\./.test(lines[i]), list = make(ordered ? 'ol' : 'ul', undefined, parent);
    for (; i < lines.length && /^\s*([-*]|\d+\.)\s/.test(lines[i]); i++) {
      const item = make('li', undefined, list);
      let text = lines[i].replace(/^\s*([-*]|\d+\.)\s+/, '');
      while (i + 1 < lines.length && /^\s{2,}\S/.test(lines[i + 1]) && !/^\s*([-*]|\d+\.)\s/.test(lines[i + 1])) text += ' ' + lines[++i].trim();
      inline(item, text);
    }
    return i;
  }

  function renderBlock(parent, lines, i) {
    const line = lines[i];
    if (line.startsWith('```')) {
      let end = i + 1;
      while (end < lines.length && !lines[end].startsWith('```')) end++;
      make('code', lines.slice(i + 1, end).join('\n'), make('pre', undefined, parent));
      return end + 1;
    }
    const h = /^(#{1,6})\s+(.*)$/.exec(line);
    if (h) { inline(make('h' + Math.min(h[1].length + 2, 6), undefined, parent), h[2]); return i + 1; }
    if (line.trim().startsWith('|') && isRule(lines[i + 1])) return renderTable(parent, lines, i);
    if (/^\s*([-*]|\d+\.)\s/.test(line)) return renderList(parent, lines, i);
    if (line.startsWith('>')) {
      const quoted = [];
      for (; i < lines.length && lines[i].startsWith('>'); i++) quoted.push(lines[i].replace(/^>\s?/, '').trim());
      inline(make('p', undefined, make('blockquote', undefined, parent)), quoted.join(' '));
      return i;
    }
    const para = [line.trim()];
    for (i++; i < lines.length && lines[i].trim() && !startsBlock(lines[i]); i++) para.push(lines[i].trim());
    inline(make('p', undefined, parent), para.join(' '));
    return i;
  }

  function renderMarkdown(target, text) {
    target.replaceChildren();
    const lines = text.replace(/\r\n?/g, '\n').split('\n');
    for (let i = 0; i < lines.length;) i = lines[i].trim() ? renderBlock(target, lines, i) : i + 1;
  }

  async function initContract() {
    const [contract, doc] = await Promise.allSettled([getJSON('api/contract'), getText('CONTRACT.md')]);
    if (contract.status === 'fulfilled') {
      renderSchemas(contract.value.schemas || []); renderCompat(contract.value.compatibility || []);
    } else {
      showAlert('The schema list is not available right now. Reload the page in a minute.');
    }
    if (doc.status === 'fulfilled') renderMarkdown($('contract-doc'), doc.value);
    else make('p', 'The full text is not available right now.', $('contract-doc')).className = 'empty';
    setStatus(''); app.ready = true;
  }

  const start = $('viewer') ? initBrowse : initContract;
  start().catch(() => { setStatus(''); showAlert('This page could not finish loading. Reload it to try again.'); });
})();
