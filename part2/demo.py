"""Demos (#16).

  part2 demo viewer  --run out/clip [--id 0]   -> out/clip/viewer.html
      each frame beside its rotatable 3D skeleton (canonical frame); drag to rotate,
      slider/arrow keys to scrub. Self-contained page; frames are loaded from ./frames/.
  part2 demo overlay --run out/clip            -> out/clip/overlay.mp4
      every person's skeleton projected onto the video, one stable colour per id.

--run is a `part2 run` output dir: frames/ (+ frames.json), pose3d.json, camera.json.
"""
import json
import subprocess
import tempfile
from pathlib import Path

from part2 import frames as frames_mod
from part2.canonical import project_pose3d
from part2.joints import BONES, CANONICAL

# Okabe-Ito-like palette, distinguishable for common colour-vision deficiencies.
COLORS = ["#E69F00", "#56B4E9", "#009E73", "#F0E442", "#0072B2", "#D55E00", "#CC79A7", "#999999",
          "#7F3C8D", "#11A579", "#3969AC", "#F2B701"]


def color_for(pid) -> str:
    return COLORS[(int(pid) if str(pid).lstrip("-").isdigit() else abs(hash(pid))) % len(COLORS)]


def _load(run: Path):
    return (frames_mod.load(run / "frames"), json.loads((run / "pose3d.json").read_text()),
            json.loads((run / "camera.json").read_text()))


def viewer(run, person_id=None, out=None) -> Path:
    run = Path(run)
    recs, pose3d, _ = _load(run)
    files = {r["frame"]: r["file"] for r in recs}
    ids = sorted({p["id"] for f in pose3d["frames"] for p in f["people"]}, key=str)
    if not ids:
        raise ValueError(f"{run / 'pose3d.json'} has no people")
    pid = ids[0] if person_id is None else type(ids[0])(person_id)
    seq = []
    for f in pose3d["frames"]:
        p = next((p for p in f["people"] if p["id"] == pid), None)
        seq.append({"frame": f["frame"], "t_ms": f["t_ms"], "file": f"frames/{files[f['frame']]}",
                    "joints": None if p is None else [[p["joints"][j][k] for k in "xyz"] for j in CANONICAL]})
    data = {"id": pid, "color": color_for(pid), "joints": CANONICAL,
            "bones": [[CANONICAL.index(a), CANONICAL.index(b)] for a, b in BONES], "frames": seq}
    html = VIEWER_HTML.replace("__DATA__", json.dumps(data))
    out = Path(out) if out else run / "viewer.html"
    out.write_text(html)
    return out


def overlay(run, out=None, fps=None) -> Path:
    """Draw projected skeletons on every frame and encode an mp4 (needs Pillow + ffmpeg)."""
    from PIL import Image, ImageDraw

    run = Path(run)
    recs, pose3d, camera = _load(run)
    uv = project_pose3d(pose3d, camera)
    if fps is None:
        dt = [b["t_ms"] - a["t_ms"] for a, b in zip(recs, recs[1:])]
        fps = 1000 / (sorted(dt)[len(dt) // 2]) if dt else 1
    out = Path(out) if out else run / "overlay.mp4"
    with tempfile.TemporaryDirectory() as tmp:
        for i, r in enumerate(recs):
            im = Image.open(run / "frames" / r["file"]).convert("RGB")
            d = ImageDraw.Draw(im)
            w = max(2, im.width // 300)
            for (frame, pid), pts in uv.items():
                if frame != r["frame"]:
                    continue
                c = color_for(pid)
                for a, b in BONES:
                    d.line([tuple(pts[a]), tuple(pts[b])], fill=c, width=w)
                for j in CANONICAL:
                    x, y = pts[j]
                    d.ellipse([x - w * 1.5, y - w * 1.5, x + w * 1.5, y + w * 1.5], fill=c)
                x, y = pts["nose"]
                d.text((x + 3 * w, y - 8 * w), f"id {pid}", fill=c)
            im.save(Path(tmp) / f"{i:06d}.png")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-framerate", f"{fps:.3f}", "-i", str(Path(tmp) / "%06d.png"),
                        "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2", "-pix_fmt", "yuv420p", "-c:v", "libx264", str(out)],
                       check=True, capture_output=True)
    return out


VIEWER_HTML = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>Simon Part 2 — 3D skeleton</title>
<style>
  :root { color-scheme: light dark; }
  body { margin: 0; font: 14px/1.4 system-ui, sans-serif; display: flex; flex-direction: column; height: 100vh; }
  main { flex: 1; display: grid; grid-template-columns: 1fr 1fr; gap: 8px; padding: 8px; min-height: 0; }
  .pane { position: relative; background: #1112; border-radius: 6px; overflow: hidden; }
  .pane img, .pane canvas { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: contain; }
  canvas { cursor: grab; } canvas:active { cursor: grabbing; }
  .label { position: absolute; left: 8px; top: 6px; font-size: 12px; opacity: .7; }
  footer { display: flex; gap: 12px; align-items: center; padding: 6px 12px 10px; }
  input[type=range] { flex: 1; }
</style></head>
<body>
<main>
  <div class="pane"><img id="img" alt="video frame"><span class="label">video frame</span></div>
  <div class="pane"><canvas id="cv"></canvas><span class="label">3D skeleton (canonical frame) · drag to rotate · scroll to zoom</span></div>
</main>
<footer><button id="play">▶</button><input id="slider" type="range" min="0" value="0"><span id="info"></span></footer>
<script>
const D = __DATA__;
const cv = document.getElementById('cv'), ctx = cv.getContext('2d'), img = document.getElementById('img');
const slider = document.getElementById('slider'), info = document.getElementById('info');
slider.max = D.frames.length - 1;
let k = 0, yaw = 0.6, pitch = 0.25, zoom = 1, timer = null, drag = null;
const side = j => j.startsWith('left') ? 'L' : j.startsWith('right') ? 'R' : 'C';

function project(p) {           // canonical (x left, y up, z anterior) -> screen; camera orbits the subject
  const [x, y, z] = p, cy = Math.cos(yaw), sy = Math.sin(yaw), cp = Math.cos(pitch), sp = Math.sin(pitch);
  const x1 = x * cy + z * sy, z1 = -x * sy + z * cy;        // yaw 0: viewer in front, subject's left on screen right
  const y2 = y * cp - z1 * sp, z2 = y * sp + z1 * cp;
  const s = Math.min(cv.width, cv.height) * 0.38 * zoom;
  return [cv.width / 2 + x1 * s, cv.height * 0.55 - y2 * s, z2];
}
function draw() {
  const r = cv.getBoundingClientRect();
  cv.width = r.width * devicePixelRatio; cv.height = r.height * devicePixelRatio;
  ctx.clearRect(0, 0, cv.width, cv.height);
  const f = D.frames[k];
  img.src = f.file;
  info.textContent = `frame ${f.frame} · ${(f.t_ms / 1000).toFixed(2)} s · person ${D.id}` + (f.joints ? '' : ' · not detected');
  // floor grid at the ankles' height
  ctx.strokeStyle = '#8884'; ctx.lineWidth = devicePixelRatio;
  const floor = f.joints ? Math.min(...f.joints.map(p => p[1])) : -0.9;
  for (let g = -1; g <= 1.001; g += 0.25) {
    for (const [a, b] of [[[g, floor, -1], [g, floor, 1]], [[-1, floor, g], [1, floor, g]]]) {
      const pa = project(a), pb = project(b); ctx.beginPath(); ctx.moveTo(pa[0], pa[1]); ctx.lineTo(pb[0], pb[1]); ctx.stroke();
    }
  }
  // axes at the hip midpoint: x (subject's left), y (up), z (anterior)
  for (const [v, c, n] of [[[0.3, 0, 0], '#d33', 'x left'], [[0, 0.3, 0], '#3a3', 'y up'], [[0, 0, 0.3], '#36d', 'z front']]) {
    const o = project([0, 0, 0]), e = project(v);
    ctx.strokeStyle = ctx.fillStyle = c; ctx.lineWidth = 2 * devicePixelRatio;
    ctx.beginPath(); ctx.moveTo(o[0], o[1]); ctx.lineTo(e[0], e[1]); ctx.stroke();
    ctx.font = `${11 * devicePixelRatio}px system-ui`; ctx.fillText(n, e[0] + 4, e[1]);
  }
  if (!f.joints) return;
  const P = f.joints.map(project);
  const bones = D.bones.map(([a, b]) => [a, b, (P[a][2] + P[b][2]) / 2]).sort((u, v) => u[2] - v[2]);
  ctx.lineCap = 'round';
  for (const [a, b] of bones) {
    const sa = side(D.joints[a]), sb = side(D.joints[b]);
    ctx.strokeStyle = sa === 'L' || sb === 'L' ? D.color : sa === 'R' || sb === 'R' ? shade(D.color) : '#bbb';
    ctx.lineWidth = 5 * devicePixelRatio;
    ctx.beginPath(); ctx.moveTo(P[a][0], P[a][1]); ctx.lineTo(P[b][0], P[b][1]); ctx.stroke();
  }
  ctx.fillStyle = '#fff';
  for (const p of P) { ctx.beginPath(); ctx.arc(p[0], p[1], 3.5 * devicePixelRatio, 0, 7); ctx.fill(); }
}
function shade(hex) {           // darker tone of the person colour for the right side
  const n = parseInt(hex.slice(1), 16), f = 0.55;
  return `rgb(${(n >> 16) * f | 0},${(n >> 8 & 255) * f | 0},${(n & 255) * f | 0})`;
}
function go(i) { k = (i + D.frames.length) % D.frames.length; slider.value = k; draw(); }
slider.oninput = () => go(+slider.value);
cv.onmousedown = e => drag = [e.clientX, e.clientY, yaw, pitch];
window.onmouseup = () => drag = null;
window.onmousemove = e => { if (!drag) return;
  yaw = drag[2] + (e.clientX - drag[0]) * 0.01; pitch = Math.max(-1.4, Math.min(1.4, drag[3] + (e.clientY - drag[1]) * 0.01)); draw(); };
cv.onwheel = e => { e.preventDefault(); zoom = Math.max(0.3, Math.min(4, zoom * Math.exp(-e.deltaY * 0.001))); draw(); };
window.onkeydown = e => { if (e.key === 'ArrowRight') go(k + 1); else if (e.key === 'ArrowLeft') go(k - 1); else if (e.key === ' ') toggle(); };
function toggle() {
  if (timer) { clearInterval(timer); timer = null; document.getElementById('play').textContent = '▶'; return; }
  const dt = D.frames.length > 1 ? Math.max(15, (D.frames.at(-1).t_ms - D.frames[0].t_ms) / (D.frames.length - 1)) : 100;
  timer = setInterval(() => go(k + 1), dt); document.getElementById('play').textContent = '⏸';
}
document.getElementById('play').onclick = toggle;
window.onresize = draw;
go(0);
</script></body></html>
"""
