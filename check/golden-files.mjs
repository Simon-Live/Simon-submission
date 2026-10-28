// The golden files the Import drives drop on the Import screen, found through
// fixtures/conformance/formats/cases.json (the one golden suite both readers run). Nothing here guesses
// a file name: a case is chosen by its kind and the format its expected summary names, so a drive
// follows the suite when a golden is renamed. Shared by check/check6-contract.mjs and staging/verify
// (which re-exports it from staging/verify/goldens.mjs). Paths are relative to the repo root.
import fs from 'node:fs';
import path from 'node:path';

const FORMATS_DIR = path.join('fixtures', 'conformance', 'formats');
// A file dropped under its usual name, whatever the golden is called on disk.
export const DROP_NAME = { keyframes: 'keyframes.json', skeleton: 'skeleton.json', animation: 'animation.json' };

export class GoldenMissing extends Error {}

const formatOf = (expect) => {
  if (!expect || typeof expect !== 'object') return null;
  if (typeof expect.format === 'string') return expect.format;
  for (const key of ['summary', 'skeleton', 'animation']) {
    if (expect[key] && typeof expect[key].format === 'string') return expect[key].format;
  }
  return null;
};

// The cases of one formats folder (the folder that holds cases.json): {dir, cases}. `label` is how
// the file is named in a message.
export function loadCasesFrom(dir, label = path.join(dir, 'cases.json')) {
  let parsed;
  try {
    parsed = JSON.parse(fs.readFileSync(path.join(dir, 'cases.json'), 'utf8'));
  } catch (error) {
    throw new GoldenMissing(`cannot read ${label}: ${error.message}`);
  }
  const cases = Array.isArray(parsed) ? parsed : parsed && Array.isArray(parsed.cases) ? parsed.cases : null;
  if (!cases) throw new GoldenMissing(`${label} holds no list of cases`);
  return { dir, cases };
}

export function loadCases(repoRoot) {
  return loadCasesFrom(path.resolve(repoRoot, FORMATS_DIR), path.join(FORMATS_DIR, 'cases.json'));
}

function contentsOf(dir, file) {
  const full = path.resolve(dir, file);
  if (!full.startsWith(`${dir}${path.sep}`)) throw new GoldenMissing(`golden path leaves the formats folder: ${file}`);
  try {
    return fs.readFileSync(full);
  } catch (error) {
    throw new GoldenMissing(`cannot read golden ${file}: ${error.message}`);
  }
}

// The first valid case of `kind` whose expected summary names `format`, as a drop-ready file.
export function goldenFor(set, kind, format) {
  const hit = set.cases.find((c) => c && c.kind === kind && !(c.expect && c.expect.error) && formatOf(c.expect) === format);
  if (!hit) throw new GoldenMissing(`cases.json has no valid ${kind} case for ${format}`);
  return {
    kind, format, source: hit.file, name: DROP_NAME[kind], mimeType: 'application/json', buffer: contentsOf(set.dir, hit.file),
  };
}

// The first error case of `kind` whose message holds `needle`, as a drop-ready file plus the message.
// It is dropped under its own file name: the golden's expected message starts with that name.
export function badGoldenFor(set, kind, needle) {
  const hit = set.cases.find((c) => c && c.kind === kind && c.expect && typeof c.expect.error === 'string' && c.expect.error.includes(needle));
  if (!hit) throw new GoldenMissing(`cases.json has no ${kind} error case holding "${needle}"`);
  return {
    kind, source: hit.file, name: path.basename(hit.file), mimeType: 'application/json', buffer: contentsOf(set.dir, hit.file), error: hit.expect.error,
  };
}

// Part 4's version 1 trio and Part 3's version 1 skeleton, the sets the drives import.
export function part4Trio(set) {
  return [
    goldenFor(set, 'keyframes', 'simon.keyframes.v1'),
    goldenFor(set, 'skeleton', 'simon.skeleton.v1'),
    goldenFor(set, 'animation', 'simon.animation.v1'),
  ];
}

export const skeletonOnly = (set) => goldenFor(set, 'skeleton', 'simon.skeleton/1');
export const unknownVersionAnimation = (set) => badGoldenFor(set, 'animation', 'is not a version Part 6 reads');

// The message without its leading "<file>: ", which depends on the name the file was dropped under.
export const messageBody = (message) => String(message).replace(/^[^:]+: /, '');

// Playwright's setInputFiles payload for a golden.
export const asUpload = (golden) => ({ name: golden.name, mimeType: golden.mimeType, buffer: golden.buffer });
