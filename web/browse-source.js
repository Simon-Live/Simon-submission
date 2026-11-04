// Where the home library's pages come from: the server's `api/catalog/search`, or, when this server has none yet
// (404 or 405), the whole catalog fetched once and searched in the browser with the same answer shape (model/browse-local.js).
import { searchCatalog, listEntries, ApiError } from "./api.js";
import { searchQuery } from "./model/browse.js";
import { searchLocal } from "./model/browse-local.js";
import { matches } from "./model/library.js";
import { arrange, isHidden } from "./curation.js";
import { judgeListed, loadOwned } from "./judge-catalog.js";

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

const NO_SEARCH = [404, 405, 501];

/**
 * @param labelsOf () => Promise<{entry_id: {tags}}>
 * @param profile {curatedOnly, showAll}: what the local fallback curates by (the server curates its own answer)
 */
export function createSource(labelsOf, { curatedOnly = false, showAll = false } = {}) {
  let mode = "server";
  let all = null;
  let owned = new Set();

  async function local(state, signedIn) {
    if (!all) {
      all = await listEntries();
      if (curatedOnly && signedIn) owned = await loadOwned().catch(() => new Set());
    }
    const labels = await labelsOf();
    // the same curation the library always had: test entries hidden unless searched by name, the judge list short
    const shown = visible(judgeListed(all, { submission: curatedOnly, owned }), labels, { query: state.q, curatedOnly, showAll });
    return searchLocal(shown, labels, state, owned);
  }

  return {
    get mode() { return mode; },
    /** One page for `state`. Throws the ApiError of a failed call. */
    async search(state, { signal, signedIn = false } = {}) {
      if (mode === "server") {
        try {
          const reply = await searchCatalog(`${searchQuery(state)}&profile=${curatedOnly ? "submission" : "default"}`, signal);
          if (reply && Array.isArray(reply.entries)) return reply;
          throw new ApiError(502, "The catalog answered in a form this page does not know.");
        } catch (err) {
          if (!(err instanceof ApiError) || !NO_SEARCH.includes(err.status)) throw err;
          mode = "local";
        }
      }
      return local(state, signedIn);
    },
  };
}
