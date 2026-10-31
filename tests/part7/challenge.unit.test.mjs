// Unit tests for the pure parts of challenges: ranking, badge text, countdown, links, card layout, share paths.
// Run: node --test tests/part7/
import test from "node:test";
import assert from "node:assert/strict";
import {
  rankEntries, strongestText, timeLeft, challengeUrl, safeHttps, cleanName, takeUrl,
} from "../../web/challenge-core.js";
import { wrapText, layoutCard, shareCard, shareLink, copyText, CARD_W, CARD_H, PAD } from "../../web/share-card.js";
import { titleFor } from "../../web/challenge-actions.js";

const E = (name, score, at, extra = {}) => ({ name, score, grade: "B", created_at: at, ...extra });

test("ranking: score descending, a tie goes to the earlier post, ranks start at 1", () => {
  const out = rankEntries([E("b", 80, "2026-01-01T00:00:02Z"), E("a", 80, "2026-01-01T00:00:01Z"), E("c", 95, "2026-01-02T00:00:00Z"), E("d", 10, "2026-01-01T00:00:00Z")]);
  assert.deepEqual(out.map((e) => [e.rank, e.name]), [[1, "c"], [2, "a"], [3, "b"], [4, "d"]]);
});

test("ranking ignores entries without a numeric score and does not mutate its input", () => {
  const input = [E("a", 5, "x"), { name: "bad", score: "9" }, null];
  const out = rankEntries(input);
  assert.deepEqual(out.map((e) => e.name), ["a"]);
  assert.equal(input.length, 3);
  assert.deepEqual(rankEntries(undefined), []);
});

test("the strongest badge reads the stored section label and is absent without one", () => {
  assert.equal(strongestText({ strongest_section: { label: "Rep 2", value: 91 } }), "Strongest: Rep 2");
  assert.equal(strongestText({ strongest_section: { label: "4.9 s to 9.8 s" } }), "Strongest: 4.9 s to 9.8 s");
  assert.equal(strongestText({ strongest_section: null }), null);
  assert.equal(strongestText({}), null);
  assert.equal(strongestText(null), null);
});

test("countdown: no end, minutes, hours, days, ended", () => {
  const now = Date.parse("2026-11-01T12:00:00Z");
  assert.deepEqual(timeLeft(null, now), { ended: false, text: "No end date" });
  assert.deepEqual(timeLeft("2026-11-01T12:20:00Z", now), { ended: false, text: "Ends in 20 min" });
  assert.deepEqual(timeLeft("2026-11-01T17:30:00Z", now), { ended: false, text: "Ends in 5 h" });
  assert.deepEqual(timeLeft("2026-11-05T12:00:00Z", now), { ended: false, text: "Ends in 4 days" });
  assert.deepEqual(timeLeft("2026-11-01T12:00:00Z", now), { ended: true, text: "Ended" });
  assert.deepEqual(timeLeft("2026-10-01T12:00:00Z", now), { ended: true, text: "Ended" });
  assert.equal(timeLeft("garbage", now).ended, false);
});

test("the challenge link is origin + path + hash route and keeps a staging base path", () => {
  const loc = { origin: "https://example.test", pathname: "/simon-part-7/", search: "?x=1", hash: "#/result/abc" };
  assert.equal(challengeUrl("Ab_c-1234", loc), "https://example.test/simon-part-7/#/challenge/Ab_c-1234");
});

test("sponsor links must be https", () => {
  assert.equal(safeHttps("https://example.com/shop"), true);
  for (const bad of ["http://example.com", "javascript:alert(1)", "https://", "https://a b.com", "", null, undefined, 'https://x.com/"onclick=']) assert.equal(safeHttps(bad), false, String(bad));
});

test("names are trimmed, white space collapsed and cut to 24 characters", () => {
  assert.equal(cleanName("  Sam \n  Lee "), "Sam Lee");
  assert.equal(cleanName("x".repeat(30)).length, 24);
  assert.equal(cleanName(""), "");
  assert.equal(cleanName(undefined), "");
});

test("the follow address carries the entry and the challenge, encoded; nothing is kept in the tab", () => {
  assert.equal(takeUrl("lateral-raise", "abc123XY"), "#/follow/lateral-raise/c/abc123XY");
  assert.equal(takeUrl("a b", "x/y"), "#/follow/a%20b/c/x%2Fy");
  assert.equal(globalThis.sessionStorage, undefined);
});

test("the challenge title is cut to the server's 60 characters", () => {
  assert.equal(titleFor("Dumbbell lateral raise"), "Beat my Dumbbell lateral raise");
  assert.equal(Array.from(titleFor("x".repeat(100))).length, 60);
});

// ----- card layout --------------------------------------------------------------------------------------
const measure = (font, s) => s.length * Number(/(\d+)px/.exec(font)[1]) * 0.55;
const model = {
  movement: "Dumbbell lateral raise", score: 82, grade: "B", strongest: "Rep 2", challenger: "Sam",
  title: "Beat my Dumbbell lateral raise", url: "https://example.test/simon-part-7/#/challenge/Ab_c-1234", sponsor: null,
};
const texts = (ops) => ops.filter((o) => o.type === "text");

test("wrapText wraps on words, breaks a long word by characters and ends with an ellipsis past the line limit", () => {
  const m = (s) => s.length * 10;
  assert.deepEqual(wrapText(m, "aa bb cc dd", 50), ["aa bb", "cc dd"]);
  assert.deepEqual(wrapText(m, "abcdefghij", 40), ["abcd", "efgh", "ij"]);
  const cut = wrapText(m, "one two three four five six", 50, 2);
  assert.equal(cut.length, 2);
  assert.ok(cut[1].endsWith("..."));
  assert.deepEqual(wrapText(m, "", 50), []);
});

test("the card is 1080 x 1350 and carries movement, score, grade, strongest, challenger, prompt and link", () => {
  assert.equal(CARD_W, 1080);
  assert.equal(CARD_H, 1350);
  const all = texts(layoutCard(model, measure)).map((o) => o.text).join("\n");
  for (const want of ["Dumbbell lateral raise", "Sam scored", "82", "B", "Strongest: Rep 2", "Can you beat it?", "Beat my Dumbbell lateral raise"]) assert.ok(all.includes(want), want);
  assert.ok(all.replace(/\n/g, "").includes(model.url));
  assert.ok(!all.includes("Sponsored by"));
});

test("every text line fits the card and stays above the bottom edge", () => {
  const long = { ...model, movement: "A very long movement name that has to wrap onto more than one line of the card", challenger: "Someone With A Long Name",
    url: `https://example.test/${"x".repeat(120)}`, title: "T ".repeat(60), sponsor: "Example Sportswear" };
  for (const m of [model, long]) {
    for (const op of texts(layoutCard(m, measure))) {
      const w = measure(op.font, op.text);
      const left = op.align === "center" ? op.x - w / 2 : op.x;
      assert.ok(left >= 0 && left + w <= CARD_W - (op.align === "center" ? 0 : PAD) + 1 || op.text === String(m.score), `${op.text} (${left}, ${w})`);
      assert.ok(op.y > 0 && op.y <= CARD_H, `${op.text} at y=${op.y}`);
    }
  }
});

test("lines of different blocks do not overlap vertically", () => {
  const ys = texts(layoutCard({ ...model, sponsor: "Example Sportswear" }, measure)).filter((o) => o.align === "left").map((o) => o.y);
  const sorted = [...ys].sort((a, b) => a - b);
  for (let i = 1; i < sorted.length; i++) assert.ok(sorted[i] - sorted[i - 1] >= 30, `${sorted[i - 1]} then ${sorted[i]}`);
});

test("no strongest line without a strongest section, a sponsor line only when sponsored", () => {
  const plain = texts(layoutCard({ ...model, strongest: null }, measure)).map((o) => o.text).join("|");
  assert.ok(!plain.includes("Strongest"));
  const sponsored = texts(layoutCard({ ...model, sponsor: "Example Sportswear" }, measure)).map((o) => o.text);
  assert.ok(sponsored.includes("Sponsored by Example Sportswear"));
});

// ----- sharing ------------------------------------------------------------------------------------------
function fakeWin({ share, canShare, clipboard = true, exec = true } = {}) {
  const log = { downloads: [], copied: [], shared: [], revoked: [] };
  const body = { append(el) { el.attached = true; } };
  const doc = {
    body,
    createElement: (tag) => ({ tag, style: {}, setAttribute() {}, select() {}, remove() {}, click() { log.downloads.push({ href: this.href, name: this.download }); } }),
    execCommand: () => { log.execCommand = true; return exec; },
  };
  const navigator = {};
  if (share) navigator.share = async (d) => { log.shared.push(d); return share(d); };
  if (canShare) navigator.canShare = canShare;
  if (clipboard) navigator.clipboard = { writeText: async (t) => { log.copied.push(t); } };
  return {
    log, navigator, document: doc, File: class { constructor(parts, name, opts) { this.name = name; this.type = opts.type; } },
    URL: { createObjectURL: () => "blob:x", revokeObjectURL: (u) => log.revoked.push(u) }, setTimeout: (fn) => fn(),
  };
}
const png = { size: 4, type: "image/png" };
const url = "https://example.test/#/challenge/abc";

test("share: with the share sheet and file support, the PNG, link and text go to navigator.share", async () => {
  const win = fakeWin({ share: async () => {}, canShare: () => true });
  const r = await shareCard({ blob: png, url, text: "Beat me" }, win);
  assert.deepEqual(r, { mode: "shared" });
  assert.equal(win.log.shared[0].url, url);
  assert.equal(win.log.shared[0].text, "Beat me");
  assert.equal(win.log.shared[0].files[0].type, "image/png");
  assert.equal(win.log.downloads.length, 0);
});

test("share: closing the sheet is a cancel, not a download", async () => {
  const win = fakeWin({ share: async () => { throw Object.assign(new Error("x"), { name: "AbortError" }); }, canShare: () => true });
  assert.deepEqual(await shareCard({ blob: png, url, text: "t" }, win), { mode: "cancelled" });
  assert.equal(win.log.downloads.length, 0);
});

test("share fallback: no share sheet means the PNG downloads and the link is copied", async () => {
  const win = fakeWin({});
  const r = await shareCard({ blob: png, url, text: "t" }, win);
  assert.deepEqual(r, { mode: "download", copied: true });
  assert.deepEqual(win.log.downloads, [{ href: "blob:x", name: "simon-challenge.png" }]);
  assert.deepEqual(win.log.copied, [url]);
});

test("share fallback: a sheet that cannot take files also downloads; a failing sheet falls back too", async () => {
  const noFiles = fakeWin({ share: async () => {}, canShare: () => false });
  assert.equal((await shareCard({ blob: png, url, text: "t" }, noFiles)).mode, "download");
  const broken = fakeWin({ share: async () => { throw new Error("denied"); }, canShare: () => true });
  assert.equal((await shareCard({ blob: png, url, text: "t" }, broken)).mode, "download");
});

test("copy falls back to a textarea when the clipboard API is missing, and reports failure", async () => {
  const win = fakeWin({ clipboard: false });
  assert.equal(await copyText(url, win), true);
  assert.equal(win.log.execCommand, true);
  assert.equal(await copyText(url, fakeWin({ clipboard: false, exec: false })), false);
});

test("link share: the share sheet, else copy", async () => {
  const withSheet = fakeWin({ share: async () => {} });
  assert.deepEqual(await shareLink({ url, text: "t" }, withSheet), { mode: "shared" });
  assert.deepEqual(await shareLink({ url, text: "t" }, fakeWin({})), { mode: "copy", copied: true });
});
