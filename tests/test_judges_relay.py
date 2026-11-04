"""The judges' relay (deploy/judges/): its rules, and Part 2's client talking to it over HTTPS."""

from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
import http.server
import importlib.util
import io
import json
from pathlib import Path
import sys
import tarfile
import threading

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "deploy" / "judges"))
import rules  # noqa: E402


def _load_client():
    spec = importlib.util.spec_from_file_location("p2_client", ROOT / "deploy" / "serverless" / "p2_client.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("method,path,model", [
    ("POST", "files", None),
    ("DELETE", "files/file-abc123", None),
    ("POST", "responses", "sam-3.1"),
    ("POST", "responses", "muse-spark-1.3"),
    ("POST", "responses/input_tokens", "muse-wonder-1.0"),
    ("POST", "asr/transcribe", "muse-voice-transcribe-1.0"),
    ("POST", "images/edits", "muse-image-1.0"),
])
def test_the_calls_simon_makes_are_forwarded(method, path, model):
    assert rules.allowed(method, path, model) is None


@pytest.mark.parametrize("method,path,model", [
    ("GET", "files", None),                      # listing someone's files
    ("POST", "responses", "some-other-model"),   # the key used for other work
    ("POST", "responses", None),
    ("POST", "chat/completions", "muse-spark-1.3"),
    ("POST", "asr/transcribe", "muse-spark-1.3"),
    ("DELETE", "files/../../admin", None),
    ("POST", "images/edits", "muse-spark-1.3"),
    ("POST", "responses", "muse-image-1.0"),
])
def test_negative_anything_else_is_refused(method, path, model):
    assert rules.allowed(method, path, model)


def test_uploads_deletes_and_token_counts_are_free_and_model_calls_are_reserved():
    assert rules.reserve("files", None) == 0
    assert rules.reserve("files/x", None) == 0
    assert rules.reserve("responses/input_tokens", "muse-spark-1.3") == 0
    assert rules.reserve("responses", "sam-3.1") == pytest.approx(0.60)
    assert rules.reserve("responses", "muse-wonder-1.0") == pytest.approx(0.40)


def test_cost_from_an_answer_usage_block():
    assert rules.cost_from_usage("muse-spark-1.3", {"input_tokens": 1_000_000, "output_tokens": 0}) == pytest.approx(1.25)
    cached = {"input_tokens": 1_000_000, "output_tokens": 1_000_000, "input_tokens_details": {"cached_tokens": 1_000_000}}
    assert rules.cost_from_usage("muse-spark-1.3", cached) == pytest.approx(0.15 + 4.25)
    assert rules.cost_from_usage("sam-3.1", {"frames": 1000}) == pytest.approx(0.20)
    assert rules.cost_from_usage("muse-voice-transcribe-1.0", {"seconds": 3600}) == pytest.approx(0.18)
    assert rules.cost_from_usage("muse-spark-1.3", {}) is None
    assert rules.cost_from_usage("muse-spark-1.3", None) is None


def test_refusals_in_order_closed_cap_address_day_and_rate():
    now = rules.ENDS - timedelta(hours=1)
    assert rules.refusal(0, 0, 0, 0.5, now) is None
    assert rules.refusal(0, 0, 0, 0.5, rules.ENDS)[0] == 410, "negative: closed once judging ends"
    assert rules.refusal(rules.CAP_USD - 0.1, 0, 0, 0.5, now)[0] == 402, "negative: the cap holds"
    assert rules.refusal(0, rules.IP_DAY_USD - 0.1, 0, 0.5, now)[0] == 429
    assert rules.refusal(0, 0, rules.IP_PER_MINUTE, 0, now)[0] == 429


def test_the_relay_closes_nov_9_1159_pm_eastern():
    assert rules.ENDS == datetime(2026, 11, 10, 4, 59, tzinfo=timezone.utc)
    assert rules.CAP_USD == 200


def test_alerts_at_50_80_and_100_percent_once_each():
    c = rules.CAP_USD / 100   # one percent of the cap
    assert rules.alerts_due(10 * c, 49 * c, []) == []
    assert rules.alerts_due(49 * c, 51 * c, []) == [0.5]
    assert rules.alerts_due(49 * c, 81 * c, []) == [0.5, 0.8]
    assert rules.alerts_due(49 * c, 81 * c, [0.5]) == [0.8], "negative: no repeat"
    assert rules.alerts_due(99 * c, 100.5 * c, [0.5, 0.8]) == [1.0]


def test_part2_through_the_relay_never_uses_a_meta_api_tracker():
    assert rules.part2_argv(["track", "--tracker", "api-sam31", "--input", "x"]) == ["track", "--tracker", "local-sam31", "--input", "x"]
    assert rules.part2_argv(["track", "--tracker", "auto"])[2] == "local-sam31"
    assert rules.part2_argv(["track", "--tracker", "local-open"])[2] == "local-open"
    assert rules.part2_argv(["run", "--fps", "5"]) == ["run", "--fps", "5"]


def test_p2_client_sends_the_call_to_the_relay_and_unpacks_the_answer(tmp_path, monkeypatch, capsys):
    tar_buf = io.BytesIO()
    with tarfile.open(fileobj=tar_buf, mode="w:gz") as tar:
        data = b'{"ok": true}'
        info = tarfile.TarInfo("pose.json")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    seen = {}

    class Relay(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            seen["path"] = self.path
            seen["doc"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.end_headers()
            self.wfile.write((json.dumps(["log", "part2 says hi\n"]) + "\n").encode())
            self.wfile.write((json.dumps(["result", {"exit": 0, "tar": base64.b64encode(tar_buf.getvalue()).decode()}]) + "\n").encode())

        def log_message(self, *a):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Relay)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"video")
    monkeypatch.setenv("SIMON_PART2_RELAY", f"http://127.0.0.1:{server.server_port}/")
    try:
        code = _load_client().main(["--sha", "c273b19", "--", "run", "--input", str(clip), "--out", str(tmp_path / "out")])
    finally:
        server.shutdown()
    assert code == 0
    assert seen["path"] == "/part2"
    assert seen["doc"]["sha"] == "c273b19"
    assert base64.b64decode(seen["doc"]["inputs"]["input.mp4"]) == b"video"
    assert json.loads((tmp_path / "out" / "pose.json").read_text()) == {"ok": True}
    assert "part2 says hi" in capsys.readouterr().out


def test_p2_client_reports_a_refusal_as_a_failed_run(tmp_path, monkeypatch, capsys):
    class Closed(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(402)
            self.end_headers()
            self.wfile.write(b'{"error": "the judges\' budget of $100 is spent; the relay is closed"}')

        def log_message(self, *a):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Closed)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setenv("SIMON_PART2_RELAY", f"http://127.0.0.1:{server.server_port}")
    try:
        code = _load_client().main(["--sha", "c273b19", "--", "run", "--fps", "5"])
    finally:
        server.shutdown()
    assert code == 1
    assert "refused (402)" in capsys.readouterr().out


def test_meta_callers_read_simon_meta_api():
    for rel in ("modules/part-1/keyframe_finder/meta_client.py", "modules/part-5/part5/opinion/meta_api.py",
                "part7/history_api.py", "part7/narration_api.py"):
        assert 'os.environ.get("SIMON_META_API", "https://api.meta.ai/v1")' in (ROOT / rel).read_text(), rel


def test_p2_client_uploads_positional_photos_for_avatar(tmp_path):
    photo = tmp_path / "me.jpg"
    photo.write_bytes(b"jpeg")
    argv, inputs, out = _load_client().remote_argv(["avatar", "--out", str(tmp_path / "o"), str(photo)])
    assert argv == ["avatar", "--out", "{out}", "{in}/arg0.jpg"]
    assert inputs == {"arg0.jpg": b"jpeg"}
    assert out == tmp_path / "o"


def test_photo_mesh_and_character_models_run_on_modal_without_a_local_gpu(monkeypatch, tmp_path):
    from part7 import avatar_jobs, config
    monkeypatch.setattr(config, "part2_gpu_venv_path", lambda: tmp_path / "no-venv")
    monkeypatch.delenv("SIMON7_PART2_REMOTE", raising=False)
    assert not avatar_jobs.available("image"), "negative: no GPU and no remote route"
    monkeypatch.setenv("SIMON7_PART2_REMOTE", "modal")
    assert avatar_jobs.available("image")
    assert avatar_jobs.available("autorig")
    assert avatar_jobs.available("image3d")
    monkeypatch.delenv("SIMON7_PART2_REMOTE")
    assert not avatar_jobs.available("image3d"), "negative: no GPU and no remote route"


def test_with_the_relay_set_up_a_run_on_choice_is_ignored_and_part2_runs_there(monkeypatch):
    from part7 import run_on
    from part7.parts import p2_pose
    seen = []
    work = lambda ctx: seen.append(p2_pose.first_route()) or {}  # noqa: E731
    monkeypatch.setenv("SIMON7_PART2_REMOTE", "modal")
    monkeypatch.setenv("SIMON_PART2_RELAY", "https://relay.example")
    run_on.bind(work, "local")(None)
    monkeypatch.delenv("SIMON_PART2_RELAY")
    monkeypatch.delenv("SIMON7_PART2_REMOTE")
    run_on.bind(work, "local")(None)
    assert seen == ["modal", "local"], "the relay's route wins; without it the choice applies as before"


def test_a_start_warms_part2_for_an_hour_and_a_second_start_only_adds_the_rest():
    assert rules.warm_extension(rules.WARM_FROM.timestamp() - 60, 0.0) == 0, "negative: no warm-up before judging"
    now = rules.WARM_FROM.timestamp() + 1000
    assert rules.warm_extension(now, 0.0) == 3600
    assert rules.warm_extension(now, now + 3000) == 600, "a warm-up already running is extended, not paid twice"
    assert rules.warm_extension(now, now + 4000) == 0
    assert round(3600 / 60 * rules.WARM_USD_PER_MINUTE, 2) == 1.95


def test_a_setup_marker_without_its_venv_does_not_skip_setup(tmp_path):
    from part7 import setup_parts
    clone = tmp_path / "part-3"
    clone.mkdir()
    assert not setup_parts._env_present("3", clone), "a marker alone must not skip Part 3 (no numpy without its venv)"
    (clone / ".venv" / "bin").mkdir(parents=True)
    (clone / ".venv" / "bin" / "python").write_text("")
    assert setup_parts._env_present("3", clone)
    assert not setup_parts._env_present("1", tmp_path / "part-1")
    assert setup_parts._env_present("4", tmp_path / "part-4") and setup_parts._env_present("6", tmp_path / "part-6")
