// TICKET-391: a textured model from `part2 image3d` shows its colours in the viewer, not a flat grey body.
// Real Chromium (software GL), the real model-preview.js, viewer3d.js and character loader. It needs a model folder made
// by the real chain (model.glb + character.json, as Part 7 stores it) and skips when TEXTURED_MODEL_DIR is not set.
// Run: TEXTURED_MODEL_DIR=<folder> [SHOT=<png>] PLAYWRIGHT_DIR=<node_modules> scripts/with-browser-slot.sh node tests/part7/textured-model.browser.mjs
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { serveRoot } from "./serve_static.mjs";

const dir = process.env.TEXTURED_MODEL_DIR;
if (!dir) { console.log("skip: TEXTURED_MODEL_DIR is not set"); process.exit(0); }
const here = path.dirname(fileURLToPath(import.meta.url));
const req = createRequire(path.join(process.env.PLAYWRIGHT_DIR || path.resolve(here, "../../node_modules"), "x.js"));
const browser = await req("playwright").chromium.launch({ args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"] });
const { server, port } = await serveRoot();
let bad = 0;
const check = (ok, what) => { if (!ok) bad++; console.log(`${ok ? "ok  " : "FAIL"} ${what}`); };
// tinted pixels (a spread of 20 or more between the strongest and weakest channel) in the picture, in the page so no image library is needed
const COLOURED = async (page, b64) => page.evaluate(async (data) => {
  const bmp = await createImageBitmap(await (await fetch(`data:image/png;base64,${data}`)).blob());
  const c = new OffscreenCanvas(bmp.width, bmp.height);
  const g = c.getContext("2d");
  g.drawImage(bmp, 0, 0);
  const px = g.getImageData(0, 0, bmp.width, bmp.height).data;
  const hues = new Set();
  let coloured = 0, figure = 0;
  for (let i = 0; i < px.length; i += 4) {
    const [r, gr, b] = [px[i], px[i + 1], px[i + 2]];
    const mx = Math.max(r, gr, b), mn = Math.min(r, gr, b);
    if (mn < 235 && mx - mn >= 20) { coloured++; hues.add(`${r >> 4}.${gr >> 4}.${b >> 4}`); }
    if (mn < 235) figure++;
  }
  return { coloured, figure, buckets: hues.size, w: bmp.width, h: bmp.height };
}, b64);
// the control: the same GLB with its base colour texture taken off the material, a flat grey like the person path's body
function flatGlb(buf) {
  const jsonLen = buf.readUInt32LE(12);
  const doc = JSON.parse(buf.subarray(20, 20 + jsonLen).toString("utf8"));
  for (const m of doc.materials) { delete m.pbrMetallicRoughness.baseColorTexture; m.pbrMetallicRoughness.baseColorFactor = [0.62, 0.62, 0.6, 1]; }
  let json = Buffer.from(JSON.stringify(doc), "utf8");
  json = Buffer.concat([json, Buffer.alloc((4 - (json.length % 4)) % 4, 0x20)]);
  const rest = buf.subarray(20 + jsonLen);
  const head = Buffer.alloc(20);
  head.write("glTF", 0, "ascii"); head.writeUInt32LE(2, 4); head.writeUInt32LE(20 + json.length + rest.length, 8);
  head.writeUInt32LE(json.length, 12); head.write("JSON", 16, "ascii");
  return Buffer.concat([head, json, rest]);
}
try {
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.route("**/__m/*", (route) => {
    const name = new URL(route.request().url()).pathname.split("/").pop();
    if (name === "flat.glb") return route.fulfill({ body: flatGlb(fs.readFileSync(path.join(dir, "model.glb"))), contentType: "model/gltf-binary" });
    const file = path.join(dir, name);
    if (!fs.existsSync(file)) return route.fulfill({ status: 404, body: "no" });
    return route.fulfill({ body: fs.readFileSync(file), contentType: file.endsWith(".json") ? "application/json" : "model/gltf-binary" });
  });
  await page.goto(`http://127.0.0.1:${port}/tests/part7/skin_page.html`);
  await page.waitForFunction(() => window.__ready === true);
  const run = async (entry) => {
    const out = await page.evaluate(async (e) => {
      const P = await import("/web/model-preview.js");
      const host = document.getElementById("host");
      host.replaceChildren();
      const p = P.mountModelPreview(host, { ...P.defaultDeps, motion: () => P.loadMotion({ prod: () => true }) });
      await p.ready;
      await p.show(`m:${e.id}`, e);
      await new Promise((r) => setTimeout(r, 800));
      const box = host.querySelector('[data-testid="my-model-preview"]');
      return { shown: box.getAttribute("data-shown") };
    }, entry);
    const shot = await page.locator('[data-testid="my-model-stage"] canvas').screenshot();
    if (process.env.SHOT) fs.writeFileSync(`${process.env.SHOT}.${entry.id}.png`, shot);
    return { ...out, ...(await COLOURED(page, shot.toString("base64"))) };
  };
  const textured = await run({ id: "textured", name: "Textured", kind: "generated", glb: "/__m/model.glb", manifest: "/__m/character.json" });
  console.log(JSON.stringify(textured));
  const flat = await run({ id: "flat", name: "Flat", kind: "generated", glb: "/__m/flat.glb", manifest: "/__m/character.json" });
  console.log(JSON.stringify(flat));
  const glb = fs.readFileSync(path.join(dir, "model.glb"));
  check(textured.shown === "m:textured", "the model is on the figure");
  check(textured.figure > 500, `something is drawn (${textured.figure} non-background pixels)`);
  // the stage's own grid and shading carry a few tints, so the two renders are compared with each other
  check(textured.buckets >= 20 && textured.buckets >= 2 * flat.buckets,
    `the figure shows the picture's colours (${textured.buckets} colour buckets in the picture)`);
  check(flat.figure > 500 && flat.buckets <= 15, `negative: the same model without its texture reads grey (${flat.buckets} colour buckets)`);
  check(errors.length === 0, `no page error ${errors.join(" | ")}`);
  check(glb.includes(Buffer.from("baseColorTexture")), "the GLB served still names its base colour texture");
  await page.close();
} finally {
  await browser.close();
  server.close();
}
process.exit(bad ? 1 : 0);
