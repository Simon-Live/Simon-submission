// demo/r20/rec.mjs: crisp screen recording of one Playwright page through the Chrome DevTools screencast.
// Playwright's recordVideo writes the CSS-pixel viewport (412x915), too soft for a phone at two thirds of a 1080p
// frame; the screencast hands over device pixels (deviceScaleFactor 2). Frames arrive only when the page paints, so
// each frame is stored with its timestamp and stitched to constant frame rate by ffmpeg's concat demuxer.
import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";

/** Start recording `page` into `<dir>/<name>`; returns { mark(label), stop() -> {file, marks} }. */
export async function record(page, dir, name, { width, height, fps = 30 } = {}) {
  const fdir = path.join(dir, `frames-${name}`);
  fs.rmSync(fdir, { recursive: true, force: true });
  fs.mkdirSync(fdir, { recursive: true });
  const cdp = await page.context().newCDPSession(page);
  const frames = [];
  const t0 = Date.now() / 1000;
  const marks = {};
  cdp.on("Page.screencastFrame", async (f) => {
    const file = path.join(fdir, `${String(frames.length).padStart(6, "0")}.jpg`);
    fs.writeFileSync(file, Buffer.from(f.data, "base64"));
    frames.push({ file, t: f.metadata.timestamp });
    try { await cdp.send("Page.screencastFrameAck", { sessionId: f.sessionId }); } catch { /* page closing */ }
  });
  await cdp.send("Page.startScreencast", { format: "jpeg", quality: 90, maxWidth: width, maxHeight: height, everyNthFrame: 1 });
  return {
    mark(label) { marks[label] = Date.now() / 1000 - t0; },
    async stop() {
      const end = Date.now() / 1000;
      try { await cdp.send("Page.stopScreencast"); } catch { /* closed */ }
      await new Promise((r) => setTimeout(r, 300));
      if (!frames.length) throw new Error(`no frames recorded for ${name}`);
      // the screencast clock and Date.now() share the epoch; shift marks onto the first frame
      const first = frames[0].t;
      const shift = first - t0;
      for (const k of Object.keys(marks)) marks[k] = Math.max(0, marks[k] - shift);
      marks.end = end - first;
      const list = frames.map((f, i) => {
        const next = i + 1 < frames.length ? frames[i + 1].t : end;
        return `file '${f.file}'\nduration ${Math.max(0.001, next - f.t).toFixed(4)}\n`;
      }).join("") + `file '${frames.at(-1).file}'\n`;
      const lf = path.join(dir, `frames-${name}.txt`);
      fs.writeFileSync(lf, list);
      const out = path.join(dir, `ui-${name}.mp4`);
      const r = spawnSync("ffmpeg", ["-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", lf,
        "-vf", `fps=${fps},scale=trunc(iw/2)*2:trunc(ih/2)*2,format=yuv420p`, "-c:v", "libx264", "-preset", "fast", "-crf", "16", out]);
      if (r.status) throw new Error(`ffmpeg failed for ${name}: ${r.stderr}`);
      fs.rmSync(fdir, { recursive: true, force: true });
      fs.rmSync(lf, { force: true });
      return { file: out, marks };
    },
  };
}
