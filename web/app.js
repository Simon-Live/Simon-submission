// Hash router: one screen at a time, mounted into #app and destroyed on leaving.
//   #/ or #/?category=dance&q=wave   catalog
//   #/movement/<id> or #/entry/<id>  detail
//   #/record                         record
//   #/import                         import
// Anything else shows the catalog.
import { mountCatalog } from './catalog.js';
import { mountDetail } from './detail.js';
import { mountImport } from './import.js';
import { mountRecord } from './record.js';

const CATEGORIES = ['exercise', 'dance'];
const DETAIL_PREFIXES = ['/movement/', '/entry/'];
const TITLES = { catalog: 'Movements', record: 'Record', import: 'Import' };

function parseRoute(hash) {
  const raw = hash.replace(/^#/, '');
  const cut = raw.indexOf('?');
  const path = cut < 0 ? raw : raw.slice(0, cut);
  if (path === '/record') return { name: 'record' };
  if (path === '/import') return { name: 'import' };
  const prefix = DETAIL_PREFIXES.find((candidate) => path.startsWith(candidate) && path.length > candidate.length);
  if (prefix) return { name: 'detail', id: decodeId(path.slice(prefix.length)) };
  const onCatalogPath = path === '/' || path === '';
  const params = new URLSearchParams(onCatalogPath && cut >= 0 ? raw.slice(cut + 1) : '');
  const category = params.get('category');
  return {
    name: 'catalog',
    q: params.get('q') || '',
    category: CATEGORIES.includes(category) ? category : '',
  };
}

function decodeId(text) {
  try {
    return decodeURIComponent(text);
  } catch (error) {
    return text;
  }
}

const MOUNTS = {
  catalog: mountCatalog, detail: mountDetail, record: mountRecord, import: mountImport,
};
const root = document.getElementById('app');
window.simonPlayer = null;
let current = null;
let position = 0;

// Each history entry carries its index so the Back buttons know whether the app has an
// earlier screen to return to.
function stampHistory() {
  const known = history.state && Number.isInteger(history.state.idx);
  position = known ? history.state.idx : position + (current ? 1 : 0);
  if (!known) history.replaceState({ idx: position }, '');
}

const nav = {
  go(hash) {
    location.hash = hash;
  },
  replace(hash) {
    history.replaceState(history.state, '', hash);
    render();
  },
  back() {
    if (position > 0) history.back();
    else nav.go('#/');
  },
};

function render() {
  const route = parseRoute(location.hash);
  const key = route.name === 'detail' ? `detail:${route.id}` : route.name;
  if (current && current.key === key && current.screen.update) {
    current.screen.update(route);
    return;
  }
  if (current) current.screen.destroy();
  window.simonPlayer = null;
  root.replaceChildren();
  window.scrollTo(0, 0);
  current = { key, screen: MOUNTS[route.name](root, route, nav) };
  document.title = TITLES[route.name] || 'Movements';
}

window.addEventListener('hashchange', () => {
  stampHistory();
  render();
});
stampHistory();
render();
