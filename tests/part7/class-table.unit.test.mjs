// The class table card and the class handout (docs/specs/class-table.md AC-C10, docs/specs/handout.md AC-H1, AC-H3):
// model wording, the views over the fake DOM, and the handout QR read back to the follow link.
//   node --test tests/part7/class-table.unit.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { El, installDom, all, find } from "./fake-dom.mjs";
import { decodeMatrix, matrixFromPath } from "./qr-decode.mjs";

installDom();
const cls = (el) => (el.attrs.class || "").split(/\s+/).filter(Boolean);
Object.defineProperty(El.prototype, "classList", {
  configurable: true,
  get() { return { add: (c) => { this.attrs.class = [...new Set([...cls(this), c])].join(" "); }, contains: (c) => cls(this).includes(c) }; },
});
globalThis.document.createElementNS = (_ns, t) => new El(t);

const { classTableView, teacherView, handoutHref, SEEDED, OWNER_NOTE } = await import("../../web/model/teacher.js");
const { followUrl, handoutView, HANDOUT_TEXT } = await import("../../web/model/handout.js");
const { renderTeacher } = await import("../../web/views/teacher.js");
const { renderHandout, renderHandoutError } = await import("../../web/views/handout.js");
const { QUIET } = await import("../../web/model/qr.js");

const TABLE = { follower_count: 3, takes_7d: 5, window_days: 7, top_cue: { text: "Knees out", followers: 3 }, seeded: false,
  followers: [{ n: 1, takes: 3, first: 50, latest: 82, delta: 32 }, { n: 2, takes: 2, first: 60, latest: 57.5, delta: -2.5 }, { n: 4, takes: 2, first: 70, latest: 70, delta: 0 }] };
const DOC = { takes: [{ score: 77, grade: "C", at: "2026-10-31T10:00:00Z", top_cues: ["Knees out"] }], cue_counts: [{ text: "Knees out", count: 1 }], class_table: TABLE };
const LOC = { origin: "http://127.0.0.1:8727", pathname: "/" };

test("class table view: facts, top cue share, signed changes and their tones", () => {
  const vm = classTableView(TABLE);
  assert.deepEqual(vm.facts, [{ key: "followers", value: "3", label: "followers" }, { key: "recent", value: "5", label: "takes in the last 7 days" }]);
  assert.deepEqual(vm.topCue, { text: "Knees out", share: "for 3 of 3 followers" });
  assert.deepEqual(vm.rows.map((r) => [r.label, r.change, r.tone, r.detail]), [
    ["Follower 1", "+32", "good", "50 to 82 over 3 takes"], ["Follower 2", "-2.5", "bad", "60 to 57.5 over 2 takes"], ["Follower 4", "0", "same", "70 to 70 over 2 takes"]]);
  assert.equal(vm.seeded, null);
  assert.equal(vm.ownerNote, "Only you see each follower's scores.");
});

test("class table view: the public answer (no followers key) has no rows and no owner line", () => {
  const { followers, ...publicTable } = TABLE;
  assert.ok(followers.length);
  const vm = classTableView(publicTable);
  assert.equal(vm.rows, null);
  assert.equal(vm.ownerNote, null);
  assert.equal(vm.topCue.share, "for 3 of 3 followers");
});

test("teacher page: a visitor who does not own the movement sees the class facts but no per-follower block", () => {
  const { followers, ...publicTable } = TABLE;
  void followers;
  const screen = new El("section");
  renderTeacher(screen, teacherView({ ...DOC, class_table: publicTable }, { name: "Body squat" }, "body-squat"));
  assert.ok(find(screen, "class-top-cue") && find(screen, "class-followers"));
  for (const id of ["class-follower-block", "class-changes", "class-no-change", "class-owner-note"]) assert.equal(find(screen, id), null, id);
  assert.doesNotMatch(screen.textContent, /From first take to latest|Follower 1|Only you see/);
});

test("class table view: one follower and one take read in the singular; no table gives null", () => {
  const vm = classTableView({ follower_count: 1, takes_7d: 1, window_days: 7, top_cue: { text: "Knees out", followers: 1 }, followers: [], seeded: false });
  assert.deepEqual(vm.facts.map((f) => f.label), ["follower", "take in the last 7 days"]);
  assert.equal(vm.topCue.share, "for 1 of 1 follower");
  assert.equal(classTableView(undefined), null);
  assert.equal(classTableView("x"), null);
});

test("class table view: malformed rows are dropped and a missing top cue stays empty", () => {
  const vm = classTableView({ follower_count: 2, takes_7d: 0, top_cue: { text: "" }, followers: [{ n: 1, delta: "3" }, null, { n: 2, takes: 2, first: 1, latest: 2, delta: 1 }] });
  assert.equal(vm.topCue, null);
  assert.deepEqual(vm.rows.map((r) => r.label), ["Follower 2"]);
});

test("teacher page: the class card renders its facts, top cue and rows, and the handout action", () => {
  const screen = new El("section");
  renderTeacher(screen, teacherView(DOC, { name: "Body squat" }, "body-squat"));
  const card = find(screen, "class-table");
  assert.ok(card);
  assert.equal(find(card, "class-changes").children.length, 3);
  assert.match(find(card, "class-top-cue").textContent, /Knees out.*for 3 of 3 followers/);
  assert.equal(find(screen, "teacher-handout").attrs.href, "#/teacher/body-squat/handout");
  assert.equal(find(card, "class-owner-note").textContent, OWNER_NOTE);
  assert.equal(find(screen, "teacher-seeded"), null); // negative: real data carries no seeded label
  assert.equal(find(card, "class-seeded"), null);
  assert.doesNotMatch(screen.textContent, /null|undefined/);
});

test("teacher page: seeded class data is labelled on the page and on the card", () => {
  const screen = new El("section");
  renderTeacher(screen, teacherView({ ...DOC, class_table: { ...TABLE, seeded: true } }, { name: "Body squat" }, "body-squat"));
  assert.match(find(screen, "teacher-seeded").textContent, new RegExp(SEEDED.badge));
  assert.match(find(screen, "class-seeded").textContent, /not by real followers/);
});

test("teacher page: no returning follower and no cue have their own lines", () => {
  const screen = new El("section");
  renderTeacher(screen, teacherView({ ...DOC, class_table: { ...TABLE, top_cue: null, followers: [] } }, null, "x"));
  assert.ok(find(screen, "class-no-change") && find(screen, "class-no-cue"));
  assert.equal(find(screen, "class-changes"), null);
});

test("teacher page: the empty state still offers the handout", () => {
  const screen = new El("section");
  renderTeacher(screen, teacherView({ takes: [], cue_counts: [], class_table: { follower_count: 0, takes_7d: 0, followers: [], top_cue: null } }, null, "body-squat"));
  assert.ok(find(screen, "teacher-empty"));
  assert.equal(find(screen, "teacher-handout").attrs.href, handoutHref("body-squat"));
  assert.equal(find(screen, "class-table"), null);
});

test("follow link: the page address with the follow route, the id encoded", () => {
  assert.equal(followUrl("body-squat-19b06562", LOC), "http://127.0.0.1:8727/#/follow/body-squat-19b06562");
  assert.equal(followUrl("a b", { origin: "https://example.org", pathname: "/simon-part-7/" }), "https://example.org/simon-part-7/#/follow/a%20b");
});

test("handout: title, steps, back link, and a QR code that reads back to the follow link", () => {
  const link = followUrl("body-squat-19b06562", LOC);
  const vm = handoutView("body-squat-19b06562", "Body squat", link);
  assert.equal(vm.title, "Follow Body squat with Simon");
  assert.equal(vm.back.href, "#/teacher/body-squat-19b06562");
  const screen = new El("section");
  let printed = 0;
  renderHandout(screen, vm, () => { printed += 1; });
  assert.equal(find(screen, "handout-link").textContent, link);
  assert.equal(find(screen, "handout-link").attrs.href, link);
  assert.equal(find(screen, "handout-title").textContent, vm.title);
  assert.equal(all(find(screen, "handout")).filter((n) => n instanceof El && n.tag === "li").length, HANDOUT_TEXT.steps.length);
  const path = find(screen, "handout-qr-path").attrs.d;
  const side = Number(find(screen, "handout-qr").attrs.viewBox.split(" ")[2]);
  assert.equal(decodeMatrix(matrixFromPath(path, side), QUIET).text, link);
  assert.equal(printed, 0);
  find(screen, "handout-print").click();
  assert.equal(printed, 1);
});

test("handout: a nameless entry uses its id; the error block tells not found from failed", () => {
  assert.equal(handoutView("x-1", "", "http://h/#/follow/x-1").title, "Follow x-1 with Simon");
  const a = new El("section");
  const b = new El("section");
  renderHandoutError(a, true);
  renderHandoutError(b, false);
  assert.match(find(a, "handout-error").textContent, /not found/);
  assert.match(find(b, "handout-error").textContent, /did not load/);
});
