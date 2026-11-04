"""The pages, the page contract with the verify suite, and the server process (docs/specs/run-app.md: Pages, Page
contract shared with the verify suite, AC-A12, AC-A-NFR-03; `python -m part2.server` and scripts/dev.sh).

Shared fixtures and helpers: tests/server_helpers.py.
"""
import json
import os
import re
import signal
import socket
import subprocess
import time
import urllib.request
from pathlib import Path

import pytest

from part2 import server
from server_helpers import ROOT, fetch, isolated_jobs, real_port, repo, running, snapshot  # noqa: F401


# ---- nothing is written, pages are CSP safe ----------------------------------------------------------------

def test_serving_writes_nothing_in_the_tree(repo):
    before = snapshot(repo)
    with running(repo) as p:
        for path in ("/", "/api/health", "/api/outputs", "/api/outputs/class", "/api/outputs/class/frames/0.jpg",
                     "/contracts/pose3d.schema.json", "/CONTRACT.md", "/nope"):
            fetch(p, path)
        fetch(p, "/api/outputs", "POST", body=b"abc")
    assert snapshot(repo) == before


def web_text(name: str) -> str:
    return (ROOT / "web" / name).read_text()


def page_ids(html: str) -> set:
    return set(re.findall(r'\bid="([^"]+)"', html))


def test_pages_use_no_inline_script_style_or_handler_so_the_csp_holds():
    for name in ("index.html", "contract.html", "run.html"):
        html = web_text(name)
        assert not re.search(r"<script(?![^>]*\ssrc=)", html), name
        assert not re.search(r"<style|\sstyle=|\son[a-z]+=", html), name
        assert 'rel="icon" href="icon.svg"' in html and 'href="style.css"' in html
        assert not re.search(r'(?:src|href)="/', html), f"{name} must use relative URLs"
    js = web_text("browse.js") + web_text("viewer.js") + web_text("run.js") + web_text("overlay.js")
    assert not re.search(r"""(?:fetch|href\s*=|src\s*=)\s*\(?\s*['"]/""", js), "scripts must use relative URLs"
    assert "setAttribute('style'" not in js and "innerHTML" not in js


def test_every_element_the_scripts_look_up_exists_on_its_page():
    index, contract = page_ids(web_text("index.html")), page_ids(web_text("contract.html"))
    looked_up = set(re.findall(r"\$\('([a-z-]+)'\)", web_text("browse.js")))
    assert looked_up <= index | contract
    browse_ids = {"output-select", "source-line", "frame-img", "frame-empty", "viewer", "legend", "view-front", "view-side",
                  "view-top", "view-reset", "play-toggle", "frame-slider", "frame-info", "status", "alert", "overlay",
                  "person-picker", "person-select"}
    contract_ids = {"status", "alert", "schemas", "schemas-empty", "compat", "compat-empty", "contract-doc"}
    assert browse_ids <= index and contract_ids <= contract
    assert {"viewer"} & contract == set()          # browse.js tells the pages apart by the canvas


def test_controls_have_the_accessible_names_the_verify_suite_uses():
    html = web_text("index.html")
    for ident, name in (("view-front", "Front"), ("view-side", "Side"), ("view-top", "Top"),
                        ("view-reset", "Reset"), ("play-toggle", "Play")):
        assert f'<button type="button" id="{ident}">{name}</button>' in html
    assert '<label for="frame-slider">Frame</label>' in html and 'id="frame-slider" min="0"' in html
    assert '<label for="output-select">Output</label>' in html
    assert 'role="status"' in html and 'role="alert"' in html
    assert 'aria-label="3D skeleton view"' in html


def test_nothing_we_wrote_uses_an_em_or_en_dash():
    files = [*(ROOT / "web").glob("*"), *(ROOT / "part2" / n for n in ("server.py", "runapi.py", "jobs.py", "gpu_guard.py")),
             ROOT / "scripts" / "dev.sh", *(ROOT / "tests" / n for n in (
                 "server_helpers.py", "test_server.py", "test_server_run.py", "test_server_pages.py",
                 "test_viewer_js.py", "test_jobs.py", "test_runapi.py", "test_gpu_guard.py"))]
    banned = (chr(0x2014), chr(0x2013))
    for path in (f for f in files if f.exists()):  # scripts/dev.sh is firm-only and absent upstream
        assert not any(ch in path.read_text() for ch in banned), path


# ---- the process: python -m part2.server and scripts/dev.sh ---------------------------------------------------

def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_main_exits_1_with_a_plain_message_when_the_port_is_taken(capsys):
    with socket.socket() as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        assert server.main(["--port", str(busy.getsockname()[1])]) == 1
    assert "in use by another program" in capsys.readouterr().err


DEV_SH = ROOT / "scripts" / "dev.sh"
# scripts/dev.sh is a firm-only file (never published), so a clean clone of upstream skips its tests.
needs_dev_sh = pytest.mark.skipif(not DEV_SH.exists(), reason="scripts/dev.sh is firm-only; absent in this checkout")


def dev(args, port, state, timeout=40):
    env = {**os.environ, "PART2_DEV_PORT": str(port), "PART2_DEV_STATE": str(state)}
    return subprocess.run(["bash", str(ROOT / "scripts" / "dev.sh"), *args], env=env, capture_output=True, text=True, timeout=timeout)


def alive(pid: int) -> bool:
    try:
        return Path(f"/proc/{pid}/stat").read_text().split()[2] != "Z"
    except OSError:
        return False


@needs_dev_sh
def test_dev_script_starts_serves_and_stops(tmp_path):
    port, state = free_port(), tmp_path / "state"
    try:
        started = dev(["start"], port, state)
        assert started.returncode == 0, started.stderr
        pid = int((state / "dev.pid").read_text())
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=5) as r:
            assert json.load(r)["ok"] is True
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as r:
            assert b"Browse outputs" in r.read()
        again = dev([], port, state)                                  # no argument means start; already running
        assert again.returncode == 0 and "already running" in again.stdout
        assert int((state / "dev.pid").read_text()) == pid
        stopped = dev(["stop"], port, state)
        assert stopped.returncode == 0 and not (state / "dev.pid").exists()
        for _ in range(50):
            if not alive(pid):
                break
            time.sleep(0.1)
        assert not alive(pid)
        assert dev(["stop"], port, state).returncode == 0              # idempotent
    finally:
        dev(["stop"], port, state)


@needs_dev_sh
def test_dev_stop_leaves_a_foreign_process_alone(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    other = subprocess.Popen(["sleep", "30"])
    try:
        (state / "dev.pid").write_text(str(other.pid))
        done = dev(["stop"], free_port(), state)
        assert done.returncode == 0 and other.poll() is None
        assert not (state / "dev.pid").exists()
    finally:
        other.send_signal(signal.SIGKILL)
        other.wait()


@needs_dev_sh
def test_dev_script_refuses_a_port_held_by_another_program_and_unknown_arguments(tmp_path):
    with running(ROOT) as held:
        busy = dev(["start"], held, tmp_path / "state")
        assert busy.returncode == 1 and "in use by another program" in busy.stderr
    assert dev(["bogus"], free_port(), tmp_path / "state").returncode == 2


# ---- the run page (TICKET-025) and the page contract ---------------------------------------------------------------

def test_the_run_page_has_every_element_its_script_looks_up():
    run_ids = page_ids(web_text("run.html"))
    looked_up = set(re.findall(r"\$\('([a-z0-9-]+)'\)", web_text("run.js")))
    assert looked_up and looked_up <= run_ids
    viewer_ids = set(re.findall(r"\$\('([a-z-]+)'\)", web_text("viewer.js")))
    assert viewer_ids <= run_ids and viewer_ids <= page_ids(web_text("index.html"))


def test_run_page_controls_have_the_accessible_names_the_verify_suite_uses():
    html = web_text("run.html")
    assert "<legend>Input</legend>" in html and "<legend>Mode</legend>" in html
    assert '<label for="file-input">Video or photo</label>' in html
    assert 'id="mode-single" value="single" checked> One person</label>' in html
    assert 'id="mode-class" value="class"> Class</label>' in html and 'id="input-file" value="file"> Your own file</label>' in html
    for ident, name in (("backend-select", "Backend"), ("tracker-select", "Tracker"), ("person-select", "Person"),
                        ("frame-slider", "Frame")):
        assert f'<label for="{ident}">{name}</label>' in html
    for ident, name in (("run-button", "Run"), ("cancel-button", "Cancel"), ("view-front", "Front"), ("view-side", "Side"),
                        ("view-top", "Top"), ("view-reset", "Reset"), ("play-toggle", "Play"),
                        ("download-pose3d", "Download pose3d.json"), ("download-tracks", "Download tracks.json")):
        assert re.search(rf'<button type="(button|submit)" id="{ident}"[^>]*>{re.escape(name)}</button>', html), ident
    assert 'id="status" role="status"' in html and 'id="alert" role="alert"' in html
    assert 'aria-label="3D skeleton view"' in html and 'aria-label="People"' in html
    assert "input-sample-" in web_text("run.js")                     # sample radios: input-sample-<id>, label = title


def test_every_page_links_the_others_and_marks_itself():
    for name, current in (("index.html", "Browse"), ("contract.html", "Contract"), ("run.html", "Run")):
        nav = re.search(r'<nav id="site-nav" aria-label="Pages">(.*?)</nav>', web_text(name), re.S).group(1)
        links = re.findall(r'<a href="([a-z.]+)"( aria-current="page")?>([A-Za-z]+)</a>', nav)
        assert [(h, n) for h, _, n in links] == [("index.html", "Browse"), ("contract.html", "Contract"), ("run.html", "Run")]
        assert [n for _, cur, n in links if cur] == [current], name


def test_the_page_hooks_are_declared_on_window_app():
    run, browse = web_text("run.js"), web_text("browse.js")
    for key in ("ready", "output", "job", "runs", "frame", "frameCount", "playing", "people", "colors", "person",
                "viewerPeople", "camera", "target"):
        assert re.search(rf"\b{key}\b", run), key
    for key in ("ready", "output", "job", "runs", "frame", "frameCount", "playing", "people", "colors", "person",
                "camera", "target"):
        assert re.search(rf"\b{key}\b", browse), key


def test_the_run_page_is_served_with_its_scripts(real_port):
    for path, ctype in (("/run.html", "text/html"), ("/run.js", "text/javascript"), ("/overlay.js", "text/javascript")):
        status, headers, body = fetch(real_port, path)
        assert status == 200 and headers["content-type"].startswith(ctype) and body
    assert b'src="overlay.js"' in fetch(real_port, "/index.html")[2]
