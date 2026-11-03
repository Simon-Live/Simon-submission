// TICKET-322: the source and licence credit, its wording, its link safety, the negative and the owner's form.
//   node --test tests/part7/source-credit.dom.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { installDom, El, find, findAll, all } from "./fake-dom.mjs";

installDom();
Object.defineProperty(El.prototype, "dataset", { get() { return (this._ds ||= {}); } });
Object.defineProperty(El.prototype, "hidden", { get() { return this.attrs.hidden !== undefined; }, set(v) { if (v) this.attrs.hidden = ""; else delete this.attrs.hidden; } });

let calls = [];
let answers = {};
globalThis.fetch = async (url, init = {}) => {
  const method = init.method || "GET";
  calls.push({ url, method, body: init.body ? JSON.parse(init.body) : undefined });
  const out = answers[`${method} ${url}`] || { status: 404, body: {} };
  return { status: out.status, json: async () => out.body, headers: { get: () => null } };
};

const { creditView, safeUrl, formBody, failText, TEXT } = await import("../../web/model/source-credit.js");
const { creditBlock, mountSourceCredit } = await import("../../web/source-credit.js");
const { renderSnapshot } = await import("../../web/views/shared.js");

const SRC = { title: "MM-Fit workout", creator: "Stromback et al.", licence: "CC BY 4.0", licence_label: "CC BY 4.0", licence_url: "https://creativecommons.org/licenses/by/4.0/", url: "https://mmfit.github.io/" };
const LICENCES = ["CC BY 4.0", "Pexels License", "own recording", "Other"];
const flush = () => new Promise((r) => setTimeout(r, 0));
const text = (n) => n.textContent;

test("a link is safe only when it is plain https", () => {
  assert.equal(safeUrl("https://mmfit.github.io/"), "https://mmfit.github.io/");
  for (const bad of ["javascript:alert(1)", "data:text/html,x", "http://example.com/", "//example.com", "https://u:p@example.com/", "https://example.com/a b", "https://localhost/", 5, null, `https://example.com/${"a".repeat(500)}`]) {
    assert.equal(safeUrl(bad), null, String(bad));
  }
});

test("creditView is null for no source and for a source with nothing readable", () => {
  assert.equal(creditView(null), null);
  assert.equal(creditView(undefined), null);
  assert.equal(creditView("x"), null);
  assert.equal(creditView({}), null);
  assert.equal(creditView({ title: "  ", url: "javascript:alert(1)" }), null);
  assert.deepEqual(creditView({ licence: "Other", licence_label: "My terms" }), { title: "", creator: "", licence: "My terms", licenceUrl: null, own: false, changes: "", url: null, host: "" });
});

test("the credit block shows title, creator, licence and a link that opens in a new tab safely", () => {
  const block = creditBlock(SRC, "watch-source");
  assert.equal(block.attrs["data-testid"], "watch-source");
  assert.equal(text(find(block, "watch-source-title")), "MM-Fit workout");
  assert.equal(text(find(block, "watch-source-creator")), "by Stromback et al.");
  assert.equal(text(find(block, "watch-source-licence")), "Licence: CC BY 4.0");
  const lic = find(block, "watch-source-licence-link");
  assert.equal(lic.attrs.href, "https://creativecommons.org/licenses/by/4.0/");
  assert.equal(lic.attrs.target, "_blank");
  assert.equal(lic.attrs.rel, "noopener noreferrer");
  assert.equal(text(find(block, "watch-source-changes")), "Changes: Simon re-encodes the clip, may cut its length and builds a 3D model from it.");
  assert.match(text(find(block, "watch-source-link")), /mmfit\.github\.io/);
  const link = find(block, "watch-source-link");
  assert.equal(link.attrs.href, "https://mmfit.github.io/");
  assert.equal(link.attrs.target, "_blank");
  assert.equal(link.attrs.rel, "noopener noreferrer");
});

test("a licence page off the licence sites is not drawn as a link, CC0 and own recording carry no changes line", () => {
  const rogue = creditBlock({ licence: "CC BY 4.0", licence_url: "https://evil.example/x" }, "r");
  assert.equal(find(rogue, "r-licence-link"), null);
  const cc0 = creditBlock({ title: "t", licence: "CC0", licence_label: "CC0", licence_url: "https://creativecommons.org/publicdomain/zero/1.0/" }, "c");
  assert.ok(find(cc0, "c-licence-link"));
  assert.equal(find(cc0, "c-changes"), null);
  const own = creditBlock({ title: "t", licence: "own recording", licence_label: "Own recording (no licence needed)", licence_url: "" }, "o");
  assert.equal(text(find(own, "o-licence")), "Own recording (no licence needed)");  // no "Licence:" lead for an own recording
  assert.equal(find(own, "o-changes"), null);
  assert.equal(creditView({ title: "t", licence: "own recording" }).licence, "Own recording (no licence needed)");
});

test("negative: no source draws no credit block, on every view", () => {
  assert.equal(creditBlock(null), null);
  assert.equal(creditBlock(undefined, "follow-source"), null);
  assert.equal(creditBlock({ title: "", creator: "", licence: "", url: "" }), null);
  const page = new El("div");
  renderSnapshot(page, { kind: "take_result", title: "A result", author: "Ana", source: null }, model());
  assert.equal(findAll(page, "shared-source").length, 0);
  renderSnapshot(page, { kind: "take_result", title: "A result", author: "Ana" }, model());
  assert.equal(findAll(page, "shared-source").length, 0);
});

test("markup in a field is text, never an element, and an unsafe link is not drawn", () => {
  const evil = { title: "<img src=x onerror=alert(1)>", creator: "<b>x</b>", licence: "Other", licence_label: "<script>1</script>", url: "javascript:alert(1)" };
  const block = creditBlock(evil);
  assert.equal(text(find(block, "source-credit-title")), "<img src=x onerror=alert(1)>");
  assert.equal(find(block, "source-credit-link"), null);
  assert.ok(all(block).every((n) => !["img", "script", "b"].includes(n.tag)));
  assert.equal(text(find(block, "source-credit-licence")), "Licence: <script>1</script>");
});

const model = () => ({ viewModel: (s) => ({ heading: s.title, byline: "", attribution: null, result: null, score: null, faults: [], trends: [], rows: [], clip: null, summary: "", on: "", until: "" }), bylines: null });

test("a share view draws the credit between the byline and the rest", () => {
  const page = new El("div");
  renderSnapshot(page, { kind: "take_result", title: "A result", source: SRC }, model());
  assert.equal(text(find(page, "shared-source-title")), "MM-Fit workout");
  assert.equal(find(page, "shared-source-link").attrs.rel, "noopener noreferrer");
});

test("the form body keeps the Other words only for Other", () => {
  assert.deepEqual(formBody({ title: "T", licence: "Other", licence_other: "Mine", url: "https://a.org/" }), { title: "T", creator: "", licence: "Other", licence_other: "Mine", url: "https://a.org/" });
  assert.equal(formBody({ title: "T", licence: "CC0", licence_other: "stale" }).licence_other, "");
});

test("failText prefers the server sentence and says so when offline", () => {
  assert.equal(failText({ status: 400, body: { message: "Use a web address." } }), "Use a web address.");
  assert.equal(failText({ status: 500, body: null }), TEXT.failed);
  assert.equal(failText({ status: 0, body: null }), TEXT.offline);
});

function serve(kind, id, body, status = 200) {
  calls = [];
  answers = { [`GET api/source/${kind}/${id}`]: { status, body } };
}

test("a stranger sees the credit and no form", async () => {
  serve("entry", "lift", { source: SRC, mine: false, licences: LICENCES });
  const slot = mountSourceCredit("entry", "lift", "watch-source");
  await flush();
  assert.ok(find(slot, "watch-source"));
  assert.equal(find(slot, "watch-source-edit"), null);
});

test("with no source a stranger sees nothing and an entry with no row stays empty", async () => {
  serve("entry", "lift", { source: null, mine: false, licences: LICENCES });
  const slot = mountSourceCredit("entry", "lift", "watch-source");
  await flush();
  assert.equal(slot.children.length, 0);
  serve("entry", "lift", {}, 404);
  const gone = mountSourceCredit("entry", "lift", "watch-source");
  await flush();
  assert.equal(gone.children.length, 0);
});

test("the follow view passes edit false: credit only", async () => {
  serve("entry", "lift", { source: SRC, mine: true, licences: LICENCES });
  const slot = mountSourceCredit("entry", "lift", "follow-source", { edit: false });
  await flush();
  assert.ok(find(slot, "follow-source"));
  assert.equal(find(slot, "follow-source-edit"), null);
});

test("the owner sees a closed Source and licence control even with no source", async () => {
  serve("take", "job12345", { source: null, mine: true, licences: LICENCES });
  const slot = mountSourceCredit("take", "job12345", "result-source");
  await flush();
  const control = find(slot, "result-source-edit");
  assert.equal(control.tag, "details");
  assert.equal(control.attrs.open, undefined);
  assert.equal(text(control.children[0]), "Source and licence");
  assert.equal(find(slot, "result-source"), null);
  const options = findAll(slot, "result-source-edit-licence")[0].children.map((o) => o.attrs.value);
  assert.deepEqual(options, ["", ...LICENCES]);
});

test("saving posts the fields, shows the new credit and keeps the control open", async () => {
  serve("take", "job12345", { source: null, mine: true, licences: LICENCES });
  answers["POST api/me/source/take/job12345"] = { status: 200, body: { source: SRC, mine: true } };
  const slot = mountSourceCredit("take", "job12345", "result-source");
  await flush();
  find(slot, "result-source-edit").setAttribute("open", "");
  find(slot, "result-source-edit-title").value = "MM-Fit workout";
  find(slot, "result-source-edit-licence").value = "CC BY 4.0";
  find(slot, "result-source-edit-url").value = "https://mmfit.github.io/";
  const form = find(slot, "result-source-edit").children[1];
  const ev = new Event("submit", { cancelable: true });
  form.dispatchEvent(ev);
  await flush();
  const post = calls.find((c) => c.method === "POST");
  assert.deepEqual(post.body, { title: "MM-Fit workout", creator: "", licence: "CC BY 4.0", licence_other: "", url: "https://mmfit.github.io/" });
  assert.equal(ev.defaultPrevented, true);
  assert.equal(text(find(slot, "result-source-title")), "MM-Fit workout");
  assert.notEqual(find(slot, "result-source-edit").getAttribute("open"), null);
});

test("a refused save keeps the form and shows the server sentence", async () => {
  serve("take", "job12345", { source: null, mine: true, licences: LICENCES });
  answers["POST api/me/source/take/job12345"] = { status: 400, body: { ok: false, message: "Use a web address that starts with https://." } };
  const slot = mountSourceCredit("take", "job12345", "result-source");
  await flush();
  find(slot, "result-source-edit").children[1].dispatchEvent(new Event("submit", { cancelable: true }));
  await flush();
  assert.equal(text(find(slot, "result-source-edit-status")), "Use a web address that starts with https://.");
  assert.equal(find(slot, "result-source"), null);
});

test("remove posts an empty body and the credit disappears", async () => {
  serve("entry", "lift", { source: SRC, mine: true, licences: LICENCES });
  answers["POST api/me/source/entry/lift"] = { status: 200, body: { source: null, mine: true } };
  const slot = mountSourceCredit("entry", "lift", "watch-source");
  await flush();
  assert.ok(find(slot, "watch-source"));
  find(slot, "watch-source-edit-remove").click();
  await flush();
  assert.deepEqual(calls.find((c) => c.method === "POST").body, {});
  assert.equal(find(slot, "watch-source"), null);
});

test("no id draws an empty slot and makes no request", () => {
  calls = [];
  const slot = mountSourceCredit("take", "", "result-source");
  assert.equal(slot.children.length, 0);
  assert.equal(calls.length, 0);
});

test("the follow and watch author slot draws the entry credit for reading only, after the author line", async () => {
  const { mountEntryAuthor } = await import("../../web/entry-author.js");
  calls = [];
  answers = {
    "GET api/teacher/lift/author": { status: 200, body: { attribution: { kind: "entry", author: { name: "Tia" }, mine: false } } },
    "GET api/source/entry/lift": { status: 200, body: { source: SRC, mine: true, licences: LICENCES } },
  };
  const slot = mountEntryAuthor("lift", "follow-author", { credit: "follow-source" });
  await flush();
  await flush();
  assert.ok(find(slot, "follow-author") && find(slot, "follow-source"));
  assert.equal(find(slot, "follow-source-edit"), null);
  const order = slot.children.map((c) => c.attrs["data-testid"]);
  assert.ok(order.indexOf("follow-author") < order.indexOf("follow-source-slot"));
  calls = [];
  answers = { "GET api/teacher/lift/author": { status: 404, body: {} } };
  const plain = mountEntryAuthor("lift", "watch-author");
  await flush();
  assert.equal(calls.some((c) => c.url.startsWith("api/source")), false);
  assert.equal(plain.children.length, 0);
});

test("free text sits in bdi so a direction mark cannot reorder the line", () => {
  const block = creditBlock({ title: "T", creator: "C", licence: "Other", licence_label: "My terms", licence_url: "" }, "b");
  assert.equal(find(block, "b-title").tag, "bdi");
  assert.equal(all(find(block, "b-creator")).find((n) => n.tag === "bdi").textContent, "C");
  assert.ok(all(find(block, "b-licence")).some((n) => n.tag === "bdi" && n.textContent === "My terms"));
});

test("the licence dropdown shows the own recording label and the plain names, with the stored value unchanged", async () => {
  serve("entry", "lift", { source: null, mine: true, licences: LICENCES });
  const slot = mountSourceCredit("entry", "lift", "watch-source");
  await flush();
  const options = findAll(slot, "watch-source-edit-licence")[0].children.map((o) => [o.attrs.value, o.textContent]);
  assert.deepEqual(options, [["", "Choose a licence"], ["CC BY 4.0", "CC BY 4.0"], ["Pexels License", "Pexels License"],
    ["own recording", "Own recording (no licence needed)"], ["Other", "Other"]]);
});

test("the trainer's clip credit is led by Trainer's video:", async () => {
  serve("entry", "lift", { source: SRC, mine: false, licences: LICENCES });
  const slot = mountSourceCredit("entry", "lift", "result-entry-source", { edit: false, trainerClip: true });
  await flush();
  assert.equal(text(find(slot, "result-entry-source-lead")), "Trainer's video:");
  serve("entry", "lift", { source: SRC, mine: false, licences: LICENCES });
  const plain = mountSourceCredit("entry", "lift", "watch-source");
  await flush();
  assert.equal(find(plain, "watch-source-lead"), null);
});
