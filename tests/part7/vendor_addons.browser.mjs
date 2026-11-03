// docs/specs/vendor-addons.md AC-VA3 and AC-VA4: the vendored GLTFLoader and SkeletonUtils work in a real browser
// against the same `three` the page imports. Run through scripts/with-browser-slot.sh:
//   node tests/part7/vendor_addons.browser.mjs        (SIMON_MODEL_GLB=/path/model.glb adds a real model)
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { serveRoot } from "./serve_static.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const req = createRequire(path.join(process.env.PLAYWRIGHT_DIR || path.resolve(here, "../../node_modules"), "x.js"));
const failures = [];
const check = (ok, what) => { if (!ok) failures.push(what); console.log(`${ok ? "ok  " : "FAIL"} ${what}`); };

/** A one-triangle skinned GLB with two joints, built in memory (nothing to commit). */
function tinySkinnedGlb() {
  const pos = new Float32Array([0, 0, 0, 1, 0, 0, 0, 1, 0]);
  const joints = new Uint8Array([0, 1, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0]);
  const weights = new Float32Array([1, 0, 0, 0, 0.5, 0.5, 0, 0, 1, 0, 0, 0]);
  const ibm = new Float32Array(32);
  for (const o of [0, 16]) { ibm[o] = ibm[o + 5] = ibm[o + 10] = ibm[o + 15] = 1; }
  ibm[13] = -1;  // joint 1 sits at y = 1
  const parts = [pos, joints, weights, ibm].map((a) => Buffer.from(a.buffer));
  const bin = Buffer.concat(parts);
  const offs = []; let o = 0;
  for (const p of parts) { offs.push(o); o += p.length; }
  const json = {
    asset: { version: "2.0" }, scene: 0, scenes: [{ nodes: [0, 2] }],
    nodes: [{ name: "hips", children: [1] }, { name: "spine", translation: [0, 1, 0] }, { mesh: 0, skin: 0 }],
    meshes: [{ primitives: [{ attributes: { POSITION: 0, JOINTS_0: 1, WEIGHTS_0: 2 } }] }],
    skins: [{ joints: [0, 1], inverseBindMatrices: 3 }],
    buffers: [{ byteLength: bin.length }],
    bufferViews: parts.map((p, i) => ({ buffer: 0, byteOffset: offs[i], byteLength: p.length })),
    accessors: [
      { bufferView: 0, componentType: 5126, count: 3, type: "VEC3", min: [0, 0, 0], max: [1, 1, 0] },
      { bufferView: 1, componentType: 5121, count: 3, type: "VEC4" },
      { bufferView: 2, componentType: 5126, count: 3, type: "VEC4" },
      { bufferView: 3, componentType: 5126, count: 2, type: "MAT4" },
    ],
  };
  let j = Buffer.from(JSON.stringify(json));
  j = Buffer.concat([j, Buffer.alloc((4 - (j.length % 4)) % 4, 0x20)]);
  const b = Buffer.concat([bin, Buffer.alloc((4 - (bin.length % 4)) % 4)]);
  const total = 12 + 8 + j.length + 8 + b.length;
  const head = Buffer.alloc(12); head.write("glTF", 0); head.writeUInt32LE(2, 4); head.writeUInt32LE(total, 8);
  const ch = (len, type) => { const h = Buffer.alloc(8); h.writeUInt32LE(len, 0); h.writeUInt32LE(type, 4); return h; };
  return Buffer.concat([head, ch(j.length, 0x4e4f534a), j, ch(b.length, 0x004e4942), b]);
}

const { server, port } = await serveRoot();
const browser = await req("playwright").chromium.launch();
try {
  const page = await browser.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
  const glb = tinySkinnedGlb();
  await page.route("**/__test/tiny.glb", (route) => route.fulfill({ status: 200, contentType: "model/gltf-binary", body: glb }));
  await page.route("**/__test/bad.glb", (route) => route.fulfill({ status: 200, contentType: "model/gltf-binary", body: Buffer.from("not a glb at all") }));
  const real = process.env.SIMON_MODEL_GLB;
  if (real) await page.route("**/__test/real.glb", (route) => route.fulfill({ status: 200, contentType: "model/gltf-binary", body: fs.readFileSync(real) }));
  await page.goto(`http://127.0.0.1:${port}/web/index.html`);

  const run = (url) => page.evaluate(async (u) => {
    const THREE = await import("three");
    const { GLTFLoader } = await import("three/addons/loaders/GLTFLoader.js");
    const SkeletonUtils = await import("three/addons/utils/SkeletonUtils.js");
    const gltf = await new GLTFLoader().loadAsync(u);
    const skinned = [];
    gltf.scene.traverse((o) => { if (o.isSkinnedMesh) skinned.push(o); });
    const copy = skinned.length ? SkeletonUtils.clone(gltf.scene) : null;
    const copies = [];
    if (copy) copy.traverse((o) => { if (o.isSkinnedMesh) copies.push(o); });
    return {
      skinned: skinned.length,
      material: skinned.length ? skinned[0].material instanceof THREE.Material : false,
      bones: skinned.length ? skinned[0].skeleton.bones.length : 0,
      cloneSkinned: copies.length,
      cloneOwnSkeleton: copies.length ? copies[0].skeleton !== skinned[0].skeleton : false,
    };
  }, url);

  const r = await run("/__test/tiny.glb");
  check(r.skinned >= 1, `the loader returns a SkinnedMesh (${r.skinned})`);
  check(r.material === true, "the material is an instance of the page's three Material (one three instance)");
  check(r.bones === 2, `the skeleton has the two joints (${r.bones})`);
  check(r.cloneSkinned === r.skinned && r.cloneOwnSkeleton, "SkeletonUtils.clone gives its own skeleton");

  const bad = await page.evaluate(async () => {
    const { GLTFLoader } = await import("three/addons/loaders/GLTFLoader.js");
    try { await new GLTFLoader().loadAsync("/__test/bad.glb"); return "loaded"; } catch (e) { return "rejected"; }
  });
  check(bad === "rejected", "a file that is not glTF is rejected (negative)");

  if (real) {
    const rr = await run("/__test/real.glb");
    check(rr.skinned >= 1 && rr.material, `the real model ${path.basename(real)} loads (${rr.skinned} skinned, ${rr.bones} bones)`);
  }
  check(errors.length === 0, `no page error (${errors.join(" | ") || "none"})`);
} finally {
  await browser.close();
  server.close();
}
process.exit(failures.length ? 1 : 0);
