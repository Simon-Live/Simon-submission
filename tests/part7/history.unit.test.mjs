// "Your takes over time" (docs/specs/history-web.md AC-1..AC-9): model, view and glue against a fake fetch.
//   node --test tests/part7/history.unit.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { El, installDom, find } from "./fake-dom.mjs";

installDom();
document.createElementNS = (_ns, tag) => new El(tag);
Object.defineProperty(El.prototype, "classList", { get() { return { add: (c) => { this.className = `${this.className} ${c}`.trim(); } }; } });
Object.defineProperty(El.prototype, "hidden", { get() { return "hidden" in this.attrs; }, set(v) { if (v) this.attrs.hidden = ""; else delete this.attrs.hidden; } });
const M = await import("../../web/model/history.js");
const V = await import("../../web/views/history.js");
const G = await import("../../web/history.js");

const fx = (f) => JSON.parse(fs.readFileSync(new URL(`./fixtures/history/${f}`, import.meta.url), "utf8"));
const PAGE = fx("page-body-squat.fixture.json");
const REPORT = fx("report-body-squat.fixture.json");
const ENTRY = "body-squat-19b06562";
const nativeTimeout = globalThis.setTimeout;
const settle = async () => { for (let i = 0; i < 6; i++) await new Promise((r) => nativeTimeout(r, 4)); };

// ---------- model (AC-1) ----------
test("AC-1 each run status maps to a state", () => {
  assert.equal(M.stateForStatus(200).kind, "done");
  assert.equal(M.stateForStatus(202).kind, "waiting");
  assert.equal(M.stateForStatus(401).kind, "signedout");
  assert.equal(M.stateForStatus(404).kind, "missing");
  assert.equal(M.stateForStatus(409).kind, "consent");
  assert.equal(M.stateForStatus(422).kind, "few");
  assert.equal(M.stateForStatus(500).kind, "error");
  assert.equal(M.stateForStatus(0).kind, "error");
  for (const s of [202, 409, 422, 500]) assert.ok(M.stateForStatus(s).message.length > 10);
});

test("AC-1 Retry-After sets the poll delay, with a floor, a ceiling and a default", () => {
  assert.equal(M.retryDelayMs("5"), 5000);
  assert.equal(M.retryDelayMs("0.2"), M.POLL_MIN_MS);
  assert.equal(M.retryDelayMs("900"), M.POLL_MAX_MS);
  for (const bad of [null, undefined, "", "soon", "-3", "0"]) assert.equal(M.retryDelayMs(bad), M.POLL_DEFAULT_MS);
  assert.equal(M.keepPolling(1000), true);
  assert.equal(M.keepPolling(M.POLL_LIMIT_MS), false);
});

test("AC-1 the context meter formats used, cached and clips from report.usage", () => {
  const m = M.contextMeter(REPORT.usage, 9);
  assert.equal(m.used, 41872);
  assert.equal(m.usedText, "41,872 of 1,048,576 tokens used (4.0%)");
  assert.equal(m.cachedText, "30,208 cached tokens");
  assert.equal(m.clipsText, "Watched 2 of your 9 takes and read the measurements of all 9");
  assert.equal(M.contextMeter(REPORT.usage).clipsText, "Watched 2 clips");
  assert.ok(m.widthPct > 3.9 && m.widthPct < 4.1);
});

test("AC-1 the context meter handles zero, one, a tiny share, an overflow and a missing count", () => {
  assert.equal(M.contextMeter({ input_tokens: 0 }).pct, "0%");
  assert.equal(M.contextMeter({ input_tokens: 500, cached_tokens: 1, clips_sent: 1 }).pct, "less than 0.1%");
  assert.equal(M.contextMeter({ input_tokens: 500, cached_tokens: 1, clips_sent: 1 }).cachedText, "1 cached token");
  assert.equal(M.contextMeter({ input_tokens: 500, clips_sent: 1 }).clipsText, "Watched 1 clip");
  assert.equal(M.contextMeter({ input_tokens: 5e6 }).widthPct, 100);
  for (const none of [null, undefined, {}, { input_tokens: "x" }]) assert.equal(M.contextMeter(none), null);
});

test("cite chips read 'Take 3 · 2.1 s' and the measure label names the side", () => {
  assert.equal(M.citeText({ take: 3, at_s: 2.1 }), "Take 3 · 2.1 s");
  assert.equal(M.citeText({ take: 3 }), "Take 3");
  assert.equal(M.measureLabel("trunk_lean_forward", "center"), "Trunk lean forward");
  assert.equal(M.measureLabel("knee_valgus", "left"), "Knee valgus, left");
});

test("the page view: chart points per take, take rows with clip URLs, chips from the fact table", () => {
  const vm = M.pageView(PAGE, ENTRY, REPORT);
  assert.deepEqual(vm.chart.points.map((p) => p.take), [1, 2]);
  assert.ok(vm.chart.points[0].y < vm.chart.points[1].y, "100 sits above 77");
  assert.equal(vm.takes[0].clip, `api/me/history/${ENTRY}/takes/cc7cd5469055/clip.mp4`);
  assert.equal(vm.canRun, true);
  assert.deepEqual(vm.chips.map((c) => [c.kind, c.label]), [["new", "Trunk lean forward"]]);
  assert.equal(vm.trends[0].cites[0].text, "Take 2 · 0.9 s");
  assert.equal(vm.focus.cue, "Keep your chest up");
  assert.equal(vm.observations[0].cite.text, "Take 2 · 3.2 s");
  assert.equal(vm.meter.used, 41872);
});

test("fixed and persistent measures become their own chips", () => {
  const facts = { takes: [{}, {}, {}], measures: [
    { measure: "knee_valgus", side: "left", present_in: 3, status: "persistent" },
    { measure: "heel_rise", side: "right", present_in: 1, status: "fixed" },
  ] };
  const chips = M.factChips(facts);
  assert.deepEqual(chips.map((c) => c.kindText), ["Still there", "Fixed"]);
  assert.equal(chips[0].detail, "in 3 of 3");
});

test("a clip that is not kept gives a cite without a clip URL; fewer than 2 takes cannot run", () => {
  const doc = structuredClone(PAGE);
  doc.takes[1].clip = false;
  assert.equal(M.pageView(doc, ENTRY, REPORT).trends[0].cites[0].clip, "");
  assert.equal(M.pageView({ takes: [PAGE.takes[0]] }, ENTRY, null).canRun, false);
  assert.equal(M.pageView(null, ENTRY, null).takeCount, 0);
});

test("AC-2 a fallback report keeps the fact table and its reason, and no model cards", () => {
  const rep = { status: "fallback", reason: "over_budget", facts: PAGE.facts, usage: null };
  const vm = M.pageView(PAGE, ENTRY, rep);
  assert.equal(vm.fallback, true);
  assert.equal(vm.ok, false);
  assert.equal(vm.reason, "Over budget.");
  assert.equal(vm.facts.measures[0].presence, "1 of 2 takes");
  assert.deepEqual([vm.facts.best, vm.facts.latest], ["Take 1", "Take 2"]);
  assert.equal(vm.trends.length, 0);
  assert.equal(vm.meter, null);
  assert.equal(M.reasonText(""), "The model was not used for this report.");
  assert.equal(M.reasonText("The call was refused."), "The call was refused.");
});

// ---------- view (AC-2, AC-3, AC-5) ----------
function page(report, hooks = {}) {
  const el = new El("section");
  const ui = V.renderHistoryPage(el, M.pageView(PAGE, ENTRY, report), { onRun() {}, onConsent() {}, ...hooks });
  return { el, ui };
}

test("the page carries every C-WEB test id for a full report", () => {
  const { el } = page(REPORT);
  for (const id of ["history-page", "history-chart", "history-take-1", "history-take-2", "history-trend-0", "history-cite-0-0", "history-cite-0-1",
    "history-focus", "history-observation-0", "history-consent", "history-run", "history-status", "history-context", "history-chip-0"]) {
    assert.ok(el.getAttribute("data-testid") === id || find(el, id), `missing ${id}`);
  }
  assert.equal(find(el, "history-fallback"), null);
  assert.match(find(el, "history-observation-0").textContent, /model's opinion, not scored/);
  assert.match(find(el, "history-focus-cue").textContent, /Keep your chest up/);
  assert.match(find(el, "history-context-used").textContent, /41,872 of 1,048,576 tokens used/);
  assert.match(find(el, "history-context-cached").textContent, /30,208 cached tokens/);
  assert.match(find(el, "history-context-clips").textContent, /Watched 2 of your 2 takes and read the measurements of all 2/);
});

test("tapping a cite chip opens that take's clip at that second", () => {
  const { el, ui } = page(REPORT);
  const chip = find(el, "history-cite-0-0");
  assert.equal(chip.textContent, "Take 2 · 0.9 s");
  chip.click();
  const video = ui.player.video;
  assert.equal(video.getAttribute("src"), `api/me/history/${ENTRY}/takes/5277380db1e1/clip.mp4`);
  video.dispatchEvent(new Event("loadedmetadata"));
  assert.equal(video.currentTime, 0.9);
  assert.equal(find(el, "history-player").hidden, false);
  find(el, "history-cite-0-1").click();
  assert.match(video.getAttribute("src"), /cc7cd5469055/);
});

test("a cite whose clip is not kept is disabled", () => {
  const doc = structuredClone(PAGE);
  doc.takes[1].clip = false;
  const el = new El("section");
  V.renderHistoryPage(el, M.pageView(doc, ENTRY, REPORT), { onRun() {}, onConsent() {} });
  assert.ok("disabled" in find(el, "history-cite-0-0").attrs);
});

test("AC-2 a fallback report renders history-fallback with its reason and the facts", () => {
  const { el } = page({ status: "fallback", reason: "the call was refused", facts: PAGE.facts });
  const fb = find(el, "history-fallback");
  assert.ok(fb);
  assert.match(fb.textContent, /Measured across your takes/);
  assert.match(find(el, "history-fallback-reason").textContent, /The call was refused\./);
  assert.match(find(el, "history-fact-0").textContent, /Trunk lean forward/);
  assert.equal(find(el, "history-trend-0"), null);
  assert.equal(find(el, "history-context"), null);
});

test("a gated build asks the 18 statement before a yes, and sends nothing without it (muse-prod.md AC-MP11)", () => {
  const calls = [];
  const el = new El("section");
  const view = { ...M.pageView(PAGE, ENTRY, null), video: false };
  V.renderHistoryPage(el, view, { onRun() {}, onConsent: (v, adults) => calls.push([v, adults]), adultsAsked: true });
  find(el, "history-consent-toggle").click();
  assert.deepEqual(calls, []);
  assert.equal(find(el, "history-consent-missing").hidden, false);
  find(el, "history-consent-adults").checked = true;
  find(el, "history-consent-toggle").click();
  assert.deepEqual(calls, [[true, true]]);
});

test("run button, status line and consent drive the hooks", () => {
  const calls = [];
  const { el, ui } = page(null, { onRun: () => calls.push("run"), onConsent: (v) => calls.push(`consent:${v}`) });
  find(el, "history-run").click();
  find(el, "history-consent-toggle").click();
  assert.deepEqual(calls, ["run", "consent:false"]);
  assert.equal(find(el, "history-status").hidden, true);
  ui.status("waiting", "Simon is reading your takes.");
  assert.equal(find(el, "history-status").textContent, "Simon is reading your takes.");
  assert.equal(find(el, "history-status").hidden, false);
  ui.busy(true);
  assert.equal(find(el, "history-run").disabled, true);
  ui.busy(false);
  assert.equal(find(el, "history-run").disabled, false);
  assert.equal(find(el, "history-report").children.length, 0);
});

test("one take leaves the run button disabled with a reason", () => {
  const el = new El("section");
  V.renderHistoryPage(el, M.pageView({ ...PAGE, takes: [PAGE.takes[0]] }, ENTRY, null), { onRun() {}, onConsent() {} });
  assert.ok("disabled" in find(el, "history-run").attrs);
  assert.match(el.textContent, /at least 2 takes/);
});

// ---------- glue (AC-1 polling, AC-4 slot, anonymous flow) ----------
function fakeServer(routes) {
  const seen = [];
  globalThis.fetch = async (url, init = {}) => {
    const key = `${init.method || "GET"} ${url}`;
    seen.push(key);
    const r = routes[key];
    const res = typeof r === "function" ? r() : r;
    if (!res) return { status: 404, headers: { get: () => null }, json: async () => ({}) };
    return { status: res.status, headers: { get: (k) => (k === "Retry-After" ? res.retry ?? null : null) }, json: async () => res.body ?? null };
  };
  return seen;
}
const U = M.historyUrls(ENTRY);
const IN = { "GET api/auth/me": { status: 200, body: { available: true, signed_in: true, user_id: "u-1", email: "a@b.co", retention: { opted_in: true } } } };
const OUT = { "GET api/auth/me": { status: 200, body: { available: true, signed_in: false } } };

test("AC-1 a 202 run polls after Retry-After and shows the report on 200", async () => {
  dom_clear();
  const delays = [];
  const realSet = globalThis.setTimeout;
  globalThis.setTimeout = (fn, ms) => { delays.push(ms); return realSet(fn, 0); };
  let polls = 0;
  const seen = fakeServer({
    [`GET ${U.page}`]: { status: 200, body: PAGE },
    [`GET ${U.report}`]: () => (polls++ < 3 ? (polls === 1 ? { status: 404 } : { status: 202, retry: "2" }) : { status: 200, body: REPORT }),
    [`POST ${U.run}`]: { status: 202, retry: "4" },
  });
  const root = new El("main");
  const stop = G.mountHistory(root, ENTRY);
  await settle();
  find(root, "history-run").click();
  await settle();
  globalThis.setTimeout = realSet;
  assert.deepEqual(delays.slice(0, 2), [4000, 2000]);
  assert.ok(find(root, "history-trend-0"), "the report is on screen");
  assert.equal(find(root, "history-status").hidden, true);
  assert.ok(seen.includes(`POST ${U.run}`));
  stop();
});

for (const [status, kind] of [[409, "consent"], [422, "few"], [500, "error"]]) {
  test(`AC-1 a ${status} on run shows its status line`, async () => {
    dom_clear();
    fakeServer({ [`GET ${U.page}`]: { status: 200, body: PAGE }, [`POST ${U.run}`]: { status } });
    const root = new El("main");
    G.mountHistory(root, ENTRY);
    await settle();
    find(root, "history-run").click();
    await settle();
    assert.equal(find(root, "history-status").getAttribute("data-kind"), kind);
    assert.equal(find(root, "history-status").textContent, M.stateForStatus(status).message);
    assert.equal(find(root, "history-run").disabled, false);
  });
}

test("a cached 200 on run shows the report at once; a stored report shows on load", async () => {
  dom_clear();
  fakeServer({ [`GET ${U.page}`]: { status: 200, body: { ...PAGE, report: REPORT } } });
  const root = new El("main");
  G.mountHistory(root, ENTRY);
  await settle();
  assert.ok(find(root, "history-focus"));
});

test("a fallback answer on 200 shows the fallback panel", async () => {
  dom_clear();
  fakeServer({ [`GET ${U.page}`]: { status: 200, body: PAGE }, [`POST ${U.run}`]: { status: 200, body: { status: "fallback", reason: "over_budget", facts: PAGE.facts } } });
  const root = new El("main");
  G.mountHistory(root, ENTRY);
  await settle();
  find(root, "history-run").click();
  await settle();
  assert.ok(find(root, "history-fallback"));
});

test("the consent toggle posts {video, version} and redraws", async () => {
  dom_clear();
  const bodies = [];
  fakeServer({ [`GET ${U.page}`]: { status: 200, body: { ...PAGE, consent: { video: false } } }, [`POST ${U.consent}`]: { status: 200, body: {} } });
  const inner = globalThis.fetch;
  globalThis.fetch = async (url, init) => { if (init && init.body) bodies.push(init.body); return inner(url, init); };
  const root = new El("main");
  G.mountHistory(root, ENTRY);
  await settle();
  assert.equal(find(root, "history-consent").getAttribute("data-on"), "false");
  find(root, "history-consent-toggle").click();
  await settle();
  assert.deepEqual(bodies.map(JSON.parse), [{ video: true, version: "video-v2" }]);
  assert.equal(find(root, "history-consent").getAttribute("data-on"), "true");
  const copy = find(root, "history-consent").textContent;
  assert.match(copy, /at most 5/); // true for the reel (5) and for Compare (4 take clips)
  assert.doesNotMatch(copy, /Up to 4/); // negative: the old, untrue-for-the-reel wording
});

test("signed out (401) the page says so and shows no takes", async () => {
  dom_clear();
  fakeServer({ [`GET ${U.page}`]: { status: 401 } });
  const root = new El("main");
  G.mountHistory(root, ENTRY);
  await settle();
  assert.ok(find(root, "history-error"));
  assert.match(root.textContent, /Sign in to see your takes/);
  assert.equal(find(root, "history-run"), null);
});

test("AC-4 the slot shows 'Your takes over time (2)' for a signed-in student with 2 takes", async () => {
  dom_clear();
  fakeServer({ ...IN, [`GET ${U.page}`]: { status: 200, body: PAGE } });
  const section = new El("section");
  G.mountHistory(section, { jobId: "5277380db1e1", entryId: ENTRY, analysis: {}, seek() {} });
  await settle();
  const link = find(section, "history-slot-link");
  assert.match(link.textContent, /Your takes over time \(2\)/);
  assert.equal(link.getAttribute("href"), `#/me/${ENTRY}`);
});

test("AC-4 negative: anonymous (401), one take, no entry id and a network failure leave the slot empty", async () => {
  for (const routes of [{ ...IN, [`GET ${U.page}`]: { status: 401 } }, { ...IN, [`GET ${U.page}`]: { status: 200, body: { takes: [PAGE.takes[0]] } } }, IN]) {
    dom_clear();
    fakeServer(routes);
    const section = new El("section");
    G.mountHistory(section, { jobId: "x", entryId: ENTRY });
    await settle();
    assert.equal(section.children.length, 0);
  }
  const section = new El("section");
  G.mountHistory(section, { jobId: "x" });
  globalThis.fetch = async () => { throw new Error("offline"); };
  G.mountHistory(section, { jobId: "x", entryId: ENTRY });
  await settle();
  assert.equal(section.children.length, 0);
});

test("R2 an anonymous visitor's result page sends no api/me request, a signed-in one with no copies expects the 404", async () => {
  dom_clear();
  const seen = fakeServer({ ...OUT, [`GET ${U.page}`]: { status: 401 } });
  const section = new El("section");
  G.mountHistory(section, { jobId: "x", entryId: ENTRY });
  await settle();
  assert.deepEqual(seen, ["GET api/auth/me"], "only the sign-in status is asked");
  assert.equal(section.children.length, 0);
  dom_clear();
  const inits = [];
  const inner = fakeServer({ ...IN });
  const wrapped = globalThis.fetch;
  globalThis.fetch = async (url, init) => { inits.push([url, init]); return wrapped(url, init); };
  G.mountHistory(new El("section"), { jobId: "x", entryId: ENTRY });
  await settle();
  assert.deepEqual(inits.find(([url]) => url === U.page)[1].expectStatus, [404], "no copies kept yet is not reported as an anomaly");
  assert.ok(inner.includes(`GET ${U.page}`));
});

test("#/me lists the movements, and says so when signed out or empty", async () => {
  dom_clear();
  fakeServer({ "GET api/me/history": { status: 200, body: { entries: [{ entry_id: ENTRY, name: "Body squat", takes: 2 }] } } });
  let root = new El("main");
  G.mountMyTakes(root);
  await settle();
  assert.equal(find(root, "history-mytakes-0").querySelector('[class="hs-mine-link"]').getAttribute("href"), `#/me/${ENTRY}`);
  assert.match(find(root, "history-mytakes-0").textContent, /Body squat2 takes/);
  fakeServer({ "GET api/me/history": { status: 200, body: { entries: [] } } });
  root = new El("main");
  G.mountMyTakes(root);
  await settle();
  assert.ok(find(root, "history-mytakes-empty"));
  fakeServer({ "GET api/me/history": { status: 401 } });
  root = new El("main");
  G.mountMyTakes(root);
  await settle();
  assert.ok(find(root, "history-signedout"));
});

// ---------- rules (AC-5, AC-6) ----------
test("AC-6 the user-facing text has no banned word and no dash", () => {
  const text = ["../../web/model/history.js", "../../web/views/history.js", "../../web/history.js"].map((f) => fs.readFileSync(new URL(f, import.meta.url), "utf8")).join("\n");
  assert.doesNotMatch(text, /coach|medical|injur/i);
  assert.doesNotMatch(text, /\u2014|\u2013/);
});

test("AC-5 history.css has no color literal", () => {
  const css = fs.readFileSync(new URL("../../web/theme/history.css", import.meta.url), "utf8");
  assert.doesNotMatch(css, /#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(/);
});

function dom_clear() { globalThis.fetch = undefined; }
