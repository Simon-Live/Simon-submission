// Writes heat.json + heat.bin beside this file in the shape of contract H1 (web/heat/heat-data.js), for the follower
// mesh of web/mesh-demo. It is a fixture in the ticket's shape, not a measurement: the left knee peaks at 3.0 s
// (peak 0.20 m), the right elbow at 1.0 s (0.08 m), the wrists and ankles are masked and hold 0.
//   node tests/part7/fixtures/heat/make-heat.mjs
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const mesh = path.resolve(here, "../../../../web/mesh-demo/follower");
const header = JSON.parse(fs.readFileSync(path.join(mesh, "mesh3d.json"), "utf8"));
const bin = fs.readFileSync(path.join(mesh, header.bin));
const names = header.vertex_joint.names;
const labels = bin.subarray(header.vertex_joint.offset, header.vertex_joint.offset + header.vertex_count);
const MAX_M = 0.25;
const MASKED = ["left_wrist", "right_wrist", "left_ankle", "right_ankle"];
const PEAKS = { left_knee: [3.0, 0.2], right_elbow: [1.0, 0.08], left_hip: [4.5, 0.05] };
const n = header.vertex_count;
const out = Buffer.alloc(header.frames.length * n);
header.frames.forEach((f, k) => {
  const t = f.t_ms / 1000;
  for (let i = 0; i < n; i++) {
    const name = names[labels[i]];
    const peak = PEAKS[name];
    let m = 0.004; // a little error everywhere
    if (peak && !MASKED.includes(name)) m += peak[1] * Math.exp(-(((t - peak[0]) / 0.6) ** 2));
    if (MASKED.includes(name)) m = 0;
    out[k * n + i] = Math.min(255, Math.round((m / MAX_M) * 255));
  }
});
const doc = {
  format: "part7.heat/1", vertex_count: n, max_m: MAX_M, frames: header.frames.map((f) => ({ t_ms: f.t_ms })),
  bin: "heat.bin", bin_bytes: out.length, masked_labels: MASKED,
};
fs.writeFileSync(path.join(here, "heat.bin"), out);
fs.writeFileSync(path.join(here, "heat.json"), `${JSON.stringify(doc)}\n`);
console.log(`heat.json: ${doc.frames.length} frames x ${n} vertices, ${out.length} bytes`);
