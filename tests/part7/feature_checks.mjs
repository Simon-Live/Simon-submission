// Feature check discovery, published with the tests (TICKET-105): staging/feature-checks.mjs re-exports it,
// because staging/ is firm-only and the unit test must run in the published repo. Every
// staging/checks-<lane>.mjs that exists is imported and its runChecks() runs after the M2 journey. A
// module that cannot be imported is a FAIL check named checks-<lane>-import, never a silent skip.
// With no such files nothing runs. Contract: docs/specs/staging.md "Feature checks".
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

const NAME = /^checks-([a-z0-9][a-z0-9-]*)\.mjs$/;

/** Sorted [{lane, file}] for the checks-<lane>.mjs files in dir. */
export function discoverFeatureChecks(dir) {
  return fs.readdirSync(dir).sort().flatMap((f) => {
    const m = NAME.exec(f);
    return m ? [{ lane: m[1], file: path.join(dir, f) }] : [];
  });
}

/** Run every discovered module. ctx: { page, baseUrl, runCheck, entryId, followJobId }. Returns the lanes seen. */
export async function runFeatureChecks(dir, ctx) {
  const lanes = [];
  const found = discoverFeatureChecks(dir);
  if (found.length && !(ctx.entryId && ctx.followJobId)) {
    await ctx.runCheck("feature-checks-journey", async () => {
      throw new Error("the journey produced no finished follow job, so feature checks cannot run");
    });
    return lanes;
  }
  for (const { lane, file } of found) {
    lanes.push(lane);
    let mod = null;
    const imported = await ctx.runCheck(`checks-${lane}-import`, async () => {
      mod = await import(pathToFileURL(file).href);
      if (typeof mod.runChecks !== "function") throw new Error(`${path.basename(file)} does not export runChecks`);
      return "loaded";
    });
    if (!imported) continue;
    try {
      await mod.runChecks(ctx);
    } catch (err) {
      // runChecks records its own failures; a throw that escapes it is still a failed check.
      await ctx.runCheck(`checks-${lane}-run`, async () => { throw err; });
    }
  }
  return lanes;
}
