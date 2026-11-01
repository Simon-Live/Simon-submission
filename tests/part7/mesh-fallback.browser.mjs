// TICKET-109 residual 7: web/mesh-demo.html loaded WITHOUT its demo data (as in the published repo) shows the
// fallback sentence and raises no script error. The data request is answered 404 whatever is on disk.
// Run through scripts/with-browser-slot.sh: node tests/part7/mesh-fallback.browser.mjs; exit 1 on a failed check.
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { serveRoot } from "./serve_static.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const req = createRequire(path.join(process.env.PLAYWRIGHT_DIR || path.resolve(here, "../../node_modules"), "x.js"));
const failures = [];
const check = (ok, what) => { if (!ok) failures.push(what); console.log(`${ok ? "ok  " : "FAIL"} ${what}`); };

const { server, port } = await serveRoot();
const browser = await req("playwright").chromium.launch();
try {
  const page = await browser.newPage({ viewport: { width: 412, height: 915 } });
  const errors = [];
  page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
  // The browser's own "Failed to load resource" line for the 404 is not a script error; every other console error is.
  page.on("console", (m) => { if (m.type() === "error" && !m.location().url.endsWith("/mesh-demo/faults.json")) errors.push(m.text()); });
  await page.route("**/mesh-demo/faults.json", (route) => route.fulfill({ status: 404, body: "not found" }));
  await page.goto(`http://127.0.0.1:${port}/web/mesh-demo.html`);
  await page.waitForFunction(() => window.__meshDemo && window.__meshDemo.ready, null, { timeout: 15000 });
  const text = await page.locator('[data-testid="demo-data-missing"]').innerText();
  check(text === "Demo data not included in this repo.", "the fallback sentence is shown");
  check(await page.locator("#stage canvas").count() === 0, "no canvas is drawn (negative)");
  check(errors.length === 0, `no console error (${errors.join(" | ") || "none"})`);
} finally {
  await browser.close();
  server.close();
}
process.exit(failures.length ? 1 : 0);
