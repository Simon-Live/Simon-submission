// The home library's browse state, page numbers, view model and local search (web/model/browse.js, browse-local.js).
//   node --test tests/part7/browse.unit.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import {
  parseHash, toHash, searchQuery, change, pageItems, viewOf, countText, rangeText, chipsOf, withoutChip, cleared, allowed, clampPage,
  isBrowsing, filterCount, effectiveSort, DEFAULTS, BROWSE_TEXT,
} from "../../web/model/browse.js";
import { searchLocal, durationBand } from "../../web/model/browse-local.js";

test("the hash round trips and leaves defaults out", () => {
  const s = parseHash("#/?q=squat&type=dance,rehab&sort=title&duration=short&has=video,model&mine=1&page=3&per_page=24");
  assert.deepEqual(s, { q: "squat", type: ["dance", "rehab"], sort: "title", duration: "short", has: ["video", "model"], mine: true, page: 3, perPage: 24 });
  assert.equal(toHash(s), "#/?q=squat&type=dance%2Crehab&sort=title&duration=short&has=video%2Cmodel&mine=1&page=3&per_page=24");
  assert.equal(toHash(parseHash("#/")), "#/");
  assert.equal(toHash(parseHash("#/?page=1&per_page=12&sort=relevance")), "#/");
});

test("junk is ignored, not trusted", () => {
  const s = parseHash("#/?type=bogus,dance&sort=nope&duration=x&has=board,evil&page=-4&per_page=7&mine=2");
  assert.deepEqual(s, { ...DEFAULTS, type: ["dance"], has: ["board"] });
  assert.equal(parseHash("#/?page=abc").page, 1);
  assert.equal(parseHash(`#/?q=${"x".repeat(500)}`).q.length, 80);
  assert.equal(parseHash(undefined).page, 1);
});

test("the server query always names the page and the size, and the page after a filter change is 1", () => {
  assert.equal(searchQuery(DEFAULTS), "page=1&per_page=12");
  const at3 = { ...DEFAULTS, page: 3 };
  assert.equal(change(at3, { type: ["dance"] }).page, 1);
  assert.equal(change(at3, { sort: "title" }).page, 1);
  assert.equal(change(at3, { perPage: 24 }).page, 1);
  assert.equal(change(at3, { page: 4 }).page, 4);
  assert.equal(change(at3, { sort: "relevance" }).page, 3, "no real change keeps the page");
});

test("page numbers: all when few, gaps when many, the block grows at an edge, width stays the same", () => {
  assert.deepEqual(pageItems(1, 1), [1]);
  assert.deepEqual(pageItems(3, 7), [1, 2, 3, 4, 5, 6, 7]);
  assert.deepEqual(pageItems(1, 200), [1, 2, 3, 4, 5, "gap", 200]);
  assert.deepEqual(pageItems(100, 200), [1, "gap", 99, 100, 101, "gap", 200]);
  assert.deepEqual(pageItems(200, 200), [1, "gap", 196, 197, 198, 199, 200]);
  assert.deepEqual(pageItems(100, 200, 0), [1, "gap", 100, "gap", 200]);
  for (const p of [1, 2, 4, 5, 6, 50, 195, 196, 199, 200]) assert.equal(pageItems(p, 200).length, 7, `page ${p}`);
  assert.ok(pageItems(100, 200).includes(100));
});

test("a page past the end corrects itself", () => {
  assert.equal(clampPage(99, 4), 4);
  assert.equal(clampPage(0, 4), 1);
  assert.equal(clampPage(3, 0), 1, "an empty result has page 1");
});

test("count and range lines", () => {
  assert.equal(countText(42), "42 movements");
  assert.equal(countText(1), "1 movement");
  assert.equal(countText(0), "No movements");
  assert.equal(rangeText(42, 2, 12), "Showing 13 to 24");
  assert.equal(rangeText(42, 4, 12), "Showing 37 to 42");
  assert.equal(rangeText(0, 1, 12), "");
});

test("chips say what is applied and removing one changes only it", () => {
  const s = { ...DEFAULTS, q: "squat", type: ["dance", "rehab"], duration: "long", has: ["video"], mine: true, page: 2 };
  assert.deepEqual(chipsOf(s).map((c) => c.label), ["Search: squat", "Dance", "Rehab", "Length: Over 45 s", "A trainer video", "Only mine"]);
  assert.deepEqual(withoutChip(s, { key: "type", value: "dance" }).type, ["rehab"]);
  assert.equal(withoutChip(s, { key: "type", value: "dance" }).page, 1);
  assert.equal(withoutChip(s, { key: "q" }).q, "");
  assert.equal(withoutChip(s, { key: "mine" }).mine, false);
  assert.deepEqual(chipsOf(cleared({ ...s, sort: "title", perPage: 24 })), []);
  assert.equal(cleared({ ...s, sort: "title" }).sort, "title", "Clear all keeps the sort");
  assert.equal(filterCount(s), 5);
  assert.equal(isBrowsing(DEFAULTS), false);
  assert.equal(isBrowsing({ ...DEFAULTS, page: 2 }), true);
});

test("Rehab is dropped from the state and the choices when policy hides it", () => {
  assert.deepEqual(allowed({ ...DEFAULTS, type: ["rehab", "dance"] }, { rehab: false }).type, ["dance"]);
  const reply = { entries: [], total: 0, pages: 0, facets: { type: { exercise: 1, dance: 2, rehab: 3 } } };
  assert.deepEqual(viewOf(DEFAULTS, reply, { rehab: false }).groups.find((g) => g.key === "type").options.map((o) => o.value), ["exercise", "dance"]);
  const offered = viewOf(DEFAULTS, { ...reply, types_offered: ["exercise", "dance"] }).groups.find((g) => g.key === "type");
  assert.deepEqual(offered.options.map((o) => o.value), ["exercise", "dance"], "the server's own list wins");
});

test("a filter or sort the reply cannot count is not offered; popular says what it counts", () => {
  const reply = { entries: [], total: 0, pages: 0, facets: { type: { dance: 4 }, has: { video: 2 } } };
  const v = viewOf(DEFAULTS, reply);
  assert.deepEqual(v.groups.map((g) => g.key), ["type", "has"], "no duration group, no signed-out Only mine");
  assert.deepEqual(v.groups.find((g) => g.key === "has").options.map((o) => o.value), ["video"], "no leaderboard filter without a count");
  assert.ok(v.sorts.some((s) => s.label === "Most followed this week"));
  assert.ok(!v.sorts.some((s) => s.value === "relevance"), "best match only with a search");
  assert.equal(v.sort, "newest");
  const q = viewOf({ ...DEFAULTS, q: "a" }, reply);
  assert.equal(q.sort, "relevance");
  assert.equal(q.sorts[0].label, "Best match");
  assert.equal(effectiveSort({ ...DEFAULTS, sort: "title" }), "title");
  const local = viewOf(DEFAULTS, { ...reply, sorts: ["relevance", "title"] });
  assert.ok(!local.sorts.some((s) => s.value === "popular"), "a source that lists its sorts is believed");
  assert.equal(viewOf(DEFAULTS, reply, { signedIn: true }).groups.at(-1).key, "mine");
});

test("copy has no em or en dash", () => {
  const all = JSON.stringify(Object.values(BROWSE_TEXT).map((v) => (typeof v === "function" ? v("x", true) : v)));
  assert.doesNotMatch(all, /[\u2013\u2014]/);
});

const E = (id, name, extra = {}) => ({ id, name, category: "exercise", duration_ms: 20000, ...extra });
const LIB = [E("a", "Squat", { video_uri: "v.mp4", duration_ms: 10000 }), E("b", "Dance one", { category: "dance", duration_ms: 60000 }), E("c", "Knee bend", { animation: "x.json" })];
const LABELS = { c: { tags: ["rehab"] } };

test("local search follows the server's contract: filters, facets, sort, pages", () => {
  const all = searchLocal(LIB, LABELS, DEFAULTS);
  assert.equal(all.total, 3);
  assert.deepEqual(all.facets.type, { exercise: 2, dance: 1, rehab: 1 });
  assert.deepEqual(all.facets.duration, { short: 1, medium: 1, long: 1 });
  assert.deepEqual(searchLocal(LIB, LABELS, { ...DEFAULTS, type: ["rehab"] }).entries.map((e) => e.id), ["c"]);
  assert.deepEqual(searchLocal(LIB, LABELS, { ...DEFAULTS, has: ["video"] }).entries.map((e) => e.id), ["a"]);
  assert.deepEqual(searchLocal(LIB, LABELS, { ...DEFAULTS, duration: "long" }).entries.map((e) => e.id), ["b"]);
  assert.deepEqual(searchLocal(LIB, LABELS, { ...DEFAULTS, q: "bend" }).entries.map((e) => e.id), ["c"]);
  assert.deepEqual(searchLocal(LIB, LABELS, { ...DEFAULTS, sort: "title" }).entries.map((e) => e.id), ["b", "c", "a"]);
  assert.deepEqual(searchLocal(LIB, LABELS, { ...DEFAULTS, sort: "duration" }).entries.map((e) => e.id), ["a", "c", "b"]);
  assert.equal(searchLocal(LIB, LABELS, { ...DEFAULTS, mine: true }).total, 0, "mine with nothing owned");
  assert.equal(searchLocal(LIB, LABELS, { ...DEFAULTS, mine: true }, new Set(["a"])).total, 1);
  assert.deepEqual(all.sorts.includes("popular"), false);
  assert.equal("board" in all.facets.has, false);
  const many = Array.from({ length: 30 }, (_, i) => E(`m${i}`, `Move ${i}`));
  const page3 = searchLocal(many, {}, { ...DEFAULTS, page: 9 });
  assert.equal(page3.page, 3);
  assert.equal(page3.pages, 3);
  assert.equal(page3.entries.length, 6);
  assert.equal(durationBand(15000), "medium");
  assert.equal(durationBand(45000), "medium");
  assert.equal(durationBand(45001), "long");
  assert.equal(durationBand(14999), "short");
  assert.equal(durationBand(0), "");
});
