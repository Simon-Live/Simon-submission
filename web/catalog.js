// Home: the routine library, browsed by search, filters, sort and pages (docs/specs/home-browse.md). Controller only: it
// keeps the browse state in the URL hash (model/browse.js), asks the source for a page (browse-source.js), builds the view
// model and hands it to the view (views/browse.js). `#/` and `#/?q=&type=&sort=&page=`
import { getLabels } from "./labels.js";
import { TEXT, matches, cardOf } from "./model/library.js";
import { mountBrowseView } from "./views/browse.js";
import { isDebug, isSubmission, showRehab } from "./flags.js";
import { mountHero } from "./hero.js";
import { isProd } from "./policy.js";
import { mountHomeBoards } from "./boards-list.js";
import { fetchMe } from "./auth.js";
import { createSource, visible } from "./browse-source.js";
import {
  BROWSE_TEXT, DEFAULTS, effectiveSort, parseHash, toHash, change, withoutChip, cleared, allowed, isBrowsing, pageItems, viewOf, clampPage,
} from "./model/browse.js";

export { matches, visible };
// TICKET-131: the pitch line stays under the title
export const PITCH = "Record a movement once. Simon turns it into a 3D reference that your students are checked against.";
export const EMPTY = [TEXT.empty];
export const DEBOUNCE_MS = 250;
const NARROW_PAGER = "(max-width: 479px)"; // fewer page numbers fit a phone

export function mountCatalog(root) {
  const curatedOnly = isSubmission();
  const rehab = showRehab();
  const labelsP = getLabels().catch(() => ({}));
  const source = createSource(() => labelsP, { curatedOnly, showAll: isDebug() });
  let state = allowed(parseHash(location.hash), { rehab });
  const ctx = { labels: {}, reply: null, loading: true, failed: "", signedIn: false, token: 0, abort: null, timer: 0, focusAfter: false, live: true };
  const narrowPager = globalThis.matchMedia ? globalThis.matchMedia(NARROW_PAGER) : { matches: false };

  const view = mountBrowseView(root, { ...BROWSE_TEXT, pitch: PITCH }, {
    query: (value, commit) => {
      clearTimeout(ctx.timer);
      const next = change(state, { q: value });
      const fire = () => go(next, { push: !state.q.trim() && Boolean(value.trim()) });
      if (commit) go(next, { push: true }); else ctx.timer = setTimeout(fire, DEBOUNCE_MS);
    },
    group: (key, value, on) => {
      if (key === "duration") return go(change(state, { duration: value }), { push: true });
      if (key === "mine") return go(change(state, { mine: on }), { push: true });
      const set = new Set(state[key]);
      if (on) set.add(value); else set.delete(value);
      return go(change(state, { [key]: [...set] }), { push: true });
    },
    sort: (value) => go(change(state, { sort: value === effectiveSort({ ...state, sort: DEFAULTS.sort }) ? DEFAULTS.sort : value }), { push: true }), // the default is left out of the address
    perPage: (n) => go(change(state, { perPage: n }), { push: true, focus: true }),
    page: (item) => go({ ...state, page: item.n }, { push: true, focus: true }),
    chip: (chip) => go(withoutChip(state, chip), { push: true }),
    clearAll: () => go(cleared(state), { push: true }),
    retry: () => load(),
  });

  /** Apply a new state: write the address (no reload, no hashchange), then ask for its page. */
  function go(next, { push = false, focus = false } = {}) {
    if (!ctx.live) return;
    if (toHash(next) !== toHash(state)) {
      history[push ? "pushState" : "replaceState"](history.state, "", toHash(next));
      state = next;
      ctx.focusAfter = focus;
      load();
    }
  }

  async function load(retried = false) {
    const token = ++ctx.token;
    ctx.abort?.abort();
    ctx.abort = typeof AbortController === "function" ? new AbortController() : null;
    ctx.loading = true; ctx.failed = "";
    paint();
    try {
      const reply = await source.search(state, { signal: ctx.abort?.signal, signedIn: ctx.signedIn });
      ctx.labels = await labelsP; // the tags feed the card meta
      if (token !== ctx.token || !ctx.live) return;
      const fixed = clampPage(state.page, reply.pages);
      if (!retried && fixed !== state.page) { // a page past the end corrects itself to the last page
        state = { ...state, page: fixed };
        history.replaceState(history.state, "", toHash(state));
        return load(true);
      }
      ctx.reply = reply;
      ctx.loading = false;
    } catch (err) {
      if (token !== ctx.token || !ctx.live || (err && err.name === "AbortError")) return;
      if (err && err.status === 401 && state.mine) { // signed out: "only mine" has nothing to show
        state = { ...state, mine: false }; window.history.replaceState(window.history.state, "", toHash(state)); return load(retried);
      }
      ctx.loading = false; ctx.reply = null; ctx.failed = (err && err.message) || "Try again in a moment.";
    }
    paint();
    if (ctx.focusAfter) { ctx.focusAfter = false; view.focusResults(); }
  }

  function paint() {
    const model = viewOf(state, ctx.reply, { rehab, signedIn: ctx.signedIn, loading: ctx.loading, failed: ctx.failed });
    const labels = ctx.labels;
    const href = (n) => toHash({ ...state, page: n });
    const empty = ctx.reply && !ctx.reply.total;
    view.render({
      ...model, browsing: isBrowsing(state), labels,
      cards: ctx.failed ? [] : model.entries.map((e) => cardOf(e, labels)),
      status: statusOf(model, empty),
      pageNav: ctx.reply && !ctx.failed && ctx.reply.total > 0 ? {
        pages: model.pages,
        prev: state.page > 1 ? { n: state.page - 1, href: href(state.page - 1) } : null,
        next: state.page < model.pages ? { n: state.page + 1, href: href(state.page + 1) } : null,
        items: pageItems(state.page, model.pages, narrowPager.matches ? 0 : 1).map((n) => (n === "gap" ? n : { n, href: href(n), current: n === state.page })),
      } : null,
    });
  }

  function statusOf(model, empty) {
    if (ctx.failed) return { kind: "load-error", text: BROWSE_TEXT.failed(ctx.failed), action: { label: BROWSE_TEXT.retry, testid: "retry", run: "retry" } };
    if (!empty || ctx.loading) return null;
    if (!isBrowsing(state) && !model.filters) return { kind: "empty", text: BROWSE_TEXT.empty, record: true };
    return { kind: "no-match", text: BROWSE_TEXT.noMatch(state.q.trim(), model.filters > 0), action: { label: BROWSE_TEXT.clearFilters, testid: "clear-filters", run: "clearAll" } };
  }

  const boardsBox = document.createElement("div"); // finding leaderboards: open boards above the search
  boardsBox.className = "bw-boards";
  root.querySelector(".bw-search")?.before(boardsBox);
  const stopBoards = mountHomeBoards(boardsBox);
  // the judge view and prod link one finished take when the operator named one (judge-view.md, prod-seed.md)
  const stopHero = curatedOnly || isProd() ? mountHero(root, { moreLinks: curatedOnly }) : () => {};
  // who is signed in decides whether "Only my movements" is offered; a shared link asking for it waits for the answer
  const who = fetchMe().then((info) => { ctx.signedIn = Boolean(info.signedIn); }).catch(() => {});
  const start = () => { if (ctx.signedIn === false && state.mine) state = { ...state, mine: false }; load(); };
  if (state.mine) who.then(() => { if (ctx.live) start(); }); else { load(); who.then(() => { if (ctx.live && ctx.signedIn) paint(); }); }

  chainDestroy(view, stopHero); // the judge hero goes with the view, so the teardown line below stays as the client wrote it
  return () => { ctx.live = false; clearTimeout(ctx.timer); ctx.abort?.abort(); stopBoards(); view.destroy(); };
}

/** Run `before` (our extra cleanup) ahead of the view's own `destroy`, once per call. Returns the view. */
export function chainDestroy(view, before) {
  const own = view.destroy;
  view.destroy = () => { before(); own.call(view); };
  return view;
}
