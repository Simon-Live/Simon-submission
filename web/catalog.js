// Home: the routine library. Controller only: it loads the catalog (Part 6 through the proxy) and the labels
// (their tags feed search and the card meta), applies the curation (curation.js: test entries hidden, curated order,
// the submission profile's short list), builds the view model (model/library.js) for the chosen kind
// (model/kind.js) and hands it to the view (views/library.js). `#/`
import { listEntries } from "./api.js";
import { getLabels } from "./labels.js";
import { libraryOf, TEXT, matches } from "./model/library.js";
import { currentKind, onKindChange } from "./model/kind.js";
import { mountLibraryView } from "./views/library.js";
import { arrange, isHidden } from "./curation.js";
import { isDebug, isSubmission, showModes } from "./flags.js";

export { matches };
// TICKET-131: the pitch line stays under the library lede
export const PITCH = "Record a movement once. Simon turns it into a 3D reference that your students are checked against.";
export const EMPTY = [TEXT.empty];
const LIBRARY_TEXT = { ...TEXT, pitch: PITCH };

/**
 * What the library lists. Without a search: the arranged list (hidden entries out, curated ones first). With a
 * search: the hidden test entries whose name matches come back, so a verify run can still find its own entry by
 * name; the submission profile keeps to the curated list.
 */
export function visible(entries, labels, { query = "", curatedOnly = false, showAll = false } = {}) {
  const base = arrange(entries, labels, { curatedOnly, showAll });
  const extra = query.trim() && !curatedOnly && !showAll
    ? entries.filter((e) => isHidden(e, labels) && !base.includes(e)) : [];
  return [...base, ...extra].filter((e) => matches(e, query, labels));
}

export function mountCatalog(root) {
  const state = { entries: [], labels: {}, query: "", loading: true, failed: null };
  const curatedOnly = isSubmission();
  const showAll = isDebug();
  const view = mountLibraryView(root, LIBRARY_TEXT, (q) => { state.query = q; paint(); });

  function paint() {
    if (state.failed) {
      view.render({ sections: [], status: { kind: "load-error", text: `The catalog did not load: ${state.failed}` } });
      return;
    }
    const entries = visible(state.entries, state.labels, { query: state.query, curatedOnly, showAll });
    if (!entries.length && state.query.trim() && !state.loading) {
      view.render({ sections: [], status: { kind: "no-match", text: TEXT.noMatch(state.query.trim()) } });
      return;
    }
    view.render(libraryOf(entries, { kind: currentKind(), query: state.query, labels: state.labels, loading: state.loading, showRehab: showModes() }));
  }

  const stopKind = onKindChange(() => paint());
  paint();
  listEntries().then((all) => {
    state.entries = all;
    // Labels first: a verify entry is recognised by its tag too, and a first paint that shows it would flash.
    return getLabels().catch(() => ({})).then((labels) => { state.labels = labels; state.loading = false; paint(); });
  }).catch((err) => { state.loading = false; state.failed = err.message; paint(); });

  return () => { stopKind(); view.destroy(); };
}
