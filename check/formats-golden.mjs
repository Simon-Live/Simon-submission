// Golden runner for web/formats.js (docs/specs/formats.md AC-F10).
//
// Runs every case of fixtures/conformance/formats/cases.json against the browser module under node
// and prints one JSON line on stdout: {"cases": n, "passed": n, "failed": [{file, kind, reason}]}.
// It also times the read of a synthetic 1801-frame Part 4 animation (NFR: under 0.5 s) and reports
// it as `read_1801_ms`; a slow read is a failure too. Exit 0 only when nothing failed.
//
// Each golden file is parsed the way the product parses a JSON file: its bytes go to parseStrictJson
// from web/formats.js, the one function web/import.js and web/api.js call too (this runner keeps no
// copy of the parse). A file it refuses gives "<file>: is not valid JSON" with no reader involved
// and no error id.
//
// tests/part6/test_formats.py runs the same cases against part6/formats.py.

import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import * as formats from '../web/formats.js';

const GOLDEN = join(dirname(fileURLToPath(import.meta.url)), '..', 'fixtures', 'conformance', 'formats');
const TOLERANCE = 1e-6;
const ERROR_IDS = ['E1', 'E2', 'E3', 'E4', 'E5', 'E6', 'E7', 'E8', 'E9', 'E9s', 'E10', 'E11', 'E12',
  'E13', 'E14', 'E15', 'E16'];
const MAX_READ_MS = 500;
// The cases the strict parse refuses before any reader runs (they have no error id), sorted by name.
const PARSE_LEVEL = ['invalid-json-bad-utf8.json', 'invalid-json-number-overflow.json'];

// A golden file the strict parse refuses; the message is the product's sentence for it.
class Refused extends Error {}

// A golden file parsed as the Import screen and the player parse a chosen file: its bytes through
// parseStrictJson. Throws Refused("<shown>: is not valid JSON") when it refuses them (AC-F10).
function load(name, shown = name) {
  const parsed = formats.parseStrictJson(readFileSync(join(GOLDEN, name)));
  if (!parsed.ok) throw new Refused(`${shown}: is not valid JSON`);
  return parsed.data;
}
const isPlain = (v) => v !== null && typeof v === 'object' && !Array.isArray(v);

// Null when a equals b (numbers within 1e-6), else a sentence naming the first difference.
function same(a, b, path = 'value') {
  if (typeof a === 'boolean' || typeof b === 'boolean') {
    return a === b ? null : `${path}: ${JSON.stringify(a)} is not ${JSON.stringify(b)}`;
  }
  if (typeof a === 'number' && typeof b === 'number') {
    return Math.abs(a - b) <= TOLERANCE ? null : `${path}: ${a} is not ${b}`;
  }
  if (Array.isArray(a) && Array.isArray(b)) {
    if (a.length !== b.length) return `${path}: length ${a.length} is not ${b.length}`;
    for (let i = 0; i < a.length; i += 1) {
      const diff = same(a[i], b[i], `${path}[${i}]`);
      if (diff) return diff;
    }
    return null;
  }
  if (isPlain(a) && isPlain(b)) {
    const ka = Object.keys(a).sort();
    const kb = Object.keys(b).sort();
    if (ka.join('|') !== kb.join('|')) return `${path}: keys ${ka} are not ${kb}`;
    for (const key of ka) {
      const diff = same(a[key], b[key], `${path}.${key}`);
      if (diff) return diff;
    }
    return null;
  }
  return a === b ? null : `${path}: ${JSON.stringify(a)} is not ${JSON.stringify(b)}`;
}

// What the browser side says about a case: a result, or {error} with the error code (none when the
// strict parse refused the file, because no reader ran).
function outcome(c) {
  const name = c.name || c.file;
  try {
    if (c.kind === 'detect') return { got: { kind: formats.detectKind(load(c.file, name), name) } };
    if (c.kind === 'playable') {
      const anim = c.animation ? formats.readAnimation(load(c.animation), c.animation) : null;
      const skel = c.skeleton ? formats.readSkeleton(load(c.skeleton), c.skeleton) : null;
      return { got: formats.summary(formats.playable(anim, skel)) };
    }
    return { got: formats.summary(formats.read(c.kind, load(c.file, name), name)) };
  } catch (err) {
    if (err instanceof Refused) return { got: { error: err.message } };
    if (err instanceof formats.FormatError) return { got: { error: err.message }, code: err.code };
    throw err;
  }
}

function skeletonAnimation(c) {
  const skeleton = formats.readSkeleton(load(c.file), c.file);
  return formats.summary(formats.animationFromSkeleton(skeleton));
}

function runCase(c) {
  const { got, code } = outcome(c);
  const diff = same(got, c.expect);
  if (diff) return diff;
  if (c.expect.error !== undefined && code !== c.error_id) return `error id ${code} is not ${c.error_id}`;
  if (c.expect_animation) return same(skeletonAnimation(c), c.expect_animation, 'as animation');
  return null;
}

function timeLongRead() {
  const base = Object.fromEntries(formats.JOINTS.map((n) => [n, [0, 0.1, 0.2]]));
  const frames = [];
  for (let i = 0; i < 1801; i += 1) {
    const joints = Object.fromEntries(Object.entries(base).map(([k, v]) => [k, v.slice()]));
    frames.push({ index: i, t: Math.round((i / 30) * 1e6) / 1e6, interpolated: i % 2 === 1, joints });
  }
  const data = { format: 'simon.animation.v1', fps: 30, frames };
  const t0 = performance.now();
  const got = formats.readAnimation(data);
  const ms = performance.now() - t0;
  return { ms, ok: got.frames.length === 1801 };
}

function main() {
  const cases = JSON.parse(readFileSync(join(GOLDEN, 'cases.json'), 'utf8'));
  const failed = [];
  let passed = 0;
  for (const c of cases) {
    let reason;
    try {
      reason = runCase(c);
    } catch (err) {
      reason = `threw ${err && err.stack ? err.stack.split('\n')[0] : err}`;
    }
    if (reason) failed.push({ file: c.file, kind: c.kind, reason });
    else passed += 1;
  }
  const covered = new Set(cases.map((c) => c.error_id).filter(Boolean));
  const missing = ERROR_IDS.filter((id) => !covered.has(id));
  if (missing.length) failed.push({ file: 'cases.json', kind: 'coverage', reason: `no case for ${missing}` });
  const parseLevel = cases.filter((c) => c.expect.error !== undefined && c.error_id === undefined).map((c) => c.file).sort();
  if (parseLevel.join('|') !== PARSE_LEVEL.join('|')) {
    failed.push({ file: 'cases.json', kind: 'coverage', reason: `parse-level cases are [${parseLevel}], not [${PARSE_LEVEL}]` });
  }
  const timing = timeLongRead();
  if (!timing.ok || timing.ms >= MAX_READ_MS) {
    failed.push({ file: '(synthetic 1801 frames)', kind: 'timing', reason: `read took ${timing.ms.toFixed(1)} ms` });
  }
  const line = { cases: cases.length, passed, failed, read_1801_ms: Math.round(timing.ms * 10) / 10 };
  process.stdout.write(`${JSON.stringify(line)}\n`);
  process.exitCode = failed.length === 0 ? 0 : 1;
}

main();
