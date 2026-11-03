// Node tests that read a real part checkout (modules/part-N) skip with a stated reason when it is absent (TICKET-244).
// CI checks out Parts 1 to 6 only when the PARTS_READ_TOKEN secret is set; a clone without submodules has empty folders.
import test from "node:test";
import { existsSync, readdirSync } from "node:fs";

export const PARTS_NOTE =
  "the part repos are not checked out (CI checks out Parts 1 to 6 only when the PARTS_READ_TOKEN secret is set)";

export function partPresent(n) {
  const dir = new URL(`../../modules/part-${n}/`, import.meta.url);
  return existsSync(dir) && readdirSync(dir).length > 0;
}

// `test` when the part is checked out, else a `test` that skips with the reason.
export function partTest(n) {
  if (partPresent(n)) return test;
  const skip = `needs modules/part-${n}: ${PARTS_NOTE}`;
  return (name, fn) => test(name, { skip }, fn);
}

// `test` when the workspace file `rel` (from the repo root) exists, else a `test` that skips naming it. For files
// .simon-publish keeps out of the client repo.
export function fileTest(rel, why) {
  if (existsSync(new URL(`../../${rel}`, import.meta.url))) return test;
  const skip = `reads ${rel}, which is not in this repo: ${why}`;
  return (name, fn) => test(name, { skip }, fn);
}
