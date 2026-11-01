// demo/cards.mjs: render the video's title cards, labels and the pipeline diagram to 1920x1080 PNG layers.
// Usage: node demo/cards.mjs <data.json> <out-dir>
// data.json is written by demo/build.py from job.json and analysis.json, so every number on a card comes from the
// real job. Also writes <out-dir>/cards-text.txt (all on-screen card text, for the number check).
import fs from "node:fs";
import path from "node:path";
import os from "node:os";
import { createRequire } from "node:module";

const data = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const OUT = path.resolve(process.argv[3]);
fs.mkdirSync(OUT, { recursive: true });
const req = createRequire(process.env.PLAYWRIGHT_ROOT || path.join(os.homedir(), "simon-part-7", "package.json"));
const { chromium } = req("playwright");

// Palette from upstream/ui-redesign:web/theme/tokens.css (black, grey-900/850/800, white, grey-500, lime, amber).
// BLUE and TEAL are the 3D legend (teacher, you) of the current UI; re-check them after ui-redesign lands.
const BG = "#0a0a0a", INK = "#f4f4ef", MUTED = "#9a9a92", BLUE = "#7aa2ff", TEAL = "#3ddc97", GREEN = "#c6f35a", AMBER = "#ffc83d";
const SURFACE = "#141414", RAISED = "#1c1c1c", LINE = "#262626";
const css = `
*{box-sizing:border-box;margin:0}
html,body{width:1920px;height:1080px;background:transparent;font-family:Inter,"DejaVu Sans",system-ui,sans-serif;color:${INK}}
.abs{position:absolute}
h1{font-size:92px;line-height:1.08;font-weight:800;letter-spacing:-1px}
h2{font-size:64px;line-height:1.12;font-weight:800}
p{font-size:38px;line-height:1.35;color:${MUTED}}
.tag{display:inline-block;font-size:30px;font-weight:700;padding:10px 22px;border-radius:999px;background:${RAISED};border:2px solid ${LINE};color:${INK};margin-right:14px}
.label{position:absolute;font-size:34px;font-weight:700;padding:12px 22px;border-radius:12px;background:rgba(11,16,32,.86);color:${INK}}
.big{font-size:220px;font-weight:800;line-height:1}
.chip{display:inline-block;font-size:110px;font-weight:800;padding:0 34px;border-radius:24px;border:8px solid ${AMBER};color:${AMBER};margin-left:30px;vertical-align:top}
.box{position:absolute;width:380px;height:150px;border-radius:20px;background:${SURFACE};border:3px solid ${LINE};padding:22px 24px;font-size:34px;font-weight:700;display:flex;flex-direction:column;justify-content:center}
.box small{font-size:24px;font-weight:400;color:${MUTED};margin-top:6px}
.box.meta{background:#1c2410;border-color:${GREEN}}
.arrow{position:absolute;font-size:64px;color:${GREEN}}
.stage{position:absolute;left:120px;width:760px;height:112px;border-radius:18px;background:${SURFACE};border:3px solid ${LINE};padding:20px 26px;font-size:34px;font-weight:700;display:flex;justify-content:space-between;align-items:center}
.stage b{white-space:nowrap;color:${GREEN};font-size:40px}
`;

const cards = {
  hook: `<div class="abs" style="left:900px;top:300px;width:900px"><h1>Learn any movement from <span style="color:${GREEN}">one recording.</span></h1>
    <p style="margin-top:36px">A teacher records it once. Anyone can follow it and see, in 3D, where their copy differs.</p></div>`,
  problem: `<div class="abs" style="left:1090px;top:330px;width:740px"><h2>You follow a video.</h2>
    <h2 style="color:${AMBER};margin-top:30px">Nobody tells you what your copy got wrong.</h2></div>`,
  teacher: `<div class="label" style="left:110px;top:150px">The teacher's recording</div>
    <div class="label" style="left:110px;top:905px;background:transparent;font-size:44px;width:1100px;padding:0">Recorded once. <span style="color:${GREEN}">It joins the catalog.</span></div>`,
  watch3d: `<div class="abs" style="left:110px;top:300px;width:1000px"><h2>Open it.</h2><h2 style="color:${GREEN};margin-top:20px">Turn it to any angle.</h2>
    <p style="margin-top:34px">Front, side and top, in 3D, from one phone video.</p></div>`,
  follow: `<div class="abs" style="left:110px;top:70px;width:1000px"><h2>Anyone follows it.</h2>
    <p style="margin-top:30px">Filmed on a phone. This take is the one behind job ${data.job}.</p></div>`,
  wait: `<div class="abs" style="left:120px;top:90px;width:820px"><h2>Analysing on the GPU</h2><p style="margin-top:8px">Job ${data.job}, measured from its log. Shown sped up.</p></div>
    <div class="stage" style="top:300px"><span>Upload</span><b>${data.stage.upload} s</b></div>
    <div class="stage" style="top:430px;border-color:${GREEN}"><span>Pose (SAM 3D Body)</span><b>${data.stage.pose} s</b></div>
    <div class="stage" style="top:560px"><span>Skeleton</span><b>${data.stage.skeleton} s</b></div>
    <div class="stage" style="top:690px"><span>Compare and phrase</span><b>${data.stage.analyse} s</b></div>
    <div class="abs" style="left:120px;top:850px;font-size:44px;color:${MUTED}">Total ${data.total_s} s, ${data.total_mmss}.</div>`,
  reveal: `<div class="abs" style="left:110px;top:300px;width:1000px"><div class="big">${data.score}<span style="font-size:80px;color:${MUTED}">/100</span><span class="chip">${data.grade}</span></div>
    <p style="margin-top:44px;font-size:46px">Where the copy differs, in 3D.</p></div>`,
  tap: `<div class="abs" style="left:110px;top:290px;width:1000px"><p style="font-size:40px">At ${data.at_s} s</p><h2 style="color:${GREEN}">${data.cue}</h2>
    <p style="margin-top:34px">Tap a moment to jump there. Tap Hear this line to listen to the cue.</p></div>`,
  mesh: `<div class="abs" style="left:110px;top:250px;width:540px"><h2 style="font-size:50px">SAM 3D Body: full body meshes, trainer and you</h2>
    <p style="margin-top:30px;font-size:30px">The faulty limb turns red at the time Simon measured it.</p>
    <p style="margin-top:24px;font-size:26px;color:${AMBER}">A demo page on two stock clips. In the app, a result shows this view when its job has meshes.</p></div>`,
  share: `<div class="abs" style="left:110px;top:300px;width:1000px"><h2>Share a clip.</h2>
    <p style="margin-top:30px">And see which Meta model made each step: SAM 3.1, SAM 3D Body and Muse Spark, with the time each took.</p></div>`,
  compare: `<div class="abs" style="left:110px;top:300px;width:1000px"><h2>Your copy, over the teacher's.</h2>
    <p style="margin-top:30px"><b style="color:${INK}">White</b> is the teacher. <b style="color:${GREEN}">Lime</b> is you.</p></div>`,
  shape: `<div class="abs" style="left:110px;top:300px;width:1000px"><h2>Shape or timing?</h2>
    <p style="margin-top:30px">Simon splits the two, and replays the worst moment on a loop.</p></div>`,
  close: `<div class="abs" style="left:110px;top:70px;width:1500px"><div><span class="tag">Dance</span><span class="tag">Rehab</span><span class="tag">Fitness</span></div>
    <h2 style="margin-top:30px">One capability.<br><span style="color:${GREEN}">Any movement a teacher can show.</span></h2></div>`,
  tech: `<div class="abs" style="left:0;top:0;width:1920px;height:1080px;background:${BG}"></div>
    <div class="abs" style="left:120px;top:70px"><h2>One pipeline, built on Meta models</h2></div>
    <div class="box" style="left:120px;top:260px">Video in</div>
    <div class="arrow" style="left:525px;top:290px">&#8594;</div>
    <div class="box meta" style="left:610px;top:260px">SAM 3.1 tracking<small>Meta Model API</small></div>
    <div class="arrow" style="left:1015px;top:290px">&#8594;</div>
    <div class="box meta" style="left:1100px;top:260px">Muse Spark 1.3<small>sections of the movement</small></div>
    <div class="arrow" style="left:1505px;top:290px">&#8594;</div>
    <div class="box meta" style="left:1590px;top:260px;width:230px;font-size:30px">SAM 3D Body<small>pose, on the GPU</small></div>
    <div class="box" style="left:120px;top:560px">Skeleton</div>
    <div class="arrow" style="left:525px;top:590px">&#8594;</div>
    <div class="box" style="left:610px;top:560px">Compare</div>
    <div class="arrow" style="left:1015px;top:590px">&#8594;</div>
    <div class="box meta" style="left:1100px;top:560px">Muse Spark<small>plain-words phrasing</small></div>
    <div class="arrow" style="left:1505px;top:590px">&#8594;</div>
    <div class="box" style="left:1590px;top:560px;width:230px;border-color:${GREEN}">Score</div>
    <div class="abs" style="left:120px;top:830px;width:1700px"><p>Lime boxes are Meta models. SAM 3D Body uses DINOv3. The server itself runs on plain Python.</p></div>`,
  end: `<div class="abs" style="left:0;top:0;width:1920px;height:1080px;background:${BG}"></div>
    <div class="abs" style="left:120px;top:70px;width:1680px"><h1 style="font-size:100px">Simon</h1>
    <p style="margin-top:12px;color:${INK};font-size:44px">Built on Meta's SAM 3.1, SAM 3D Body (DINOv3) and Muse Spark.</p></div>
    <div class="abs" style="left:120px;top:330px;width:1680px;font-size:33px;line-height:1.5;color:${MUTED}">
      <p style="font-size:33px"><b style="color:${INK}">Before the window:</b> the idea and the event entry. No code: every Simon repository has its first commit on ${data.window_start}.</p>
      <p style="font-size:33px;margin-top:18px"><b style="color:${INK}">Built in the window:</b> the seven parts, from keyframes to this app, in ${data.repos} repositories.</p>
      <p style="font-size:33px;margin-top:18px"><b style="color:${INK}">Footage:</b> one real take, cleared for this video (job ${data.job}), plus Pexels stock clips.</p>
      <p style="font-size:33px;margin-top:18px"><b style="color:${INK}">Clips:</b> Pexels License, ids ${data.pexels.join(", ")}; authors not stated on the pages. Details in demo/README.md.</p></div>`,
};

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
let text = "";
for (const [name, html] of Object.entries(cards)) {
  await page.setContent(`<style>${css}</style><body>${html}</body>`);
  for (let attempt = 1; ; attempt++) {  // headless screenshots fail now and then on a busy host
    try { await page.screenshot({ path: path.join(OUT, `card-${name}.png`), omitBackground: true }); break; }
    catch (e) { if (attempt >= 4) throw e; await page.waitForTimeout(500); }
  }
  text += `## ${name}\n${await page.evaluate(() => document.body.innerText)}\n`;
}
await browser.close();
fs.writeFileSync(path.join(OUT, "cards-text.txt"), text);
console.log("cards:", Object.keys(cards).join(","));
