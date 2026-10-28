// Catalog screen: type chips, live search and movement cards (AC-004). The chip and the
// search text live in the hash, so browser Back restores them.
import {
  el, listEntries, thumbnailUrl, formatDuration, categoryLabel, sourceLabel, CATALOG_LOAD_FAILED,
} from './api.js';

const CHIPS = [
  ['chip-all', 'All', ''],
  ['chip-exercise', 'Exercises', 'exercise'],
  ['chip-dance', 'Dances', 'dance'],
];
const CATEGORY_NAMES = { exercise: 'Exercises', dance: 'Dances' };
const TEXT = {
  noEntries: 'No movements yet. Record one to add it here.',
};
const PLACEHOLDER_CARDS = 3;

function catalogHash({ q, category }) {
  const params = new URLSearchParams();
  if (category) params.set('category', category);
  if (q) params.set('q', q);
  const query = params.toString();
  return `#/${query ? `?${query}` : ''}`;
}

function emptyMessage(state) {
  const query = state.q.trim();
  const quoted = query ? ` "${query}"` : '';
  const scope = state.category ? ` in ${CATEGORY_NAMES[state.category]}` : '';
  return `No movements match${quoted}${scope}.`;
}

function imagesLoaded(container) {
  const pending = [...container.querySelectorAll('img')].filter((image) => !image.complete);
  return Promise.all(pending.map((image) => new Promise((resolve) => {
    image.addEventListener('load', resolve, { once: true });
    image.addEventListener('error', resolve, { once: true });
  })));
}

function signature(entry) {
  return [entry.name, entry.category, entry.duration_ms, entry.files_source, entry.thumbnail].join('|');
}

function buildCard(entry) {
  const label = sourceLabel(entry.files_source);
  const card = el('a', {
    class: 'card', href: `#/movement/${encodeURIComponent(entry.id)}`, 'data-testid': 'card', 'data-id': entry.id,
  },
  el('span', { class: 'thumb' }, el('img', { src: thumbnailUrl(entry), alt: '', width: 88, height: 88 })),
  el('span', { class: 'card-body' },
    el('span', { class: 'card-name', 'data-testid': 'card-name' }, entry.name),
    el('span', { class: 'card-meta' },
      el('span', { 'data-testid': 'card-category' }, categoryLabel(entry.category)),
      el('span', { class: 'dot', 'aria-hidden': 'true' }, '·'),
      el('span', { 'data-testid': 'card-duration' }, formatDuration(entry.duration_ms / 1000))),
    label && el('span', { class: 'badge', 'data-testid': 'card-label' }, label)));
  card.dataset.signature = signature(entry);
  return card;
}

function placeholders() {
  return Array.from({ length: PLACEHOLDER_CARDS }, () => el('div', { class: 'card card-placeholder', 'aria-hidden': 'true' },
    el('span', { class: 'thumb' }),
    el('span', { class: 'card-body' }, el('span', { class: 'skeleton-line wide' }), el('span', { class: 'skeleton-line' }))));
}

export function mountCatalog(root, route, nav) {
  let state = { q: route.q, category: route.category };
  let sequence = 0;
  let destroyed = false;
  const cards = new Map();

  const search = el('input', {
    id: 'search', type: 'search', class: 'search', placeholder: 'Search movements', autocomplete: 'off',
    enterkeyhint: 'search', 'data-testid': 'search', value: state.q,
  });
  const chips = CHIPS.map(([testid, text, category]) => ({
    category,
    node: el('button', { type: 'button', class: 'chip', 'data-testid': testid, 'aria-pressed': 'false' }, text),
  }));
  const results = el('div', { class: 'results' }, placeholders());
  const screen = el('section', { class: 'screen catalog', 'data-testid': 'catalog', 'data-ready': '0' },
    el('header', { class: 'catalog-head' },
      el('h1', {}, 'Movements'),
      el('div', { class: 'head-actions' },
        el('button', {
          type: 'button', class: 'btn import-open', 'data-testid': 'open-import', onclick: () => nav.go('#/import'),
        }, 'Import'),
        el('button', {
          type: 'button', class: 'btn btn-primary record-open', 'data-testid': 'record-open', onclick: () => nav.go('#/record'),
        }, 'Record'))),
    el('div', { class: 'search-wrap' },
      el('label', { class: 'sr-only', for: 'search' }, 'Search movements'),
      search),
    el('div', { class: 'chips', role: 'group', 'aria-label': 'Type' }, chips.map((chip) => chip.node)),
    results);

  function syncControls() {
    if (search.value !== state.q) search.value = state.q;
    chips.forEach((chip) => chip.node.setAttribute('aria-pressed', String(chip.category === state.category)));
  }

  function cardFor(entry) {
    const known = cards.get(entry.id);
    if (known && known.dataset.signature === signature(entry)) return known;
    const fresh = buildCard(entry);
    cards.set(entry.id, fresh);
    return fresh;
  }

  function errorView() {
    return el('div', { class: 'notice', 'data-testid': 'catalog-error', role: 'alert' },
      el('p', {}, CATALOG_LOAD_FAILED),
      el('button', { type: 'button', class: 'btn btn-primary', 'data-testid': 'retry', onclick: () => load() }, 'Try again'));
  }

  function emptyView() {
    const filtered = state.q.trim() || state.category;
    const action = filtered
      ? el('button', { type: 'button', class: 'btn', 'data-testid': 'clear', onclick: () => clear() }, 'Clear')
      : el('button', { type: 'button', class: 'btn btn-primary', 'data-testid': 'empty-record', onclick: () => nav.go('#/record') }, 'Record');
    return el('div', { class: 'notice', 'data-testid': 'empty', role: 'status' },
      el('p', {}, filtered ? emptyMessage(state) : TEXT.noEntries),
      action);
  }

  function listView(result) {
    if (result.status !== 'ok') return [errorView()];
    if (result.entries.length === 0) return [emptyView()];
    return result.entries.map(cardFor);
  }

  async function render(mine) {
    const result = await listEntries(state.q, state.category);
    if (destroyed || mine !== sequence) return;
    results.replaceChildren(...listView(result));
    await imagesLoaded(results);
  }

  function load() {
    sequence += 1;
    const mine = sequence;
    screen.dataset.ready = '0';
    return render(mine)
      .catch(() => {
        if (!destroyed && mine === sequence) results.replaceChildren(errorView());
      })
      .then(() => {
        if (!destroyed && mine === sequence) screen.dataset.ready = '1';
      });
  }

  function change(next) {
    state = next;
    history.replaceState(history.state, '', catalogHash(state));
    syncControls();
    load();
  }

  function clear() {
    change({ q: '', category: '' });
  }

  chips.forEach((chip) => chip.node.addEventListener('click', () => {
    if (chip.category !== state.category) change({ ...state, category: chip.category });
  }));
  search.addEventListener('input', () => change({ ...state, q: search.value }));

  root.append(screen);
  syncControls();
  load();

  return {
    update(next) {
      state = { q: next.q, category: next.category };
      syncControls();
      load();
    },
    destroy() {
      destroyed = true;
      sequence += 1;
    },
  };
}
