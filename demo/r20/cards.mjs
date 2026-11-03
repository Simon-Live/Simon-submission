// demo/r20/cards.mjs: the release 20 cut's text layers, 1920x1080 transparent PNGs, one or more per scene.
// Usage: node demo/r20/cards.mjs <data.json> <out-dir>
// data.json is written by demo/r20/build.py from the staging job files and the capture's facts, so every number on a
// card comes from a real job or a sourced file. Also writes <out-dir>/cards-text.txt for demo/r20/check.py.
import fs from "node:fs";
import path from "node:path";
import os from "node:os";
import { createRequire } from "node:module";

const d = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const OUT = path.resolve(process.argv[3]);
fs.mkdirSync(OUT, { recursive: true });
const req = createRequire(process.env.PLAYWRIGHT_ROOT || path.join(os.homedir(), "simon-part-7", "package.json"));
const { chromium } = req("playwright");

// The app's own palette (web/theme/tokens.css): black, lime accent, hot pink for faults.
const BG = "#0a0a0a", INK = "#f4f4ef", MUTED = "#a3a39a", LIME = "#d4f25a", PINK = "#ff3ea5";
const css = `
*{box-sizing:border-box;margin:0}
html,body{width:1920px;height:1080px;background:transparent;font-family:Inter,"DejaVu Sans",system-ui,sans-serif;color:${INK}}
.l{position:absolute;left:130px;width:930px}
.kick{font-size:30px;font-weight:800;letter-spacing:3px;text-transform:uppercase;color:${LIME};margin-bottom:22px}
h1{font-size:96px;line-height:1.05;font-weight:800;letter-spacing:-1.5px}
h2{font-size:70px;line-height:1.08;font-weight:800;letter-spacing:-1px}
p{font-size:36px;line-height:1.4;color:${MUTED};margin-top:26px}
.acc{color:${LIME}}
.pink{color:${PINK}}
.src{position:absolute;left:130px;bottom:150px;font-size:24px;color:${MUTED}}
.step{display:flex;align-items:center;gap:26px;margin-top:30px;font-size:40px;font-weight:700}
.step b{display:inline-block;min-width:330px;padding:12px 22px;border-radius:14px;background:#1b2408;border:3px solid ${LIME};color:${LIME};font-size:34px}
.step span{color:${INK}}
.tag{position:absolute;font-size:28px;font-weight:800;padding:10px 20px;border-radius:999px;background:rgba(10,10,10,.82);border:2px solid #333;color:${INK}}
.big{font-size:230px;font-weight:800;line-height:1}
.chip{display:inline-block;font-size:120px;font-weight:800;padding:0 36px;border-radius:26px;border:8px solid ${PINK};color:${PINK};margin-left:34px;vertical-align:top}
.vs{display:flex;gap:60px;margin-top:40px}
.vs div{flex:1;border-radius:24px;background:#141414;border:3px solid #262626;padding:36px}
.vs .n{font-size:84px;white-space:nowrap;font-weight:800;line-height:1.05}
.vs .w{font-size:32px;color:${MUTED};margin-top:12px}
.full{position:absolute;left:0;top:0;width:1920px;height:1080px;background:${BG}}
`;

const src = (t) => `<div class="src">${t}</div>`;
const cards = {
  hook: `<div class="l" style="top:260px"><div class="kick">Between physio visits</div><h1>Your physio can't watch <span class="acc">every rep.</span></h1></div>
    ${src(`Stock clip: Pexels ${d.hook_clip}.`)}`,
  teacher: `<div class="l" style="top:110px"><div class="kick">The recording</div><h2>Recorded once, <span class="acc">the reference in 3D.</span></h2></div>
    <div class="tag" style="left:150px;top:420px">The recording</div>
    <div class="src" style="top:330px;bottom:auto">Stock clip: Pexels ${d.trainer_clip}.</div>`,
  follow: `<div class="l" style="top:100px"><div class="kick">At home</div><h2>Follow it <span class="acc">side by side.</span></h2>
    <p style="font-size:30px;margin-top:14px">Live check runs on the phone and marks the joints that drift.</p></div>
    ${src(`The camera here plays stock clip Pexels ${d.follower_clip}.`)}`,
  "wait-0": `<div class="l" style="top:150px"><div class="kick">On the server</div><h2>Meta's models <span class="acc">go to work.</span></h2></div>
    ${src(`Measured from the take's log: ${d.take_total_s} s in all, shown ${d.take_speed} times faster.`)}`,
  "wait-1": `<div class="l" style="top:470px"><div class="step"><b>SAM 3.1</b><span>finds the student</span></div></div>`,
  "wait-2": `<div class="l" style="top:580px"><div class="step"><b>SAM 3D Body</b><span>3D in every frame</span></div></div>`,
  "wait-3": `<div class="l" style="top:690px"><div class="step"><b>Muse Spark</b><span>the feedback in words</span></div></div>`,
  result: `<div class="l" style="top:100px;width:1050px"><div class="kick">The result</div>
    <div style="display:flex;align-items:center;gap:36px"><span class="chip" style="margin-left:0;font-size:84px;padding:0 24px">${d.hero_grade}</span>
    <p style="font-size:40px;color:${INK};margin-top:0">${d.hero_figures}<br><span style="font-size:32px">At ${d.cue_at} s: <span class="acc">${d.cue}</span></span></p></div>
    <p style="font-size:22px;margin-top:10px">Student: Pexels ${d.follower_clip}. Recording: Pexels ${d.trainer_clip}. Two different people, Pexels License.</p></div>`,
  opinion: `<div class="l" style="top:100px;width:1050px"><div class="kick">Fix it for me</div><h2>Your body, <span class="acc">moved to the recorded pose.</span></h2>
    <p style="font-size:28px;margin-top:12px">Muse Spark's second opinion: it ${d.verdict_word}. The score does not change.</p></div>`,
  models: `<div class="l" style="top:100px;width:1050px"><div class="kick">How this was made</div><h2 style="font-size:60px">Which Meta model ran, <span class="acc">and whether it ran live.</span></h2>
    <p style="font-size:24px;margin-top:10px">The app's own card for this take.</p></div>`,
  picture: `<div class="l" style="top:90px"><div class="kick">One picture</div><h2>A character becomes <span class="acc">a rigged model.</span></h2>
    <p style="font-size:32px">${d.picture_chain}</p></div>
    ${d.picture_img ? `<img src="${d.picture_img}" style="position:absolute;left:130px;top:550px;height:330px;border-radius:14px;border:4px solid #3a3a3a">
    <div class="abs" style="position:absolute;left:${130 + 20}px;top:900px;font-size:24px;color:${MUTED}">The picture that went in</div>` : ""}
    <div class="src" style="top:485px;bottom:auto;width:900px">${d.picture_credit}</div>`,
  anybody: `<div class="l" style="top:300px;width:400px"><div class="kick">Any body</div><h2 style="font-size:58px">One take on <span class="acc">several bodies</span> at once.</h2></div>`,
  privacy: `<div class="l" style="top:240px"><div class="kick">Privacy</div><h2>You <span class="acc">stay in control.</span></h2>
    <p>Consent before every take. Keep only the 3D model. Delete any take.</p></div>`,
  cost: `<div class="full"></div><div class="l" style="top:180px;width:1660px"><div class="kick">Cost</div><h2>One take, set beside one hour.</h2>
    <div class="vs"><div><div class="n acc">about ${d.cost_cents} cents</div><div class="w">API spend per take on staging, an upper bound (${d.cost_takes} takes)</div></div>
    <div><div class="n">$${d.trainer_low} to $${d.trainer_high}</div><div class="w">a typical hour with a personal trainer (GoodRx)</div></div></div></div>
    ${src("Sources in demo/README.md: tools/cost_per_take.py output of 2026-11-02, and docs/submission.md.")}`,
  end: `<div class="full"></div><div class="l" style="top:150px;width:1000px"><h1 style="font-size:150px">simon</h1>
    <p style="color:${INK};font-size:48px">Learn any movement from one recording.</p>
    <p style="margin-top:60px">Code: <span style="color:${INK}">${d.repo}</span></p>
    <p style="margin-top:12px">${d.live_line}</p>
    <p style="margin-top:60px;font-size:26px">Built on Meta's SAM 3.1, SAM 3D Body and Muse Spark. Filmed on release ${d.sha_short}. ${d.credits}</p></div>
    ${d.footer_img ? `<img src="${d.footer_img}" style="position:absolute;left:1220px;top:300px;width:560px;border-radius:12px;border:3px solid #3a3a3a">
    <div style="position:absolute;left:1220px;top:670px;font-size:24px;color:${MUTED}">The app's version footer</div>` : ""}`,
};

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
let text = "";
for (const [name, html] of Object.entries(cards)) {
  await page.setContent(`<style>${css}</style><body>${html}</body>`);
  for (let attempt = 1; ; attempt++) {
    try { await page.screenshot({ path: path.join(OUT, `card-${name}.png`), omitBackground: true }); break; }
    catch (e) { if (attempt >= 4) throw e; await page.waitForTimeout(500); }
  }
  text += `## ${name}\n${await page.evaluate(() => document.body.innerText)}\n`;
}
await browser.close();
fs.writeFileSync(path.join(OUT, "cards-text.txt"), text);
console.log("cards:", Object.keys(cards).join(","));
