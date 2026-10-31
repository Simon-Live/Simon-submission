// Home: the routine library. Controller only: it loads the catalog (Part 6 through the proxy) and the labels
// (their tags feed search and the card meta), builds the view model (model/library.js) for the chosen kind
// (model/kind.js) and hands it to the view (views/library.js). `#/`
import { listEntries } from "./api.js";
import { getLabels } from "./labels.js";
import { libraryOf, TEXT, matches } from "./model/library.js";
import { currentKind, onKindChange } from "./model/kind.js";
import { mountLibraryView } from "./views/library.js";

export { matches };

export function mountCatalog(root) {
  const state = { entries: [], labels: {}, query: "", loading: true, failed: null };
  const view = mountLibraryView(root, TEXT, (q) => { state.query = q; paint(); });

  function paint() {
    if (state.failed) {
      view.render({ sections: [], status: { kind: "load-error", text: `The catalog did not load: ${state.failed}` } });
      return;
    }
    view.render(libraryOf(state.entries, { kind: currentKind(), query: state.query, labels: state.labels, loading: state.loading }));
  }

  const stopKind = onKindChange(() => paint());
  paint();
  listEntries().then((all) => {
    state.entries = all;
    state.loading = false;
    paint();
    getLabels().then((labels) => { state.labels = labels; paint(); }).catch(() => {});
  }).catch((err) => { state.loading = false; state.failed = err.message; paint(); });

  return () => { stopKind(); view.destroy(); };
}
