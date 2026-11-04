// TICKET-376: the 3D stick figure hides a joint the camera did not see in that frame, and its bones; hips stay.
// Fixture shaped like take 69842f939ab0 (ankles unseen in every frame, a knee in some). Run through
// scripts/with-browser-slot.sh: node tests/part7/seen-joints.browser.mjs
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";
import { serveRoot } from "./serve_static.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const failures = [];
const check = (ok, what) => { if (!ok) failures.push(what); console.log(`${ok ? "ok  " : "FAIL"} ${what}`); };
const req = createRequire(path.join(process.env.PLAYWRIGHT_DIR || path.resolve(here, "../../node_modules"), "x.js"));
const browser = await req("playwright").chromium.launch({ args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"] });
const { server, port } = await serveRoot();
try {
  const page = await browser.newPage({ viewport: { width: 412, height: 915 } });
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.goto(`http://127.0.0.1:${port}/tests/part7/skin_page.html`);
  await page.waitForFunction(() => window.__ready === true);
  const r = await page.evaluate(async () => {
    const { createStage } = window.__skin;
    const { normalizeReplay, hidesForPicked } = await import("/web/compare.js");
    const joints = ["nose", "left_hip", "right_hip", "left_knee", "right_knee", "left_ankle", "right_ankle"];
    const body = [[0, 0.6, 0], [0.1, 0, 0], [-0.1, 0, 0], [0.1, -0.4, 0], [-0.1, -0.4, 0], [0.1, -0.8, 0], [-0.1, -0.8, 0]];
    const bones = [[1, 2], [1, 3], [3, 5], [2, 4], [4, 6], [0, 1]];
    const n = 4;
    const doc = { fps: 10, joints, bones, expected: [body], follower: Array.from({ length: n }, () => body), exp_to_fol: [0],
      follower_unseen: Array.from({ length: n }, (_, i) => (i === 1 || i === 2 ? [3, 5, 6] : [5, 6])) };
    const model = normalizeReplay(doc);
    const stage = createStage(document.getElementById("host"), { joints: model.joints, bones: model.bones, tracks: [{ color: 0x44aaff }] });
    const out = [];
    for (let i = 0; i < n; i++) {
      stage.setPoses([model.follower[i]], [model.followerUnseen[i]], [hidesForPicked(model, { follower: i })[1]]);
      await new Promise((ok) => requestAnimationFrame(() => requestAnimationFrame(ok)));
      out.push(stage.drawStats()[0]);
    }
    return out;
  });
  // frames 0 and 3: both ankles unseen; frames 1 and 2: the left knee too. 7 joints, 6 bones.
  const want = [{ joints: 5, dimmed: 2, bones: 4 }, { joints: 4, dimmed: 3, bones: 3 }, { joints: 4, dimmed: 3, bones: 3 }, { joints: 5, dimmed: 2, bones: 4 }];
  r.forEach((s, i) => {
    check(s && s.joints === want[i].joints, `frame ${i}: ${want[i].joints} joints drawn (got ${s && s.joints})`);
    check(s && s.dimmed === want[i].dimmed, `frame ${i}: ${want[i].dimmed} unseen joints counted (got ${s && s.dimmed})`);
    check(s && s.bones === want[i].bones, `frame ${i}: ${want[i].bones} bones drawn, hips and upper body kept (got ${s && s.bones})`);
  });
  check(errors.length === 0, `no page error ${errors.join(" | ")}`);
} finally {
  await browser.close();
  server.close();
}
if (failures.length) { console.log(`${failures.length} failed`); process.exit(1); }
