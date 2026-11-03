// web/model/qr.js against python-qrcode's matrices and penalties (tests/part7/fixtures/qr/reference.json, made by qr_reference.py) and decoded
// back by the separate reader in qr-decode.mjs (docs/specs/handout.md AC-H2), and against segno's matrices for the AR page's code
// (tests/part7/fixtures/qr-golden.json, heat-and-ar.md AC-A2): the one encoder both use. Run: node --test tests/part7/
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { encodeQr, qrPath, qrSvg, tryQr, versionFor, rsRemainder, penalty, MAX_VERSION, MAX_BYTES, QUIET } from "../../web/model/qr.js";
import { decodeMatrix, matrixFromPath } from "./qr-decode.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const REF = JSON.parse(fs.readFileSync(path.join(here, "fixtures/qr/reference.json"), "utf8"));
const rows = (modules) => modules.map((r) => r.map((d) => (d ? "1" : "0")).join(""));

test("the reference covers every version from 1 to 10", () => {
  assert.deepEqual([...new Set(REF.cases.map((c) => c.version))].sort((a, b) => a - b), [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]);
});

test("every forced mask gives python-qrcode's matrix, module for module", () => {
  for (const c of REF.cases) {
    for (const [mask, expected] of Object.entries(c.masks)) {
      const got = encodeQr(c.text, { mask: Number(mask) });
      assert.equal(got.version, c.version, c.text);
      assert.deepEqual(rows(got.modules), expected, `${c.text} mask ${mask}`);
    }
  }
});

test("penalties equal python-qrcode's lost_point and the lowest one is picked", () => {
  for (const c of REF.cases) {
    const mine = [0, 1, 2, 3, 4, 5, 6, 7].map((k) => penalty(encodeQr(c.text, { mask: k }).modules));
    assert.deepEqual(mine, c.penalties, c.text);
    assert.equal(encodeQr(c.text).mask, mine.indexOf(Math.min(...mine)), c.text);
  }
});

test("each code decodes back to its text, with and without the quiet zone", () => {
  for (const c of REF.cases) {
    const { modules } = encodeQr(c.text);
    assert.equal(decodeMatrix(modules).text, c.text);
    const { d, side } = qrPath(modules);
    assert.equal(decodeMatrix(matrixFromPath(d, side), QUIET).text, c.text);
  }
});

test("a follow link of a movement decodes to that link", () => {
  const link = "http://127.0.0.1:8727/#/follow/body-squat-19b06562";
  const { d, side } = qrPath(encodeQr(link).modules);
  assert.equal(decodeMatrix(matrixFromPath(d, side), QUIET).text, link);
});

test("the reader refuses a damaged code (the check is real)", () => {
  const { modules } = encodeQr(REF.cases[0].text);
  const broken = modules.map((r) => r.slice());
  broken[12][12] = !broken[12][12];
  broken[13][12] = !broken[13][12];
  assert.throws(() => decodeMatrix(broken), /error correction check failed|not byte mode/);
});

test("versions grow with the length and stop at 10", () => {
  assert.equal(versionFor(0), 1);
  assert.equal(versionFor(14), 1);
  assert.equal(versionFor(15), 2);
  assert.equal(versionFor(213), MAX_VERSION);
  assert.equal(versionFor(214), 0);
  assert.throws(() => encodeQr("x".repeat(214)), RangeError);
});

test("Reed-Solomon of the ISO 18004 annex example (version 1-M, HELLO WORLD)", () => {
  const data = [32, 91, 11, 120, 209, 114, 220, 77, 67, 64, 236, 17, 236, 17, 236, 17];
  assert.deepEqual(rsRemainder(data, 10), [196, 35, 39, 119, 235, 215, 231, 226, 93, 23]);
});

test("the path offsets each module by the quiet zone and the square holds it", () => {
  const { d, side } = qrPath([[true, false], [false, true]], 1);
  assert.equal(side, 4);
  assert.equal(d, "M1 1h1v1h-1zM2 2h1v1h-1z");
});

test("penalty counts runs, blocks and balance", () => {
  const allLight = Array.from({ length: 21 }, () => new Array(21).fill(false));
  // runs: 21 rows and 21 columns of 21 (3 + 16 each); blocks: 20 x 20 of 3; balance: 50 % off, 10 steps of 10
  assert.equal(penalty(allLight), 42 * 19 + 400 * 3 + 100);
});

// ---- the AR page's code (TICKET-282): segno's output, `segno.make(text, error="m", mode="byte")`, for fixed strings
const GOLDEN = JSON.parse(fs.readFileSync(path.join(here, "fixtures/qr-golden.json"), "utf8"));

test("with segno's mask the matrix is segno's for every version 1 to 10 (strings that fill the data codewords exactly)", () => {
  assert.deepEqual(GOLDEN.map((g) => g.version), [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]);
  for (const g of GOLDEN) {
    const got = rows(encodeQr(g.text, { mask: g.mask }).modules);
    assert.equal(got.length, 17 + 4 * g.version, `size of version ${g.version}`);
    assert.deepEqual(got, g.rows, `modules of version ${g.version}`);
  }
});

test("the automatic mask is one of the eight valid ones and each segno string decodes back", () => {
  for (const g of GOLDEN) {
    const auto = encodeQr(g.text);
    assert.deepEqual(auto.modules, encodeQr(g.text, { mask: auto.mask }).modules, `version ${g.version}`);
    assert.equal(decodeMatrix(auto.modules).text, g.text);
  }
});

test("the longest string that fits encodes; one byte more gives null from tryQr (negative)", () => {
  assert.ok(tryQr("a".repeat(MAX_BYTES)));
  assert.equal(tryQr("a".repeat(MAX_BYTES + 1)), null);
  assert.equal(versionFor(MAX_BYTES + 1), 0);
});

test("a forced mask changes the modules but not the size", () => {
  const a = encodeQr("https://x.test/r", { mask: 0 }).modules;
  const b = encodeQr("https://x.test/r", { mask: 3 }).modules;
  assert.equal(a.length, b.length);
  assert.notDeepEqual(a, b);
});

test("the svg draws one path inside its viewBox, with no external reference", () => {
  const svg = qrSvg(encodeQr("hi").modules);
  assert.match(svg, /viewBox="0 0 29 29"/);
  assert.equal(svg.match(/<path /g).length, 1);
  assert.doesNotMatch(svg, /https?:\/\/(?!www\.w3\.org)/);
  assert.doesNotMatch(svg, /<image|href=/);
});
