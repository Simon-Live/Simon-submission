// Shared harness for the job-page DOM tests: mountJob from web/job.js on the fake DOM, fed one job answer per mount.
import { installDom, El, find } from "./fake-dom.mjs";

installDom();
let answer = {};
globalThis.location = { hash: "" };
globalThis.fetch = async (url) => {
  const body = String(url).includes("api/jobs/") ? answer : {};
  return { ok: true, status: 200, json: async () => body, headers: { get: () => null } };
};
const { mountJob } = await import("../../web/job.js");

export const settle = (ms = 30) => new Promise((r) => setTimeout(r, ms));

/** Serves `job` as the job answer, mounts the page, waits one poll; returns {root, stop, find}. */
export async function mountJobPage(job, { id = "abcdefabcdef", wait = 30 } = {}) {
  answer = { id, ...job };
  const root = new El("div");
  const stop = mountJob(root, id);
  await settle(wait);
  return { root, stop, find: (testid) => find(root, testid) };
}
