// TICKET-389: with no example result (prod), the Me page preview still shows the person's figure, posed and draggable.
// Real Chromium (software GL), the real model-preview.js and viewer3d.js, the library rigged figure through the same
// character loader an uploaded GLB uses. Run: PLAYWRIGHT_DIR=<node_modules> scripts/with-browser-slot.sh node tests/part7/model-preview-rest.browser.mjs
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { serveRoot } from "./serve_static.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const req = createRequire(path.join(process.env.PLAYWRIGHT_DIR || path.resolve(here, "../../node_modules"), "x.js"));
const browser = await req("playwright").chromium.launch({ args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"] });
const { server, port } = await serveRoot();
let bad = 0;
const check = (ok, what) => { if (!ok) bad++; console.log(`${ok ? "ok  " : "FAIL"} ${what}`); };
try {
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.goto(`http://127.0.0.1:${port}/tests/part7/skin_page.html`);
  await page.waitForFunction(() => window.__ready === true);
  console.log(`# browser: Chromium ${browser.version()} (playwright, swiftshader software GL)`);
  const out = await page.evaluate(async () => {
    const P = await import("/web/model-preview.js");
    const lib = await (await fetch("/web/models/library/library.json")).json();
    const entry = lib.models.find((m) => m.id === "rigged-figure");
    const host = document.getElementById("host");
    const deps = { ...P.defaultDeps, motion: () => P.loadMotion({ prod: () => true }) };
    const p = P.mountModelPreview(host, deps);
    const ok = await p.ready;
    await p.show("lib:rigged-figure", { ...entry, glb: `/web/${entry.glb}`, manifest: `/web/${entry.manifest}` });
    const box = host.querySelector('[data-testid="my-model-preview"]');
    const stage = host.querySelector('[data-testid="my-model-stage"]');
    const canvas = stage.querySelector("canvas");
    const before = box.getAttribute("data-camera-azimuth");
    const r = canvas.getBoundingClientRect();
    const fire = (type, x) => canvas.dispatchEvent(new PointerEvent(type, { clientX: x, clientY: r.top + r.height / 2, pointerId: 1, bubbles: true, isPrimary: true, button: 0, buttons: 1 }));
    fire("pointerdown", r.left + 50); fire("pointermove", r.left + 150); fire("pointerup", r.left + 150);
    await new Promise((res) => setTimeout(res, 200));
    return {
      ok, hidden: stage.hidden, canvas: Boolean(canvas), w: r.width, h: r.height, shown: box.getAttribute("data-shown"), motion: box.getAttribute("data-motion"),
      status: host.querySelector('[data-testid="my-model-preview-status"]').textContent, playDisabled: host.querySelector('[data-testid="my-model-play"]').disabled,
      before, after: box.getAttribute("data-camera-azimuth"),
    };
  });
  console.log(JSON.stringify(out));
  check(out.ok && !out.hidden && out.canvas && out.w > 100 && out.h > 100, "the stage is shown with a canvas");
  check(out.shown === "lib:rigged-figure" && out.motion === "rest", "the model is on the figure, posed at rest");
  check(out.playDisabled, "negative: Play stays disabled, there is nothing to play");
  check(out.before !== out.after, "a drag turns the figure");
  check(errors.length === 0, `no page error ${errors.join(" | ")}`);
  await page.close();
} finally {
  await browser.close();
  server.close();
}
process.exit(bad ? 1 : 0);
