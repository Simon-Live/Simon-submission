// The redesigned views of the rubric features: teacher, export, voice, second opinion, language picker, narration, plus
// the route, the links and the landing page.   node --test tests/part7/rubric_ui.unit.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { El, installDom, all, find } from "./fake-dom.mjs";

const web = path.join(path.dirname(fileURLToPath(import.meta.url)), "../../web");
const read = (f) => fs.readFileSync(path.join(web, f), "utf8");

installDom();
// the fake DOM lacks classList and SVG elements: add the small part these views use
const cls = (el) => (el.attrs.class || "").split(/\s+/).filter(Boolean);
Object.defineProperty(El.prototype, "classList", {
  get() { return { add: (c) => { this.attrs.class = [...new Set([...cls(this), c])].join(" "); }, contains: (c) => cls(this).includes(c) }; },
});
globalThis.document.createElementNS = (_ns, t) => new El(t);
const hasClass = (el, c) => cls(el).includes(c);
const byClass = (root, c) => all(root).filter((n) => n instanceof El && hasClass(n, c));

const { teacherView } = await import("../../web/model/teacher.js");
const { renderTeacher, renderTeacherError } = await import("../../web/views/teacher.js");
const { startView, busyView, errorView, readyView } = await import("../../web/views/export.js");
const { hearButton, verdictBadge } = await import("../../web/views/voice.js");
const { observationsPanel } = await import("../../web/views/second-opinion.js");
const { langSelect } = await import("../../web/views/lang-picker.js");
const { narrationBox } = await import("../../web/views/narration.js");

const DOC = {
  takes: [{ score: 77, grade: "C", at: "2026-10-31T10:00:00Z", top_cues: ["Keep your chest up"] }, { score: 90, grade: "A", at: "2026-10-31T11:00:00Z", top_cues: [] }],
  cue_counts: [{ text: "Keep your chest up", count: 1 }],
};

test("teacher page: chart with grid, tone-coloured dots, cue rows and take rows carry their classes", () => {
  const screen = new El("section");
  renderTeacher(screen, teacherView(DOC, { name: "Body squat" }, "body-squat"));
  assert.ok(hasClass(screen, "th"));
  assert.equal(byClass(screen, "th-grid").length, 3);
  assert.equal(byClass(screen, "th-dot").length, 2);
  assert.deepEqual(byClass(screen, "th-dot").map((d) => d.attrs["data-tone"]), ["warn", "good"]);
  assert.equal(byClass(screen, "th-line").length, 1);
  assert.equal(byClass(screen, "th-cue").length, 1);
  const takes = byClass(screen, "th-take");
  assert.equal(takes.length, 2);
  assert.ok(takes[0].textContent.includes("90"), "newest first");
});

test("teacher page: no stroke or fill attribute is a colour (colours come from the stylesheet)", () => {
  const screen = new El("section");
  renderTeacher(screen, teacherView(DOC, null, "x"));
  for (const n of all(screen)) if (n instanceof El) for (const k of ["stroke", "fill"]) assert.equal(k in n.attrs, false, `${n.tag} sets ${k}`);
});

test("teacher page: empty state keeps the page class and shows no chart (negative)", () => {
  const screen = new El("section");
  renderTeacher(screen, teacherView({ takes: [], cue_counts: [] }, { name: "Body squat" }, "body-squat"));
  assert.ok(hasClass(screen, "th"));
  assert.ok(find(screen, "teacher-empty"));
  assert.equal(find(screen, "teacher-chart"), null);
  assert.equal(find(screen, "teacher-takes"), null);
});

test("teacher error block: not found and failed load differ", () => {
  const a = new El("section");
  const b = new El("section");
  renderTeacherError(a, true);
  renderTeacherError(b, false);
  assert.match(find(a, "teacher-error").textContent, /not found/);
  assert.match(find(b, "teacher-error").textContent, /did not load/);
});

test("export views: idle, making, ready and failed each carry their class", () => {
  assert.ok(hasClass(startView("Make a clip", () => {}), "ex-start"));
  const busy = busyView("Making your clip");
  assert.ok(hasClass(busy, "ex-busy"));
  assert.equal(byClass(busy, "ex-spin").length, 1);
  const ready = readyView("x.mp4", "Download");
  assert.equal(byClass(ready, "ex-download").length, 1);
  assert.equal(find(ready, "export-download").attrs.href, "x.mp4");
  const failed = errorView("It failed", "Try again", () => {});
  assert.ok(find(failed, "export-error") && hasClass(find(failed, "export-error"), "ex-error"));
  assert.equal(find(failed, "export-video"), null); // negative: a failed export shows no video
});

test("voice views: the verdict says whose opinion it is and the speak button names its moment", () => {
  const box = verdictBadge({ agrees: false, note: "Heels stay down" }, "Llama");
  assert.equal(find(box, "verdict-badge").textContent, "Llama disagrees");
  assert.equal(find(box, "verdict-badge").attrs["data-verdict"], "disagrees");
  assert.match(box.textContent, /model's opinion, not scored/);
  assert.ok(find(box, "verdict-note"));
  assert.equal(find(verdictBadge({ agrees: true }, "Llama"), "verdict-note"), null);
  assert.ok(hasClass(hearButton(0, () => {}), "vx-hear"));
});

test("second opinion view: one row per observation, each labelled as the model's view", () => {
  const seen = [];
  const [title, note, list] = observationsPanel("Llama", [{ at_s: 1.25, text: "Knees cave" }], (t) => seen.push(t));
  assert.match(title.textContent, /A second opinion/);
  assert.match(note.textContent, /does not change your score/);
  assert.equal(byClass(list, "so-row").length, 1);
  assert.match(list.textContent, /model's opinion/);
  find(list, "second-opinion-0").click();
  assert.deepEqual(seen, [1.25]);
});

test("language picker view: a labelled select styled as an input", () => {
  const { box, select } = langSelect([{ code: "en", label: "English" }, { code: "es", label: "Espanol" }], "es", () => {});
  assert.equal(select.value, "es");
  assert.ok(hasClass(select, "input"));
  assert.equal(byClass(box, "lp-label")[0].attrs.for, "sv-lang");
});

test("narration view: one line per cue under a styled box", () => {
  const box = narrationBox("fault-0-narration", [{ at: 0.5, text: "Chest up" }, { at: 1.5, text: "Slow down" }]);
  assert.ok(hasClass(box, "nr"));
  assert.equal(byClass(box, "nr-line").length, 2);
  assert.equal(byClass(box, "nr-line")[1].attrs["data-cue-at-s"], "1.5");
});

test("the new stylesheets are linked after the redesign ones, and each file exists", () => {
  const html = read("index.html");
  let last = html.indexOf("theme/screens.css");
  for (const name of ["voice", "teacher", "export", "narration"]) {
    const at = html.indexOf(`theme/${name}.css`);
    assert.ok(at > last, `${name}.css is linked after the previous sheet`);
    last = at;
    assert.ok(fs.existsSync(path.join(web, "theme", `${name}.css`)));
  }
});

test("the teacher route and the way to it", () => {
  assert.match(read("app.js"), /\^teacher\\\/\(\[\^\/\]\+\)\$\/, \(el, m\) => mountTeacher\(el, m\[1\]\)/);
  assert.match(read("owner-link.js"), /#\/teacher\/\$\{encodeURIComponent\(entryId\)\}`, "Your followers"/); // TICKET-316: drawn by owner-link.js, for the owner only
  assert.match(read("watch.js"), /mountOwnerLink\(eid\)/);
});

test("landing page: muted loop with poster and a pause button, one line, a Try it link to the catalog, no banned words", () => {
  const html = read("landing.html");
  for (const a of ["muted", "loop", "playsinline", 'poster="media/landing-poster.jpg"', 'src="media/landing-loop.mp4"']) assert.ok(html.includes(a), a);
  assert.match(html, /data-testid="landing-pause"/); // LEG-M8: the moving loop can be paused (landing.js)
  assert.match(html, /<a class="ld-try"[^>]*href="\.\/#\/"[^>]*>Try it<\/a>/);
  assert.equal((html.match(/<h1/g) || []).length, 1);
  assert.doesNotMatch(html, /coach|medical|injur|\u2014|\u2013/i);
  assert.doesNotMatch(html, /googleapis|gstatic|preconnect/); // LEG-H2: Inter is served from this site, no font host
  assert.deepEqual(html.match(/<script[^>]*>/g), ['<script type="module" src="landing.js"></script>'.slice(0, -9)]); // only the pause control
  // the client's font handling (ee3990c): theme/fonts.css loads Inter off the render path; the landing page does the same
  const swapped = /<link rel="stylesheet" href="theme\/fonts\.css" media="print" onload="this\.media='all'">/;
  assert.match(html, swapped);
  assert.match(html, /<noscript><link rel="stylesheet" href="theme\/fonts\.css"><\/noscript>/);
  // lane/rubric-54-ui 92fea18: the app page swaps the same font link in, and the font itself is display=swap, so no
  // page waits on the font host for first paint
  assert.match(read("index.html"), swapped);
  assert.match(read("theme/fonts.css"), /font-display: swap/);
  assert.doesNotMatch(read("theme/fonts.css"), /https?:\/\//); // LEG-H2: no outside font host
  assert.doesNotMatch(read("theme/tokens.css"), /@import/); // negative: the tokens import nothing
  assert.doesNotMatch(read("index.html"), /https?:\/\//); // test_web_static: the app page names no outside host
});
