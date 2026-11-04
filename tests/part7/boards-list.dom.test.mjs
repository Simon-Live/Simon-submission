// Finding leaderboards (docs/specs/board-discovery.md AC-1 to AC-8): the words, the urls and the four mounts.
//   node --test tests/part7/boards-list.dom.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { installDom, El, find, findAll, all } from "./fake-dom.mjs";

const { store } = installDom();
const core = await import("../../web/boards-list-core.js");
const view = await import("../../web/boards-list.js");

const card = (id, extra = {}) => ({
  id, title: `Beat my ${id}`, kind: "friend", visibility: "public", ends_at: null, ended: false, entries: 3, viewer_rank: null,
  top: [{ name: "Mo", score_label: "9,249 points of 12,160" }, { name: "Cat", score_label: "8,000 points of 12,160" }], url: `#/challenge/${id}`, ...extra,
});
const answer = (cards) => async () => ({ status: 200, ok: true, body: { boards: cards } });
const text = (n) => n.textContent;
const settle = () => new Promise((r) => setTimeout(r, 0));
const mount = async (fn, ...args) => { const root = new El("div"); const stop = fn(root, ...args); await settle(); return { root, stop }; };

test("AC-1: ordinals read 1st 2nd 3rd 4th 11th 12th 13th 21st 22nd 101st", () => {
  assert.deepEqual([1, 2, 3, 4, 11, 12, 13, 21, 22, 101].map(core.ordinal), ["1st", "2nd", "3rd", "4th", "11th", "12th", "13th", "21st", "22nd", "101st"]);
});

test("AC-1: the card words", () => {
  const c = card("a", { viewer_rank: 3 });
  assert.equal(core.rankText(c), "You are 3rd");
  assert.equal(core.resultRankText(c), "You are 3rd on Beat my a");
  assert.equal(core.rankText(card("a")), "", "negative: not on the board, no rank words");
  assert.equal(core.whoText(card("a", { entries: 1 })), "1 person");
  assert.equal(core.whoText(card("a", { entries: 0 })), "No scores yet");
  assert.equal(core.whenText(card("a", { ended: true })), "Ended");
  assert.equal(core.whenText(card("a"), 0), "No end date");
  assert.equal(core.whenText(card("a", { ends_at: "1970-01-04T00:00:00Z" }), 0), "Ends in 3 days");
  assert.equal(core.leadingText(card("a")), "Leading: Mo");
  assert.equal(core.leaderScore(card("a")), "9,249 points of 12,160");
  const { open, ended } = core.split([card("a"), card("b", { ended: true })]);
  assert.deepEqual([open.map((c) => c.id), ended.map((c) => c.id)], [["a"], ["b"]]);
});

test("AC-2: urls name the movement and the jobs this browser sent for it", () => {
  const rows = [{ job: "aaaaaaaaaaaa", entry: "squat", at: new Date().toISOString(), name: "x" }, { job: "bbbbbbbbbbbb", entry: "lunge", at: new Date().toISOString(), name: "x" }];
  store.set("simon.deviceTakes", JSON.stringify(rows));
  assert.equal(core.movementBoardsUrl("squat"), "api/movements/squat/boards?jobs=aaaaaaaaaaaa");
  assert.match(core.myBoardsUrl(), /^api\/me\/boards\?jobs=(aaaaaaaaaaaa,bbbbbbbbbbbb|bbbbbbbbbbbb,aaaaaaaaaaaa)$/);
  assert.equal(core.resultBoardsUrl("squat", "cccccccccccc"), "api/movements/squat/boards?jobs=cccccccccccc");
  store.clear();
  assert.equal(core.movementBoardsUrl("a b"), "api/movements/a%20b/boards", "no jobs, no query");
  assert.equal(core.homeBoardsUrl(), "api/boards");
});

test("AC-2: a missing or private movement reads as no boards; a failed answer throws", async () => {
  assert.deepEqual(await core.getBoards("u", async () => ({ status: 404, ok: false, body: null })), []);
  await assert.rejects(core.getBoards("u", async () => ({ status: 0, ok: false, body: null })));
  await assert.rejects(core.getBoards("u", async () => ({ status: 200, ok: true, body: {} })));
});

test("AC-3, AC-4, AC-5: movement page lists open boards with a way in, ended ones apart, and a way to start", async () => {
  const cards = [card("open1", { viewer_rank: 2 }), card("old1", { ended: true, ends_at: "2026-01-01T00:00:00Z" })];
  const { root } = await mount(view.mountMovementBoards, "arm-wave", { fetchJson: answer(cards) });
  assert.match(text(find(root, "movement-boards")), /Active leaderboards/);
  const active = find(root, "challenge-list");
  assert.deepEqual(findAll(active, "board-who").map(text), ["3 people"]);
  assert.equal(text(find(active, "board-you")), "You are 2nd");
  assert.equal(text(find(active, "board-lead")), "Leading: Mo. Top score 9,249 points of 12,160");
  assert.equal(find(root, "challenge-link-open1").getAttribute("href"), "#/challenge/open1");
  const ended = find(root, "boards-ended");
  assert.match(text(ended), /Ended boards/);
  assert.ok(find(ended, "challenge-link-old1"), "the ended board is kept, in its own section");
  assert.equal(find(active, "challenge-link-old1"), null, "negative: an ended board is not among the active ones");
  assert.equal(find(root, "board-start").getAttribute("href"), "#/follow/arm-wave");
  assert.equal(find(root, "boards-empty"), null);
});

test("AC-6: no boards gives an empty state and Start as the main action", async () => {
  const { root } = await mount(view.mountMovementBoards, "arm-wave", { fetchJson: answer([]) });
  assert.match(text(find(root, "boards-empty")), /No one has started a leaderboard/);
  assert.match(find(root, "board-start").getAttribute("class"), /primary/);
  assert.equal(find(root, "challenge-list"), null);
  assert.equal(find(root, "boards-ended"), null, "negative: no empty Ended heading");
});

test("AC-6: a failed load says so and Try again loads them", async () => {
  let n = 0;
  const fetchJson = async () => (++n === 1 ? { status: 0, ok: false, body: null } : { status: 200, ok: true, body: { boards: [card("late")] } });
  const { root } = await mount(view.mountMovementBoards, "arm-wave", { fetchJson });
  assert.equal(find(root, "boards-failed").getAttribute("role"), "status");
  find(root, "boards-retry").click();
  await settle();
  assert.ok(find(root, "challenge-link-late"));
});

test("AC-8: labels for a screen reader and no private fields on a card", async () => {
  const { root } = await mount(view.mountMovementBoards, "arm-wave", { fetchJson: answer([card("a"), card("z", { ended: true })]) });
  const section = find(root, "movement-boards");
  const heading = all(root).find((n) => n.attrs && n.attrs.id === section.getAttribute("aria-labelledby"));
  assert.match(text(heading), /Active leaderboards/);
  assert.equal(find(root, "challenge-list").getAttribute("aria-label"), "Active leaderboards");
  assert.equal(find(root, "boards-ended-list").getAttribute("aria-label"), "Ended boards");
  assert.equal(/@|job_id|"pid"/.test(text(root)), false, "negative: no email or job id on the page");
  assert.equal(all(root).some((n) => n.tag === "a" && !text(n).trim()), false, "every link has words");
});

test("AC-7: home shows open boards only, nothing when there are none", async () => {
  const some = await mount(view.mountHomeBoards, { fetchJson: answer([card("a"), card("z", { ended: true })]) });
  assert.ok(find(some.root, "challenge-link-a"));
  assert.equal(find(some.root, "challenge-link-z"), null, "negative: no ended board on home");
  const none = await mount(view.mountHomeBoards, { fetchJson: answer([]) });
  assert.equal(none.root.children.length, 0);
  const failed = await mount(view.mountHomeBoards, { fetchJson: async () => ({ status: 0, ok: false, body: null }) });
  assert.equal(failed.root.children.length, 0, "home stays whole when the list fails");
});

test("AC-7: Me shows My challenges, ended apart, and an empty state with the next step", async () => {
  const mine = await mount(view.mountMyBoards, { fetchJson: answer([card("a", { viewer_rank: 1 }), card("z", { ended: true, viewer_rank: 4 })]) });
  assert.match(text(find(mine.root, "my-boards")), /My challenges/);
  assert.equal(text(find(mine.root, "board-you")), "You are 1st");
  assert.ok(find(find(mine.root, "my-boards-ended"), "challenge-link-z"));
  assert.equal(find(mine.root, "my-boards-empty"), null);
  const none = await mount(view.mountMyBoards, { fetchJson: answer([]) });
  assert.match(text(find(none.root, "my-boards-empty")), /not on a board yet/);
  assert.equal(find(none.root, "my-boards-next").getAttribute("href"), "#/");
});

test("AC-7: a result says where the take stands, once per board, and says nothing when it is on none", async () => {
  const root = new El("div");
  await view.mountResultRank(root, "squat", "cccccccccccc", { fetchJson: answer([card("a", { viewer_rank: 3 }), card("b")]) });
  const links = findAll(find(root, "result-ranks"), "result-rank-a");
  assert.deepEqual(links.map(text), ["You are 3rd on Beat my a"]);
  assert.equal(links[0].getAttribute("href"), "#/challenge/a");
  const bare = new El("div");
  await view.mountResultRank(bare, "squat", "cccccccccccc", { fetchJson: answer([card("b")]) });
  assert.equal(bare.children.length, 0);
  await view.mountResultRank(bare, "squat", "cccccccccccc", { fetchJson: async () => ({ status: 0, ok: false, body: null }) });
  assert.equal(bare.children.length, 0, "a failed answer adds nothing to the result");
});
