// Unit tests for the Open-source notices page (model/notices.js, THIRD_PARTY_NOTICES.md) and the whitepaper copy
// (web/whitepaper.html, the design blueprint). `node --test`.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { noticeBlocks } from "../../web/model/notices.js";

const read = (p) => fs.readFileSync(new URL(`../../${p}`, import.meta.url), "utf8");

test("the notices read as headings, tables, licence texts and paragraphs; nothing as HTML", () => {
  const md = "# T\n\nIntro <b>x</b>\nmore\n\n## Shipped\n\n| A | B |\n|---|---|\n| three.js | MIT |\n| Sniglet | OFL |\n\n```\nMIT text\nline 2\n```\n";
  assert.deepEqual(noticeBlocks(md), [
    { kind: "h1", text: "T" },
    { kind: "p", text: "Intro <b>x</b> more" },
    { kind: "h2", text: "Shipped" },
    { kind: "table", head: ["A", "B"], rows: [["three.js", "MIT"], ["Sniglet", "OFL"]] },
    { kind: "code", text: "MIT text\nline 2" },
  ]);
  assert.deepEqual(noticeBlocks(undefined), [], "negative: no notices");
});

test("the build has its notices: every shipped component with its licence, and the texts it ships", () => {
  const md = read("THIRD_PARTY_NOTICES.md");
  for (const name of ["three.js", "Mermaid", "DOMPurify", "lodash-es", "Cytoscape", "Sniglet", "MediaPipe", "idna", "SAM 3.1", "SAM 3D Body", "MHR"]) {
    assert.ok(md.includes(name), name);
  }
  assert.ok(md.includes(read("web/vendor/three/LICENSE").trim()), "three's own licence text");
  assert.ok(md.includes(read("web/vendor/mermaid/LICENSE").trim()), "Mermaid's own licence text");
  const blocks = noticeBlocks(md);
  assert.ok(blocks.filter((b) => b.kind === "table").length >= 4 && blocks.filter((b) => b.kind === "code").length >= 4);
});

test("the whitepaper is the blueprint, with nothing loaded from a third party and no address or key in it", () => {
  const page = read("web/whitepaper.html");
  assert.match(page, /<title>[^<]*Blueprint[^<]*<\/title>/i);
  for (const never of ["fonts.googleapis", "fonts.gstatic", "trycloudflare", "gmail.com", "<script src=\"http"]) assert.ok(!page.includes(never), never);
  assert.ok(!/\b(sk|pk)[-_][A-Za-z0-9]{16,}/.test(page), "negative: nothing that looks like a key");
});
