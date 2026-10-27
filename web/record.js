// Record screen (AC-008): a mock camera view with a timer and Stop, then a name and type
// form that posts to the server. Nothing here touches a camera API or a file input.
import { el, createEntry, formatTime } from './api.js';

const LIMITS = { minStopMs: 1000, maxMs: 120000, minProcessingMs: 600, nameMax: 80 };
const TEXT = {
  noName: 'Enter a name.',
  longName: 'Use 80 characters or fewer.',
  noType: 'Choose Exercise or Dance.',
  saveFailed: 'Could not save. Try again.',
};

// Collapses whitespace and drops control characters, as the server's name rule does.
function cleanName(raw) {
  return raw.replace(/\s+/g, ' ').replace(/[\u0000-\u001f\u007f]/g, '').trim();
}

function problemWith(name, category) {
  const length = Array.from(name).length;
  if (length === 0) return TEXT.noName;
  if (length > LIMITS.nameMax) return TEXT.longName;
  return category ? null : TEXT.noType;
}

function pause(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function cameraView() {
  return el('div', { class: 'camera', 'data-testid': 'mock-camera' },
    el('span', { class: 'camera-tag' }, el('span', { class: 'rec-dot', 'aria-hidden': 'true' }), 'Mock camera'),
    el('span', { class: 'camera-figure', 'aria-hidden': 'true' }),
    el('span', { class: 'scan', 'aria-hidden': 'true' }));
}

function radioView(testid, value, text) {
  return el('label', { class: 'radio' },
    el('input', { type: 'radio', name: 'type', value, 'data-testid': testid }),
    el('span', {}, text));
}

function formView() {
  const ui = {
    name: el('input', { id: 'record-name', type: 'text', class: 'text-input', autocomplete: 'off', 'data-testid': 'name' }),
    exercise: radioView('type-exercise', 'exercise', 'Exercise'),
    dance: radioView('type-dance', 'dance', 'Dance'),
    error: el('p', { class: 'form-error', 'data-testid': 'form-error', role: 'alert', hidden: true }),
    processing: el('p', { class: 'processing', 'data-testid': 'processing', role: 'status', hidden: true },
      el('span', { class: 'spinner', 'aria-hidden': 'true' }), 'Processing'),
    save: el('button', { type: 'submit', class: 'btn btn-primary', 'data-testid': 'save' }, 'Save'),
    discard: el('button', { type: 'button', class: 'btn', 'data-testid': 'discard' }, 'Discard'),
  };
  ui.node = el('form', { class: 'form', novalidate: true },
    el('div', { class: 'field' }, el('label', { class: 'field-label', for: 'record-name' }, 'Name'), ui.name),
    el('fieldset', { class: 'field' },
      el('legend', { class: 'field-label' }, 'Type'),
      el('div', { class: 'radio-row' }, ui.exercise, ui.dance)),
    ui.error,
    ui.processing,
    el('div', { class: 'actions' }, ui.save, ui.discard));
  return ui;
}

function chosenCategory(form) {
  const checked = form.node.querySelector('input[name="type"]:checked');
  return checked ? checked.value : '';
}

function setBusy(form, busy) {
  form.node.querySelectorAll('input, button').forEach((control) => { control.disabled = busy; });
  form.processing.hidden = !busy;
  if (busy) form.error.hidden = true;
}

function showProblem(form, message) {
  form.error.textContent = message || '';
  form.error.hidden = !message;
}

export function mountRecord(root, route, nav) {
  const startedAt = performance.now();
  let destroyed = false;
  let durationMs = 0;
  let form = null;

  const timer = el('p', { class: 'timer', 'data-testid': 'timer' }, '0:00');
  const camera = cameraView();
  const stop = el('button', {
    type: 'button', class: 'btn btn-primary', 'data-testid': 'stop', disabled: true, onclick: () => finish(performance.now() - startedAt),
  }, 'Stop');
  const discard = el('button', { type: 'button', class: 'btn', 'data-testid': 'discard', onclick: () => nav.back() }, 'Discard');
  const panel = el('div', { class: 'record-panel' }, el('div', { class: 'actions' }, stop, discard));
  const screen = el('section', { class: 'screen record', 'data-testid': 'record' },
    el('h1', {}, 'Record'), camera, timer, panel);

  const ticker = setInterval(() => {
    const elapsed = performance.now() - startedAt;
    timer.textContent = formatTime(elapsed / 1000);
    if (elapsed >= LIMITS.minStopMs) stop.disabled = false;
    if (elapsed >= LIMITS.maxMs) finish(elapsed);
  }, 100);

  function revalidate() {
    if (!form.checked) return;
    const name = cleanName(form.name.value);
    showProblem(form, problemWith(name, chosenCategory(form)));
  }

  async function save() {
    const name = cleanName(form.name.value);
    const category = chosenCategory(form);
    form.checked = true;
    const problem = problemWith(name, category);
    showProblem(form, problem);
    if (problem) return;
    setBusy(form, true);
    const [result] = await Promise.all([
      createEntry({ name, category, duration_ms: durationMs }),
      pause(LIMITS.minProcessingMs),
    ]);
    if (destroyed) return;
    if (result.status === 'ok' && result.data && result.data.id) {
      nav.replace(`#/movement/${encodeURIComponent(result.data.id)}`);
      return;
    }
    setBusy(form, false);
    showProblem(form, TEXT.saveFailed);
  }

  function finish(elapsedMs) {
    if (form) return;
    clearInterval(ticker);
    durationMs = Math.min(LIMITS.maxMs, Math.max(LIMITS.minStopMs, Math.round(elapsedMs)));
    timer.textContent = formatTime(durationMs / 1000);
    camera.classList.add('is-stopped');
    form = formView();
    form.checked = false;
    form.node.addEventListener('submit', (event) => {
      event.preventDefault();
      save().catch(() => {
        if (destroyed) return;
        setBusy(form, false);
        showProblem(form, TEXT.saveFailed);
      });
    });
    form.node.addEventListener('input', revalidate);
    form.node.addEventListener('change', revalidate);
    form.discard.addEventListener('click', () => nav.back());
    panel.replaceChildren(form.node);
    form.name.focus({ preventScroll: true });
  }

  root.append(screen);
  return {
    destroy() {
      destroyed = true;
      clearInterval(ticker);
    },
  };
}
