"""The page code that runs under node (docs/specs/compare-mode.md AC-M15, AC-M16; TICKET-032 and TICKET-033 batch
reviews; TICKET-034 residual 7): the output and overlay camera framing of the Run and Compare pages, run with the real
web/controls.js and the vendored THREE.Vector3, and the Compare result's source note. Each node check skips without
node; the text checks beside it still hold.
"""

import json
import math
import re

import pytest

from part3 import runapi, standard
from webkit import defines, module_url, node_json, number_in, read


# ---- the output camera of the Run page is framed for the body's height (TICKET-032) -----------------------

def test_the_output_camera_is_framed_for_the_body_height_in_the_run_page_code():
    controls, script = read("controls.js"), read("app.js")
    assert number_in(controls, "FRAMING_STATURE_M") == standard.stature_m() == 1.7  # the body the views are framed for
    assert re.search(r"\bexport function framingScale\(statureM\)", controls)
    assert "framingScale(data.metrics.stature_m)" in script  # the height the run answered with
    # Every output camera move goes through the shared framedView (scaled by state.framing); none uses the bare target.
    assert script.count("framedView(viewOffset(output, \"reset\"), OVERLAP_TARGET, state.framing)") == 1
    assert script.count("framedView(viewOffset(output.panel, name), OVERLAP_TARGET, state.framing)") == 1
    assert "output.place(viewOffset(output" not in script and "flyTo(viewOffset(output.panel" not in script
    assert "reframePanel(state, state.stage && state.stage.output.panel, framingScale(data.metrics.stature_m));" in script
    assert "framingScale" not in read("scene.js") and "framingScale" not in read("viewer.js")  # the agreement view is as before


def test_the_framing_covers_the_servers_height_range_inside_the_panel_zoom_limit():
    # The farthest output camera (the three-quarter view on a narrow panel, at the tallest Height) stays under maxDistance.
    scene, script = read("scene.js"), read("app.js")
    reset = [float(v) for v in re.search(r"reset: new THREE\.Vector3\(([-0-9., ]+)\)", scene).group(1).split(",")]
    output = re.search(r'label: "Output skeleton\.json, one fixed body", minDistance: [0-9.]+, maxDistance: ([0-9.]+)', script)
    narrow = 1.3  # viewOffset(): a tall narrow panel needs more distance
    assert math.hypot(*reset) * narrow * (runapi.STATURE_RANGE[1] / 1.7) < float(output.group(1))


FRAMING_CASES = [1.7, 1.85, 2.5, 1.55, 0.5, None, float("nan"), float("inf"), "2"]


def framing_scales():
    """framingScale of FRAMING_CASES as computed by web/controls.js itself under node, or a skip without node."""
    cases = json.dumps(FRAMING_CASES)  # Python writes NaN and Infinity, which are JavaScript literals too
    program = f"import {{ framingScale }} from {module_url('controls.js')};\n" \
              f"console.log(JSON.stringify({cases}.map(framingScale)));"
    return node_json(program, "the static checks still cover the function")


def test_framing_scale_keeps_the_standard_view_and_grows_with_a_taller_body():
    scales = framing_scales()
    assert scales[0] == 1  # 1.70 m: the view as before
    assert scales[1] == pytest.approx(1.85 / 1.7) and scales[2] == pytest.approx(2.5 / 1.7)
    assert scales[3:] == [1] * (len(FRAMING_CASES) - 3)  # a shorter body, the smallest Height, and anything not a number
    assert scales[1] < scales[2]


# ---- the overlay camera of the Compare page is framed for the tallest input (TICKET-032 batch review residual 5) --------

def imported_from_controls(page):
    block = re.search(r"import \{([^}]*)\} from \"\./controls\.js\"", read(page)).group(1)
    return [part.strip() for part in block.split(",") if part.strip()]


def test_the_compare_page_frames_its_overlay_camera_by_framing_scale():
    script = read("compare.js")
    assert {"framingScale", "framedView", "reframePanel"} <= set(imported_from_controls("compare.js"))
    assert "framingScale(run.metrics.stature_m)" in script  # the height each input's run answered with
    assert re.search(r"const tallest = Math\.max\(\.\.\.runs\.map\(", script)  # the tallest input sets the framing
    assert "reframePanel(state, state.stage && state.stage.panel, tallest);" in script
    # Every overlay camera move goes through framedView (scaled by state.framing); none uses the bare target.
    assert script.count("framedView(viewOffset(state.stage.panel, name), OVERLAP_TARGET, state.framing)") == 1
    assert re.search(r"state\.stage\.panel\.flyTo\(view\.offset, view\.target\)", script)
    assert "flyTo(viewOffset(" not in script and "OVERLAP_TARGET)" not in script


def test_one_helper_in_controls_js_frames_the_camera_of_both_pages():
    controls, app, compare = read("controls.js"), read("app.js"), read("compare.js")
    # The two functions live in controls.js, exported once each ...
    for name in ("framedView", "reframePanel"):
        assert len(re.findall(rf"\bexport function {name}\(", controls)) == 1, name
    assert re.search(r"offset: offset\.clone\(\)\.multiplyScalar\(scale\)", controls)
    assert re.search(r"const ratio = scale / state\.framing;", controls)
    assert re.search(r"if \(!panel \|\| ratio === 1\) return;", controls)  # no stage, or the same framing: camera as it is
    # ... both pages import and call them ...
    for page, script in (("app.js", app), ("compare.js", compare)):
        assert {"framedView", "reframePanel"} <= set(imported_from_controls(page)), page
        assert len(re.findall(r"\breframePanel\(state, ", script)) == 1, page
        assert "framedView(" in script, page
    # ... and neither keeps a copy of the logic behind them.
    for page, script in (("app.js", app), ("compare.js", compare)):
        for name in ("framedView", "reframePanel", "outputView", "overlayView", "frameOutput", "frameOverlay"):
            assert not defines(script, name), (page, name)
        assert "multiplyScalar" not in script, page
        assert "panel.tween = null" not in script, page
        assert "/ state.framing" not in script, page


def test_only_the_compare_and_run_pages_know_the_framing_the_agreement_view_is_as_before():
    for name in ("scene.js", "viewer.js", "index.html"):
        assert "framingScale" not in read(name), name
        assert "framing" not in read(name).lower(), name
    controls = read("controls.js")
    assert len(re.findall(r"\bexport function framingScale\b", controls)) == 1  # one definition, shared


def test_the_overlay_zoom_limit_holds_the_farthest_compare_camera_at_the_tallest_height():
    scene = read("scene.js")
    reset = [float(v) for v in re.search(r"reset: new THREE\.Vector3\(([-0-9., ]+)\)", scene).group(1).split(",")]
    overlay = re.search(r"class Overlay \{.*?new Panel\(stage, \{[^}]*maxDistance: ([0-9.]+)", scene, re.S)
    narrow = 1.3  # viewOffset(): a tall narrow panel needs more distance
    assert math.hypot(*reset) * narrow * (runapi.STATURE_RANGE[1] / 1.7) < float(overlay.group(1))


def run_framing_helpers(body):
    """Runs `body` (JavaScript) with the real framedView and reframePanel of web/controls.js and `Vec`, the vendored
    THREE.Vector3 the pages pass them (TICKET-034 residual 7); the last console.log is parsed as JSON. Skipped without
    node."""
    program = f"import {{ framedView, reframePanel }} from {module_url('controls.js')};\n" \
              f"import {{ Vector3 as Vec }} from {module_url('vendor', 'three', 'three.module.js')};\n{body}"
    return node_json(program, "the static checks still cover the helpers")


def test_framed_view_scales_the_offset_and_the_target_and_leaves_its_arguments_alone():
    out = run_framing_helpers("""
      const offset = new Vec(1.7, 0.8, 2.3), target = new Vec(0, 0.75, 0);
      const same = framedView(offset, target, 1), far = framedView(offset, target, 2.5 / 1.7);
      console.log(JSON.stringify({ same: [same.offset.toArray(), same.target.toArray()],
        far: [far.offset.toArray(), far.target.toArray()], args: [offset.toArray(), target.toArray()] }));""")
    assert out["same"] == [[1.7, 0.8, 2.3], [0, 0.75, 0]]  # scale 1 is the view as before
    assert out["far"][0] == pytest.approx([1.7 * 2.5 / 1.7, 0.8 * 2.5 / 1.7, 2.3 * 2.5 / 1.7])
    assert out["far"][1] == pytest.approx([0, 0.75 * 2.5 / 1.7, 0])
    assert out["args"] == [[1.7, 0.8, 2.3], [0, 0.75, 0]]


def test_reframe_panel_moves_the_live_camera_by_the_ratio_and_keeps_the_visitors_view():
    out = run_framing_helpers("""
      const panel = { tween: "flying", camera: { position: new Vec(-1.4, 2.6, 1.2) }, controls: { target: new Vec(0, 0.75, 0) }, placed: 0,
        place(offset, target) { this.placed += 1; this.controls.target = target; this.camera.position = target.clone(); this.offset = offset; } };
      const state = { framing: 1 };
      reframePanel(state, panel, 1);   // the same framing: nothing moves
      const idle = { framing: state.framing, placed: panel.placed, tween: panel.tween };
      reframePanel(state, null, 2);    // no 3D stage: only the framing is kept
      const headless = { framing: state.framing, placed: panel.placed };
      state.framing = 1;
      reframePanel(state, panel, 2);   // a body twice as tall: out by 2
      const moved = { framing: state.framing, placed: panel.placed, tween: panel.tween, offset: panel.offset.toArray(),
        target: panel.controls.target.toArray() };
      console.log(JSON.stringify({ idle, headless, moved }));""")
    assert out["idle"] == {"framing": 1, "placed": 0, "tween": "flying"}
    assert out["headless"] == {"framing": 2, "placed": 0}
    assert out["moved"]["framing"] == 2 and out["moved"]["placed"] == 1 and out["moved"]["tween"] is None
    assert out["moved"]["offset"] == pytest.approx([2 * (-1.4), 2 * (2.6 - 0.75), 2 * 1.2])  # camera minus target, doubled
    assert out["moved"]["target"] == pytest.approx([0, 1.5, 0])


COMPARE_STATURES = [[1.7, 1.7], [1.7, 1.85], [2.5, 1.7, 1.85], [1.55, 1.6], [None, 1.7], [1.85, None], [None, None]]


def compare_framings():
    """The expression compare.js frames its overlay camera by (`tallest`), evaluated by node on COMPARE_STATURES with the real
    framingScale, or a skip without node."""
    expression = re.search(r"const tallest = (Math\.max\(.*?\));", read("compare.js")).group(1)
    assert re.fullmatch(r"Math\.max\(\.\.\.runs\.map\(\(run\) => framingScale\(run\.metrics\.stature_m\)\)\)", expression)
    runs = json.dumps([[{"metrics": {"stature_m": s}} for s in group] for group in COMPARE_STATURES])
    program = f"import {{ framingScale }} from {module_url('controls.js')};\n" \
              f"console.log(JSON.stringify({runs}.map((runs) => {expression})));"
    return node_json(program, "the static checks still cover the page")


def test_the_compare_framing_is_one_at_the_default_height_and_follows_the_tallest_input():
    scales = compare_framings()
    assert scales[0] == 1  # two inputs at 1.70 m: the overlay view as before
    assert scales[1] == pytest.approx(1.85 / 1.7) and scales[2] == pytest.approx(2.5 / 1.7)  # the tallest decides
    # Shorter bodies, and a height that is not a number, add nothing.
    assert scales[3:] == [1, 1, pytest.approx(1.85 / 1.7), 1]




# ---- the Compare result's source note names what the server applied (docs/specs/compare-mode.md AC-M05) ---------

# (options, note): the options a run echoed, or the raw field text of readOptions(), and the note they must give.
NOTE_CASES = [
    # What the server echoes: numbers, null for a blank Height and the Source frame rate.
    ({"body": "measured", "stature": 1.85, "view": "native", "fps": 30},
     "Body: measured, height 1.85 m. View: native. Frame rate: 30 per second."),
    ({"body": "part4-rig", "stature": 2.5, "view": "part5", "fps": 60},
     "Body: part4-rig, height 2.5 m. View: part5. Frame rate: 60 per second."),
    ({"body": "simon-standard", "stature": None, "view": "native", "fps": None},
     "Body: simon-standard, height the body's own. View: native. Frame rate: source."),  # the defaults: as before
    # The page's own field text (readOptions): a number in a string is still named, a blank one reads as the default.
    ({"body": "measured", "stature": "1.85", "view": "native", "fps": "30"},
     "Body: measured, height 1.85 m. View: native. Frame rate: 30 per second."),
    ({"body": "simon-standard", "stature": "", "view": "native", "fps": ""},
     "Body: simon-standard, height the body's own. View: native. Frame rate: source."),
    ({"body": "simon-standard", "stature": "  ", "view": "part4", "fps": "abc"},
     "Body: simon-standard, height the body's own. View: part4. Frame rate: source."),
    # An answer without the echo is not a crash.
    (None, "Body: n/a, height the body's own. View: n/a. Frame rate: source."),
]


def compare_notes():
    """The note compare.js builds for each of NOTE_CASES: its own `applied`, `named` and `sourceNote` (the text between
    `const applied` and `function fillCards`) run by node with the real isNum and NA of web/controls.js, or a skip."""
    script = read("compare.js")
    start, end = script.index("const applied = "), script.index("function fillCards(")
    cases = json.dumps([options for options, _ in NOTE_CASES])
    program = f"import {{ NA, isNum }} from {module_url('controls.js')};\n{script[start:end]}\n" \
              f"console.log(JSON.stringify({cases}.map(sourceNote)));"
    return node_json(program, "the static checks still cover the page")


def test_the_compare_note_names_the_height_and_frame_rate_the_server_applied_and_reads_as_before_by_default():
    assert compare_notes() == [note for _, note in NOTE_CASES]


def test_the_compare_note_is_built_from_the_options_the_runs_echoed_not_from_the_field_text():
    script = read("compare.js")
    # Each kept run carries the options the server echoed, and the cards read the first run's (all runs got the same).
    assert re.search(r"function keepRun\(.*?\boptions: data\.options\b", script, re.S)
    assert 'byId("source-note").textContent = sourceNote(result.inputs[0].options);' in script
    # fillCards and showResult no longer take the page's readOptions() strings; the note builder never reads them.
    assert "function fillCards(result) {" in script and "function showResult(runs, compared) {" in script
    assert "fillCards(result);" in script and "showResult(runs, compared);" in script
    note = script[script.index("function sourceNote("):script.index("function fillCards(")]
    assert "readOptions" not in note and "options.stature" not in script.replace("heightError(options.stature)", "")
    assert "options.fps" not in script
    # The page still reads the field text to send it, and only for that.
    assert script.count("readOptions()") == 1 and "runAll(inputs, options)" in script


def test_the_server_echoes_the_height_and_frame_rate_as_numbers_the_note_names():
    options, bad = runapi.parse_options("body=measured&stature=1.85&view=native&fps=30")
    assert bad is None and options == {"body": "measured", "stature": 1.85, "view": "native", "fps": 30}
    status, body = runapi.handle("take-1", "auto", "", b"", options)
    assert status == 200 and body["options"] == options and body["metrics"]["stature_m"] == 1.85
    defaults, _ = runapi.parse_options("")
    assert defaults == {"body": None, "stature": None, "view": "native", "fps": None}  # body None: the View's default
    for view, used in (("native", "simon-standard"), ("part4", "part4-rig")):  # the echo names the body that ran
        status, body = runapi.handle("take-1", "auto", "", b"", {**defaults, "view": view})
        assert status == 200 and body["options"]["body"] == used and body["metrics"]["profile"] == used
