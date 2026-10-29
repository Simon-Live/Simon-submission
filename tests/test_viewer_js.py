"""web/viewer.js and web/overlay.js: constants, colours, projection and placement agree with part2, and the camera
controls work (AC-A01, AC-A03, AC-A05).

Both scripts are plain JavaScript with no DOM at import time, so these tests run them under Node with a stub
canvas and stub controls. The pages themselves are proved on the running app by the staging verify suite.
"""
import json
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from part2 import demo
from part2.canonical import to_camera
from part2.joints import BONES, CANONICAL

ROOT = Path(__file__).resolve().parent.parent
VIEWER = ROOT / "web" / "viewer.js"
OVERLAY = ROOT / "web" / "overlay.js"
OUT = ROOT / "fixtures" / "output"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node is not installed")

PRELUDE = f"""
const V = require({json.dumps(str(VIEWER))});
const O = require({json.dumps(str(OVERLAY))});
const fs = require('fs');
const readJSON = p => JSON.parse(fs.readFileSync(p, 'utf8'));
function stub(size = 300) {{
  const handlers = {{}}, calls = [], styles = new Set();
  const ctx = new Proxy({{}}, {{
    get(t, k) {{ return k in t ? t[k] : (...a) => {{ calls.push([k, ...a]); }}; }},
    set(t, k, v) {{ if (k === 'strokeStyle' || k === 'fillStyle') styles.add(v); t[k] = v; return true; }},
  }});
  const canvas = {{ width: size, height: size, getContext: () => ctx, getBoundingClientRect: () => ({{ width: size, height: size }}),
    addEventListener: (name, fn) => {{ handlers[name] = fn; }}, setPointerCapture() {{}} }};
  return {{ canvas, handlers, calls, styles }};
}}
function manualTimers() {{
  const t = {{ fn: null, ms: null }};
  return {{ t, timers: {{ set: (fn, ms) => {{ t.fn = fn; t.ms = ms; return 1; }}, clear: () => {{ t.fn = null; }} }} }};
}}
function viewerFor(dir, extra) {{
  const s = stub(), m = manualTimers();
  const v = V.create(s.canvas, {{ timers: m.timers }});
  v.setScene(V.buildScene(readJSON(`${{dir}}/pose3d.json`), readJSON(`${{dir}}/camera.json`)));
  return {{ v, s, m }};
}}
"""


def run_js(body: str):
    code = PRELUDE + f"\nconst result = (() => {{ {body} }})();\nconsole.log(JSON.stringify(result));"
    done = subprocess.run(["node", "-e", code], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_joints_bones_and_palette_match_the_demo():
    got = run_js("return {joints: V.JOINTS, bones: V.BONES, palette: V.PALETTE};")
    assert got["joints"] == CANONICAL
    assert got["bones"] == [[CANONICAL.index(a), CANONICAL.index(b)] for a, b in BONES]
    assert got["palette"] == demo.COLORS


def test_color_for_matches_demo_for_numbers_and_strings():
    ids = list(range(-14, 40)) + ["7", "007", "a", "track-3", "person 9", "é", "-0", ""]
    got = run_js(f"return {json.dumps(ids)}.map(id => V.colorFor(id));")
    assert got == [demo.color_for(i) for i in ids]


def test_shade_is_a_darker_tone():
    assert run_js("return V.shade('#E69F00');") == "rgb(126,87,0)"


def test_one_person_is_drawn_person_centred():
    got = run_js("""
      const pose = readJSON(%s), s = V.buildScene(pose, readJSON(%s));
      const j = pose.frames[5].people[0].joints.nose;
      return {placement: s.placement, ids: s.ids, nose: s.frames[5].people[0].pts[0], expect: [j.x, j.y, j.z]};
    """ % (json.dumps(str(OUT / "single" / "pose3d.json")), json.dumps(str(OUT / "single" / "camera.json"))))
    assert got["placement"] == "canonical" and got["ids"] == [0]
    assert got["nose"] == got["expect"]


def test_several_people_are_placed_with_camera_json():
    pose = json.loads((OUT / "class" / "pose3d.json").read_text())
    camera = json.loads((OUT / "class" / "camera.json").read_text())
    got = run_js("""
      const s = V.buildScene(readJSON(%s), readJSON(%s));
      const f = s.frames[10];
      return {placement: s.placement, ids: s.ids, drawn: f.people.map(p => p.id), pts: f.people.map(p => p.pts)};
    """ % (json.dumps(str(OUT / "class" / "pose3d.json")), json.dumps(str(OUT / "class" / "camera.json"))))
    assert got["placement"] == "scene" and got["ids"] == list(range(7)) and got["drawn"] == list(range(7))
    cams = {(f["frame"], c["id"]): c for f in camera["frames"] for c in f["people"]}
    for person, pts in zip(pose["frames"][10]["people"], got["pts"]):
        can = np.array([[person["joints"][j][k] for k in "xyz"] for j in CANONICAL])
        c = cams[(pose["frames"][10]["frame"], person["id"])]
        cam = to_camera(can, np.array(c["R"]), np.array(c["t"]))
        np.testing.assert_allclose(pts, cam * [1, -1, -1], atol=1e-9)   # y up, z toward the camera


def test_a_person_without_a_camera_pose_is_left_out_of_a_scene_frame():
    got = run_js("""
      const person = id => ({id, joints: Object.fromEntries(V.JOINTS.map(n => [n, {x: 0, y: 0, z: 0, conf: 1}]))});
      const pose = {frames: [{frame: 0, t_ms: 0, people: [person(1), person(2)]}]};
      const cam = {frames: [{frame: 0, people: [{id: 1, R: [[1,0,0],[0,1,0],[0,0,1]], t: [0, 0, 3]}]}]};
      return V.buildScene(pose, cam).frames[0].people.map(p => p.id);
    """)
    assert got == [1]


def test_presets_put_the_camera_on_the_axes_of_the_target():
    got = run_js("""
      const {v} = viewerFor(%s), out = {};
      for (const name of ['front', 'side', 'top']) {
        v.view(name);
        out[name] = v.camera().map((c, i) => c - v.target()[i]);
      }
      return {out, dist: v.distance()};
    """ % json.dumps(str(OUT / "class")))
    d = got["dist"]
    assert got["out"]["front"] == pytest.approx([0, 0, d], abs=1e-9)
    assert got["out"]["side"] == pytest.approx([d, 0, 0], abs=1e-9)
    assert got["out"]["top"] == pytest.approx([0, d, 0], abs=1e-9)


def test_reset_returns_the_camera_home_after_drag_zoom_and_a_preset():
    got = run_js("""
      const {v, s} = viewerFor(%s), home = v.camera(), homeDist = v.distance();
      s.handlers.pointerdown({pointerId: 1, clientX: 100, clientY: 100});
      s.handlers.pointermove({pointerId: 1, clientX: 160, clientY: 140});
      s.handlers.pointerup({pointerId: 1});
      const dragged = v.camera();
      s.handlers.wheel({preventDefault() {}, deltaY: 400});
      const zoomed = v.distance();
      v.view('top'); v.reset();
      return {home, dragged, homeDist, zoomed, after: v.camera(), afterDist: v.distance()};
    """ % json.dumps(str(OUT / "single")))
    assert got["dragged"] != got["home"] and got["zoomed"] > got["homeDist"]
    assert got["after"] == got["home"] and got["afterDist"] == got["homeDist"]


def test_drag_turns_the_camera_and_keeps_its_distance():
    got = run_js("""
      const {v, s} = viewerFor(%s), d0 = v.distance(), c0 = v.camera();
      s.handlers.pointerdown({pointerId: 1, clientX: 50, clientY: 50});
      s.handlers.pointermove({pointerId: 1, clientX: 90, clientY: 50});
      const right = v.camera();
      s.handlers.pointermove({pointerId: 1, clientX: 90, clientY: 80});
      const down = v.camera();
      s.handlers.pointerup({pointerId: 1});
      s.handlers.pointermove({pointerId: 1, clientX: 400, clientY: 400});   // not pressed: ignored
      const t = v.target(), len = c => Math.hypot(...c.map((x, i) => x - t[i]));
      return {c0, right, down, ignored: v.camera(), lens: [len(c0), len(right), len(down)], d0};
    """ % json.dumps(str(OUT / "single")))
    assert got["right"] != got["c0"] and got["down"] != got["right"] and got["ignored"] == got["down"]
    assert got["down"][1] > got["right"][1]                                  # dragging down lifts the camera
    assert all(abs(n - got["d0"]) < 1e-9 for n in got["lens"])


def test_wheel_and_pinch_change_the_distance_within_limits():
    got = run_js("""
      const {v, s} = viewerFor(%s), d0 = v.distance(), seen = [];
      s.handlers.wheel({preventDefault() {}, deltaY: 300}); seen.push(v.distance());
      s.handlers.wheel({preventDefault() {}, deltaY: -600}); seen.push(v.distance());
      for (let i = 0; i < 80; i++) s.handlers.wheel({preventDefault() {}, deltaY: 1000});
      const far = v.distance();
      for (let i = 0; i < 80; i++) s.handlers.wheel({preventDefault() {}, deltaY: -1000});
      const near = v.distance();
      v.reset();
      s.handlers.pointerdown({pointerId: 1, clientX: 100, clientY: 100});
      s.handlers.pointerdown({pointerId: 2, clientX: 140, clientY: 100});
      const before = v.distance();
      s.handlers.pointermove({pointerId: 2, clientX: 220, clientY: 100});     // fingers apart: zoom in
      return {d0, seen, far, near, before, pinched: v.distance()};
    """ % json.dumps(str(OUT / "single")))
    assert got["seen"][0] > got["d0"] > got["seen"][1]
    assert got["far"] == pytest.approx(got["d0"] * 5) and got["near"] == pytest.approx(got["d0"] * 0.3)
    assert got["before"] == got["d0"] and got["pinched"] == pytest.approx(got["d0"] / 3)


def test_pitch_is_limited_to_straight_up_and_down():
    got = run_js("""
      const {v, s} = viewerFor(%s);
      s.handlers.pointerdown({pointerId: 1, clientX: 0, clientY: 0});
      s.handlers.pointermove({pointerId: 1, clientX: 0, clientY: 5000});
      const up = v.camera().map((c, i) => c - v.target()[i]);
      s.handlers.pointermove({pointerId: 1, clientX: 0, clientY: -5000});
      const down = v.camera().map((c, i) => c - v.target()[i]);
      return {up, down, d: v.distance()};
    """ % json.dumps(str(OUT / "single")))
    assert got["up"][1] == pytest.approx(got["d"]) and got["down"][1] == pytest.approx(-got["d"])


def test_frames_step_wrap_clamp_and_play_pause():
    got = run_js("""
      const {v, m} = viewerFor(%s), n = v.frameCount(), seen = {};
      seen.n = n; seen.start = v.frame();
      v.step(1); seen.step = v.frame();
      v.step(-2); seen.wrapBack = v.frame();
      v.setFrame(10 * n); seen.clamped = v.frame();
      v.setFrame(-3); seen.clampedLow = v.frame();
      v.setFrame(7); v.play(); seen.playing = v.playing(); seen.ms = m.t.ms;
      m.t.fn(); m.t.fn(); seen.advanced = v.frame();
      v.pause(); seen.paused = v.playing(); seen.cleared = m.t.fn === null;
      v.setFrame(n - 1); v.step(1); seen.wrapForward = v.frame();
      v.toggle(); seen.toggled = v.playing(); v.toggle(); seen.toggledBack = v.playing();
      return seen;
    """ % json.dumps(str(OUT / "class")))
    assert got["n"] == 89 and got["start"] == 0 and got["step"] == 1
    assert got["wrapBack"] == 88 and got["clamped"] == 88 and got["clampedLow"] == 0
    assert got["playing"] and got["ms"] == 200 and got["advanced"] == 9
    assert got["paused"] is False and got["cleared"] and got["wrapForward"] == 0
    assert got["toggled"] is True and got["toggledBack"] is False


def test_a_single_frame_cannot_play():
    got = run_js("""
      const s = stub(), m = manualTimers(), v = V.create(s.canvas, {timers: m.timers});
      const person = {id: 0, joints: Object.fromEntries(V.JOINTS.map(n => [n, {x: 0, y: 0.1, z: 0, conf: 1}]))};
      v.setScene(V.buildScene({frames: [{frame: 0, t_ms: 0, people: [person]}]}, {frames: []}));
      v.play();
      return {playing: v.playing(), count: v.frameCount()};
    """)
    assert got == {"playing": False, "count": 1}


def test_every_person_in_the_frame_is_drawn_in_their_own_colour():
    got = run_js("""
      const {v, s} = viewerFor(%s);
      v.draw();
      return {people: v.people(), colors: v.colors(), styles: [...s.styles], strokes: s.calls.filter(c => c[0] === 'stroke').length};
    """ % json.dumps(str(OUT / "class")))
    assert got["people"] == list(range(7))
    assert got["colors"] == {str(i): demo.color_for(i) for i in range(7)}
    assert set(got["colors"].values()) <= set(got["styles"])
    assert got["strokes"] >= 7 * len(BONES)


def test_a_frame_with_nobody_says_so_and_draws_no_skeleton():
    got = run_js("""
      const s = stub(), v = V.create(s.canvas, {timers: manualTimers().timers});
      const person = {id: 0, joints: Object.fromEntries(V.JOINTS.map(n => [n, {x: 0, y: 0.1, z: 0, conf: 1}]))};
      v.setScene(V.buildScene({frames: [{frame: 0, t_ms: 0, people: [person]}, {frame: 1, t_ms: 100, people: []}]}, {frames: []}));
      v.setFrame(1); s.calls.length = 0; v.draw();
      return {people: v.people(), text: s.calls.filter(c => c[0] === 'fillText').map(c => c[1])};
    """)
    assert got["people"] == [] and "Nobody was found in this frame." in got["text"]


def test_drawing_before_a_scene_is_loaded_does_nothing():
    got = run_js("""
      const s = stub(), v = V.create(s.canvas, {timers: manualTimers().timers});
      v.draw(); v.view('front'); v.step(1); v.play();
      return {n: v.frameCount(), people: v.people(), playing: v.playing(), strokes: s.calls.filter(c => c[0] === 'stroke').length};
    """)
    assert got == {"n": 0, "people": [], "playing": False, "strokes": 0}


# ---- notes and shared controls ---------------------------------------------------------------------------------

def test_the_empty_frame_note_can_be_changed():
    got = run_js("""
      const s = stub(), v = V.create(s.canvas, {timers: manualTimers().timers});
      v.setScene(V.buildScene({frames: [{frame: 0, t_ms: 0, people: []}]}, {frames: []}));
      v.setNote('This person is not in this frame.'); s.calls.length = 0; v.draw();
      return s.calls.filter(c => c[0] === 'fillText').map(c => c[1]);
    """)
    assert "This person is not in this frame." in got


def test_bind_controls_wires_buttons_slider_and_keys():
    got = run_js("""
      const els = {}, docHandlers = {};
      const el = id => (els[id] = els[id] || {id, value: '0', textContent: 'Play', handlers: {},
        addEventListener(n, fn) { this.handlers[n] = fn; }});
      globalThis.document = {addEventListener: (n, fn) => { docHandlers[n] = fn; }};
      const {v, m} = viewerFor(%s);
      V.bindControls(v, el);
      const rel = () => v.camera().map((c, i) => +(c - v.target()[i]).toFixed(9));
      const out = {};
      els['view-side'].handlers.click(); out.side = rel();
      els['view-top'].handlers.click(); out.top = rel();
      els['view-front'].handlers.click(); out.front = rel();
      els['view-reset'].handlers.click(); out.reset = rel();
      els['frame-slider'].value = '12'; els['frame-slider'].handlers.input(); out.slider = v.frame();
      const key = (k, tag) => docHandlers.keydown({key: k, target: {tagName: tag || 'BODY'}, preventDefault() {}});
      key('ArrowRight'); out.right = v.frame();
      key('ArrowLeft'); key('ArrowLeft'); out.left = v.frame();
      key('ArrowRight', 'INPUT'); out.inInput = v.frame();
      els['play-toggle'].handlers.click(); out.playing = v.playing(); out.label = els['play-toggle'].textContent;
      els['play-toggle'].handlers.click(); out.label2 = els['play-toggle'].textContent;
      out.d = v.distance();
      return out;
    """ % json.dumps(str(OUT / "class")))
    d = got["d"]
    assert got["side"] == pytest.approx([d, 0, 0]) and got["top"] == pytest.approx([0, d, 0])
    assert got["front"] == pytest.approx([0, 0, d]) and got["reset"] != got["front"]
    assert got["slider"] == 12 and got["right"] == 13 and got["left"] == 11 and got["inInput"] == 11
    assert got["playing"] is True and got["label"] == "Pause" and got["label2"] == "Play"


# ---- overlay.js ------------------------------------------------------------------------------------------------

def test_overlay_projection_matches_part2_canonical_project_pose3d():
    from part2.canonical import project_pose3d

    pose = json.loads((OUT / "class" / "pose3d.json").read_text())
    camera = json.loads((OUT / "class" / "camera.json").read_text())
    got = run_js("return O.project(readJSON(%s), readJSON(%s));" % (
        json.dumps(str(OUT / "class" / "pose3d.json")), json.dumps(str(OUT / "class" / "camera.json"))))
    want = project_pose3d(pose, camera)
    assert set(got) == {f"{f}:{i}" for f, i in want}
    for (f, i), joints in want.items():
        np.testing.assert_allclose(got[f"{f}:{i}"], [joints[j] for j in CANONICAL], atol=1e-6)


def test_overlay_fit_matches_object_fit_contain():
    got = run_js("return [O.fit(1280, 720, 640, 640), O.fit(720, 1280, 400, 300)];")
    assert got[0] == pytest.approx({"s": 0.5, "ox": 0, "oy": 140})
    assert got[1] == pytest.approx({"s": 300 / 1280, "ox": (400 - 720 * 300 / 1280) / 2, "oy": 0})


def test_overlay_draws_every_person_in_the_frame_in_their_colour():
    got = run_js("""
      const s = stub(640), o = O.create(s.canvas);
      o.setData(readJSON(%s), readJSON(%s));
      const seen = [];
      for (const i of [0, 44, 88]) { o.setFrame(i); seen.push(o.people()); }
      s.calls.length = 0; o.pick(3); o.draw();
      return {seen, ids: o.ids(), colors: o.colors(), styles: [...s.styles],
              strokes: s.calls.filter(c => c[0] === 'stroke').length, labels: s.calls.filter(c => c[0] === 'fillText').map(c => c[1])};
    """ % (json.dumps(str(OUT / "class" / "pose3d.json")), json.dumps(str(OUT / "class" / "camera.json"))))
    assert got["ids"] == list(range(7)) and all(len(ids) >= 5 for ids in got["seen"])
    assert got["colors"] == {str(i): demo.color_for(i) for i in range(7)}
    assert set(got["colors"].values()) <= set(got["styles"])
    assert got["strokes"] >= 5 * len(BONES) and {"id 3"} <= set(got["labels"])


def test_overlay_without_data_draws_nothing_and_one_person_has_no_label():
    got = run_js("""
      const s = stub(), o = O.create(s.canvas);
      o.draw(); const empty = {people: o.people(), strokes: s.calls.filter(c => c[0] === 'stroke').length};
      o.setData(readJSON(%s), readJSON(%s)); s.calls.length = 0; o.setFrame(3);
      const one = {people: o.people(), labels: s.calls.filter(c => c[0] === 'fillText').length};
      o.clear();
      return {empty, one, cleared: o.people()};
    """ % (json.dumps(str(OUT / "single" / "pose3d.json")), json.dumps(str(OUT / "single" / "camera.json"))))
    assert got["empty"] == {"people": [], "strokes": 0}
    assert got["one"] == {"people": [0], "labels": 0} and got["cleared"] == []


def test_a_picked_person_is_shown_alone_in_the_canonical_frame():
    pose = json.loads((OUT / "class" / "pose3d.json").read_text())
    got = run_js("""
      const pose = readJSON(%s), cam = readJSON(%s);
      const scene = O.personScene(pose, cam, 4);
      const s = stub(), v = V.create(s.canvas, {timers: manualTimers().timers});
      v.setScene(scene); v.setFrame(10); v.view('front');
      return {placement: scene.placement, ids: scene.ids, frames: scene.frames.length, drawn: v.people(),
              front: v.camera().map((c, i) => c - v.target()[i]), d: v.distance(),
              pts: scene.frames[10].people[0].pts, axes: scene.home.axes.labels,
              kept: O.onlyPerson(pose, 4).frames.length, idOf: [O.idOf('4', [3, 4]), O.idOf('x', [3, 4])]};
    """ % (json.dumps(str(OUT / "class" / "pose3d.json")), json.dumps(str(OUT / "class" / "camera.json"))))
    person = next(p for p in pose["frames"][10]["people"] if p["id"] == 4)
    assert got["placement"] == "canonical" and got["ids"] == [4] and got["drawn"] == [4]
    assert got["frames"] == len(pose["frames"]) == got["kept"]
    assert got["front"] == pytest.approx([0, 0, got["d"]], abs=1e-9)          # Front: camera on +z, the body's front
    assert got["axes"] == ["x left", "y up", "z front"]
    np.testing.assert_allclose(got["pts"], [[person["joints"][j][k] for k in "xyz"] for j in CANONICAL])
    assert got["idOf"] == [4, None]
