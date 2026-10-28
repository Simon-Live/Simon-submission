// Record screen (AC-008, AC-C10): a mock camera view with a timer and Stop, then a name and
// type form that posts to the server. A saved recording is either done at once (201) or a job
// whose stage this screen shows until it is done or failed (202). Nothing here touches a camera
// API or a file input.
import {
  el, createEntry, getJob, getEntry, formatTime, cleanName, nameProblem,
} from './api.js';

const LIMITS = { minStopMs: 1000, maxMs: 120000, minProcessingMs: 600, pollMs: 500, pollFailures: 10 };
const TEXT = {
  noType: 'Choose Exercise or Dance.',
  saveFailed: 'Could not save. Try again.',
  processing: 'Processing',
  queued: 'Waiting to start',
};
const FAILED_STATUS = /^failed:([^:]*):\s*([\s\S]*)$/;
const UNSTAGED = 'processing';

function problemWith(name, category) {
  return nameProblem(name) || (category ? null : TEXT.noType);
}

// What the processing panel says for a job status: queued, processing:<stage> or anything else.
function stageText(status) {
  if (status === 'queued') return TEXT.queued;
  if (typeof status === 'string' && status.startsWith('processing:')) {
    return `${TEXT.processing}: ${status.slice('processing:'.length)}`;
  }
  return TEXT.processing;
}

// "failed:pose: no person found" -> {stage: 'pose', reason: 'No person found.'}
function parseFailure(status) {
  const match = FAILED_STATUS.exec(status);
  const stage = (match && match[1].trim()) || UNSTAGED;
  const reason = match ? match[2].trim() : '';
  const sentence = reason ? `${reason[0].toUpperCase()}${reason.slice(1)}` : '';
  return { stage, reason: /[.!?]$/.test(sentence) ? sentence : sentence && `${sentence}.` };
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

function failureView(status, onRetry, onDiscard) {
  const { stage, reason } = parseFailure(status);
  return el('div', { class: 'failure', 'data-testid': 'processing-failed', role: 'alert' },
    el('p', { class: 'failure-head' }, `Processing failed at ${stage}.`),
    reason && el('p', { class: 'failure-reason' }, reason),
    el('div', { class: 'actions' },
      el('button', { type: 'button', class: 'btn btn-primary', 'data-testid': 'retry', onclick: onRetry }, 'Try again'),
      el('button', { type: 'button', class: 'btn', 'data-testid': 'discard', onclick: onDiscard }, 'Discard')));
}

function formView() {
  const label = el('span', {}, TEXT.processing);
  const ui = {
    label,
    name: el('input', { id: 'record-name', type: 'text', class: 'text-input', autocomplete: 'off', 'data-testid': 'name' }),
    exercise: radioView('type-exercise', 'exercise', 'Exercise'),
    dance: radioView('type-dance', 'dance', 'Dance'),
    error: el('p', { class: 'form-error', 'data-testid': 'form-error', role: 'alert', hidden: true }),
    processing: el('p', { class: 'processing', 'data-testid': 'processing', role: 'status', hidden: true },
      el('span', { class: 'spinner', 'aria-hidden': 'true' }), label),
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

// A job shows its stage in the processing panel; null goes back to the plain "Processing".
function showStage(form, status) {
  if (status === null) {
    form.label.removeAttribute('data-testid');
    form.label.textContent = TEXT.processing;
    return;
  }
  form.label.setAttribute('data-testid', 'processing-stage');
  form.label.textContent = stageText(status);
}

export function mountRecord(root, route, nav) {
  const startedAt = performance.now();
  let destroyed = false;
  let durationMs = 0;
  let form = null;
  let lastBody = null;

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

  function saveFailed() {
    if (destroyed) return;
    setBusy(form, false);
    showProblem(form, TEXT.saveFailed);
  }

  function openEntry(route, id) {
    nav.replace(`#/${route}/${encodeURIComponent(id)}`);
  }

  function retry() {
    panel.replaceChildren(form.node);
    submit(lastBody).catch(saveFailed);
  }

  function showFailure(status) {
    setBusy(form, false);
    panel.replaceChildren(failureView(status, retry, () => nav.back()));
  }

  // A job that is gone from the server's memory may still have stored its entry.
  async function resolveLost(id) {
    const found = await getEntry(id);
    if (destroyed) return;
    if (found.status === 'ok') openEntry('entry', id);
    else saveFailed();
  }

  // Follows a 202 job: shows each stage, polls every 500 ms, stops when the screen is left.
  async function watch(accepted) {
    let status = String(accepted.status || 'queued');
    let entryId = accepted.id;
    let failures = 0;
    while (!destroyed) {
      if (status === 'done') return openEntry('entry', entryId);
      if (status.startsWith('failed')) return showFailure(status);
      showStage(form, status);
      await pause(LIMITS.pollMs);
      if (destroyed) return undefined;
      const result = await getJob(accepted.id);
      if (destroyed) return undefined;
      if (result.status === 'missing') return resolveLost(accepted.id);
      if (result.status === 'ok' && result.data) {
        failures = 0;
        status = String(result.data.status || status);
        if (result.data.entry && result.data.entry.id) entryId = result.data.entry.id;
      } else {
        failures += 1;
        if (failures >= LIMITS.pollFailures) return saveFailed();
      }
    }
    return undefined;
  }

  async function submit(body) {
    lastBody = body;
    setBusy(form, true);
    showStage(form, null);
    const [result] = await Promise.all([createEntry(body), pause(LIMITS.minProcessingMs)]);
    if (destroyed) return;
    if (result.status !== 'ok' || !result.data || !result.data.id) {
      saveFailed();
    } else if (result.code === 201) {
      openEntry('movement', result.data.id);
    } else {
      await watch(result.data);
    }
  }

  async function save() {
    const name = cleanName(form.name.value);
    const category = chosenCategory(form);
    form.checked = true;
    const problem = problemWith(name, category);
    showProblem(form, problem);
    if (problem) return;
    await submit({ name, category, duration_ms: durationMs });
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
      save().catch(saveFailed);
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
