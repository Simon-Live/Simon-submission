"""part2/runapi.py: body limits, multipart parsing, sniffing, the choice of backend and tracker, capabilities and
job creation (docs/specs/run-app.md AC-A04 to AC-A07, AC-A10; staging.md AC-S06 caps; TICKET-024).

Media are made in tmp_path with Pillow and ffmpeg (tests needing ffmpeg skip without it); caps are parameters.
"""
import io
import json
import shutil
import subprocess
import time
from email.message import Message
from pathlib import Path

import pytest
from PIL import Image

from part2 import jobs, runapi

ROOT = Path(__file__).resolve().parent.parent
needs_ffmpeg = pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="ffmpeg is not installed")
ALL_UP = {"backends": {"gpu": {"ok": True}, "cpu": {"ok": True}},
          "trackers": {"local-open": {"ok": True, "why": ""}, "bytetrack": {"ok": True, "why": ""}},
          "automatic": {"ok": True, "runs": "local-sam31"}}
SMALL = runapi.Limits(video_bytes=2_000_000, photo_bytes=300_000, video_s=2.0, photo_px=500)


def headers(**h) -> Message:
    m = Message()
    for k, v in h.items():
        m[k.replace("_", "-")] = v
    return m


def form(fields: dict, file: bytes | None = None, boundary="XyZ-boundary-123", filename="clip.mp4") -> tuple[bytes, str]:
    out = b""
    for k, v in fields.items():
        out += f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
    if file is not None:
        out += (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
                f'Content-Type: application/octet-stream\r\n\r\n').encode() + file + b"\r\n"
    out += f"--{boundary}--\r\n".encode()
    return out, f"multipart/form-data; boundary={boundary}"


def jpeg(size=(64, 48), orientation=None) -> bytes:
    buf = io.BytesIO()
    img = Image.new("RGB", size, (200, 30, 30))
    exif = Image.Exif()
    if orientation:
        exif[0x0112] = orientation
    img.save(buf, "JPEG", exif=exif.tobytes())
    return buf.getvalue()


def png(size=(32, 32)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGBA", size, (0, 0, 255, 128)).save(buf, "PNG")
    return buf.getvalue()


def video(path: Path, seconds: float, fmt="mp4", fps=5, audio_only=False) -> Path:
    if audio_only:
        args = ["-f", "lavfi", "-i", f"anullsrc=r=8000:cl=mono", "-t", str(seconds), "-c:a", "aac"]
    else:
        codec = ["-c:v", "libvpx", "-b:v", "50k"] if fmt == "webm" else ["-c:v", "mpeg4"]
        args = ["-f", "lavfi", "-i", f"color=c=gray:s=32x32:r={fps}", "-t", str(seconds), *codec]
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args, str(path)], check=True, timeout=120)
    return path


def err(fn, *a, **kw) -> runapi.ApiError:
    with pytest.raises(runapi.ApiError) as e:
        fn(*a, **kw)
    return e.value


# ---- the body ---------------------------------------------------------------------------------------------

def test_content_length_is_required_and_must_be_digits():
    assert err(runapi.body_length, headers(), 100).status == 411
    assert err(runapi.body_length, headers(Transfer_Encoding="chunked", Content_Length="5"), 100).status == 411
    for bad in ("abc", "-5", "1e3", "5.0", "0x10", "", "9" * 16):
        e = err(runapi.body_length, headers(Content_Length=bad), 10 ** 20)
        assert e.status == 400 and e.message == "The Content-Length header must be a whole number of bytes.", bad
    two = headers(Content_Length="5")
    two["Content-Length"] = "6"
    assert err(runapi.body_length, two, 100).status == 400
    assert runapi.body_length(headers(Content_Length=" 42 "), 100) == 42


def test_a_body_over_the_cap_is_413_before_reading():
    e = err(runapi.body_length, headers(Content_Length=str(201_000_000)), runapi.Limits().body_bytes)
    assert e.status == 413 and e.message == "The file is too large. Videos can be up to 200 MB and photos up to 20 MB."
    assert runapi.body_length(headers(Content_Length=str(200_000_000)), runapi.Limits().body_bytes) == 200_000_000


def test_the_test_header_only_lowers_the_cap():
    limits = runapi.Limits()
    assert runapi.body_cap(headers(X_Part2_Test_Max_Body="1000"), limits) == 1000
    assert runapi.body_cap(headers(X_Part2_Test_Max_Body=str(10 ** 12)), limits) == limits.body_bytes
    assert runapi.body_cap(headers(X_Part2_Test_Max_Body="lots"), limits) == limits.body_bytes
    assert runapi.body_cap(headers(), limits) == limits.body_bytes


def test_form_boundary_needs_multipart_form_data():
    assert runapi.form_boundary("multipart/form-data; boundary=abc123") == "abc123"
    assert runapi.form_boundary('multipart/form-data; boundary="a b:c"') == "a b:c"
    for bad in ("", "application/json", "multipart/form-data", "multipart/mixed; boundary=x",
                "multipart/form-data; boundary=" + "x" * 71, "multipart/form-data; boundary=a\x00b"):
        assert err(runapi.form_boundary, bad).status == 400, bad


def test_receive_copies_exactly_the_declared_bytes_and_refuses_a_short_body(tmp_path):
    runapi.receive(io.BytesIO(b"hello world, more"), 11, tmp_path / "b", chunk=4)
    assert (tmp_path / "b").read_bytes() == b"hello world"
    e = err(runapi.receive, io.BytesIO(b"abc"), 10, tmp_path / "c")
    assert e.status == 400 and e.message == "The upload ended early. Try again."

    class Stalled:
        def read(self, n):
            raise TimeoutError("timed out")
    assert err(runapi.receive, Stalled(), 10, tmp_path / "d").status == 400


# ---- multipart -------------------------------------------------------------------------------------------------

def parse(tmp_path, body: bytes, boundary="XyZ-boundary-123"):
    path = tmp_path / "body"
    path.write_bytes(body)
    return runapi.parse_multipart(path, boundary), path


def test_fields_and_the_file_span_are_read(tmp_path):
    payload = b"\x00\xff--XyZ-boundary-12\r\nbinary\r\n--not-it" * 3
    body, _ = form({"mode": "class", "backend": "gpu", "tracker": "bytetrack", "extra": "ignored"}, payload)
    parsed, path = parse(tmp_path, body)
    assert parsed.fields == {"mode": "class", "backend": "gpu", "tracker": "bytetrack"}
    start, end = parsed.file
    assert path.read_bytes()[start:end] == payload
    assert runapi.extract(path, parsed.file, tmp_path / "out", chunk=7) == len(payload)
    assert (tmp_path / "out").read_bytes() == payload


def test_an_empty_file_part_counts_as_no_file(tmp_path):
    body, _ = form({"mode": "single", "sample": "single"}, b"", filename="")
    parsed, _ = parse(tmp_path, body)
    assert parsed.file is None and parsed.fields["sample"] == "single"


@pytest.mark.parametrize("body", [
    b"",
    b"no boundary at all",
    b"--XyZ-boundary-123\r\nContent-Disposition: form-data; name=\"mode\"\r\n\r\nsingle",          # never closed
    b"--XyZ-boundary-123junk",
    b"--XyZ-boundary-123\r\nContent-Disposition: attachment; name=\"mode\"\r\n\r\nx\r\n--XyZ-boundary-123--",
    b"--XyZ-boundary-123\r\nContent-Disposition: form-data; name=\"mode\"" + b"x" * 9000,
])
def test_malformed_bodies_are_400(tmp_path, body):
    path = tmp_path / "body"
    path.write_bytes(body)
    e = err(runapi.parse_multipart, path, "XyZ-boundary-123")
    assert e.status == 400 and e.code == "bad_form"


def test_repeated_fields_too_long_values_and_too_many_parts_are_400(tmp_path):
    part = lambda v: b'--XyZ-boundary-123\r\nContent-Disposition: form-data; name="mode"\r\n\r\n' + v + b"\r\n"
    twice = part(b"single") + part(b"class") + b"--XyZ-boundary-123--\r\n"
    assert err(lambda: parse(tmp_path, twice)).status == 400
    assert err(lambda: parse(tmp_path, form({"mode": "x" * 300})[0])).status == 400
    many = form({f"f{i}": "1" for i in range(20)})[0]
    assert err(lambda: parse(tmp_path, many)).status == 400


# ---- sniffing and intake (AC-A06, AC-A07) -------------------------------------------------------------------------

def test_a_jpeg_photo_is_stored_upright_without_metadata(tmp_path):
    src = tmp_path / "upload.bin"
    src.write_bytes(jpeg((64, 48), orientation=6))           # a phone photo held upright: rotate 90 degrees
    assert runapi.is_photo(src)
    out = runapi.intake_photo(src, tmp_path / "photo", runapi.Limits())
    assert out.name == "000000.jpg"
    with Image.open(out) as im:
        assert im.format == "JPEG" and im.size == (48, 64) and not im.getexif()


def test_a_png_photo_is_accepted(tmp_path):
    src = tmp_path / "upload.bin"
    src.write_bytes(png())
    assert runapi.is_photo(src)
    with Image.open(runapi.intake_photo(src, tmp_path / "photo", runapi.Limits())) as im:
        assert im.mode == "RGB" and im.size == (32, 32)


def test_a_photo_over_the_side_limit_is_422(tmp_path):
    src = tmp_path / "upload.bin"
    src.write_bytes(png((501, 4)))
    e = err(runapi.intake_photo, src, tmp_path / "photo", SMALL)
    assert e.status == 422 and e.message == "Photos can be at most 8000 pixels on the longest side."


def test_a_broken_photo_is_415(tmp_path):
    src = tmp_path / "upload.bin"
    src.write_bytes(b"\xff\xd8\xff\xe0" + b"not really a jpeg" * 10)
    assert err(runapi.intake_photo, src, tmp_path / "photo", runapi.Limits()).status == 415


def test_a_text_file_renamed_mp4_is_415(tmp_path):
    src = tmp_path / "upload.bin"
    src.write_text("just some text pretending to be a video\n" * 20)
    assert not runapi.is_photo(src)
    e = err(runapi.probe_video, src, runapi.Limits())
    assert e.status == 415 and e.message == "This file is not a video or photo the app can read."


def test_without_ffprobe_videos_are_503(tmp_path, monkeypatch):
    monkeypatch.setattr(runapi.shutil, "which", lambda name: None)
    src = tmp_path / "upload.bin"
    src.write_bytes(b"\x00" * 100)
    assert err(runapi.probe_video, src, runapi.Limits()).status == 503


@needs_ffmpeg
def test_mp4_and_webm_videos_are_read(tmp_path):
    assert runapi.probe_video(video(tmp_path / "a.mp4", 1.0), runapi.Limits()) == ".mp4"
    assert runapi.probe_video(video(tmp_path / "b.webm", 1.0, fmt="webm"), runapi.Limits()) == ".webm"


@needs_ffmpeg
def test_a_video_over_the_duration_limit_is_422(tmp_path):
    long = video(tmp_path / "long.mp4", 61, fps=1)
    e = err(runapi.probe_video, long, runapi.Limits())
    assert e.status == 422 and e.message == "Videos can be at most 60 seconds long."
    assert runapi.probe_video(video(tmp_path / "ok.mp4", 2.0, fps=2), runapi.Limits(video_s=60)) == ".mp4"


@needs_ffmpeg
def test_an_mp4_without_a_video_stream_is_415(tmp_path):
    audio = video(tmp_path / "audio.mp4", 1.0, audio_only=True)
    assert err(runapi.probe_video, audio, runapi.Limits()).status == 415


# ---- samples, capabilities -------------------------------------------------------------------------------------------

def test_samples_are_the_input_clips_with_stored_frames(tmp_path):
    table = runapi.samples(ROOT)
    assert set(table) == {"single", "class"}
    assert table["class"]["mode"] == "class" and table["class"]["frames"] == 89
    assert table["single"]["dir"] == ROOT / "fixtures" / "input" / "single" / "frames"
    assert runapi.samples(tmp_path) == {}


def test_capabilities_doc_from_a_probe():
    doc = runapi.capabilities_doc(ALL_UP, runapi.samples(ROOT), runapi.Limits())
    assert [b["name"] for b in doc["backends"]] == ["gpu", "cpu"] and all(b["available"] for b in doc["backends"])
    assert doc["backends"][1]["approximate"] is (not jobs.CPU_3D_BAR_PASSED)
    assert [t["name"] for t in doc["trackers"]] == ["automatic", "local-open", "bytetrack"]
    assert doc["trackers"][0]["runs"] == "local-sam31"
    assert not {"api-sam31", "local-sam31"} & {t["name"] for t in doc["trackers"]}
    assert [s["id"] for s in doc["samples"]] == ["single", "class"] and "dir" not in doc["samples"][0]
    assert doc["limits"] == {"video_mb": 200.0, "video_s": 60.0, "photo_mb": 20.0, "photo_px": 8000, "fps": 10,
                             "max_frames": 601, "queue": 5}


def test_capabilities_name_plain_reasons_and_never_echo_the_probe():
    raw = {"backends": {"gpu": {"ok": False, "reason": "/home/x/venv missing"}, "cpu": {"ok": True}},
           "trackers": {"local-open": {"ok": False, "why": "no_key"}, "bytetrack": {"ok": False, "why": "/etc/passwd"}},
           "automatic": {"ok": True, "runs": "/bin/sh"}}
    doc = runapi.capabilities_doc(raw, {}, runapi.Limits())
    text = json.dumps(doc)
    assert "/home" not in text and "/etc" not in text and "/bin" not in text
    assert doc["backends"][0] == {"name": "gpu", "label": "GPU (SAM 3D Body)", "available": False,
                                  "reason": "no GPU backend is set up on this server"}
    by = {t["name"]: t for t in doc["trackers"]}
    assert by["automatic"]["available"] is False and by["automatic"]["runs"] is None
    assert by["local-open"]["reason"] == "no key on this server"
    assert by["bytetrack"]["reason"] == "cannot run on this server"


def test_an_empty_probe_means_nothing_is_known_to_run():
    doc = runapi.capabilities_doc({}, {}, runapi.Limits())
    assert not any(e["available"] for e in doc["backends"] + doc["trackers"])
    assert {e["reason"] for e in doc["backends"] + doc["trackers"]} == {"the server could not check it"}


def test_the_probe_answer_is_cached_and_refreshed_in_the_background():
    calls = []

    def probe():
        calls.append(time.monotonic())
        return {"n": len(calls)}
    caps = runapi.Capabilities(probe=probe, ttl_s=0.2)
    assert caps.raw() == {"n": 1} and caps.raw() == {"n": 1} and len(calls) == 1
    time.sleep(0.25)
    assert caps.raw() == {"n": 1}                      # stale answer served while it refreshes
    deadline = time.monotonic() + 2
    while caps.raw() != {"n": 2} and time.monotonic() < deadline:
        time.sleep(0.02)
    assert caps.raw() == {"n": 2}


def test_a_failing_probe_is_an_empty_answer():
    assert runapi.Capabilities(probe=lambda: 1 / 0).raw() == {}
    assert runapi.Capabilities(probe=lambda: ["not", "a", "dict"]).raw() == {}


def test_the_real_probe_runs_in_the_given_interpreter_with_the_run_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("MODEL_API_KEY", "FAKE-KEY-DO-NOT-PRINT-123")
    raw = runapi.Capabilities(python=__import__("sys").executable, root=ROOT).raw()
    assert set(raw) == {"backends", "trackers", "automatic"}
    assert set(raw["backends"]) == {"gpu", "cpu"} and set(raw["trackers"]) == {"local-open", "bytetrack"}
    assert "FAKE-KEY" not in json.dumps(raw)


# ---- choosing backend, tracker, sample -------------------------------------------------------------------------------

def caps(**over):
    return runapi.capabilities_doc({**ALL_UP, **over}, runapi.samples(ROOT), runapi.Limits())


def test_mode_is_required():
    for fields in ({}, {"mode": "multi"}, {"mode": "everyone"}):
        e = err(runapi.choose, fields, caps(), runapi.samples(ROOT))
        assert e.status == 400 and e.code == "bad_mode"


@pytest.mark.parametrize("name", ["api-sam31", "local-sam31", "API-SAM31"])
@pytest.mark.parametrize("mode", ["single", "class"])
def test_a_visitor_never_names_a_paid_or_key_gated_tracker(name, mode):
    e = err(runapi.choose, {"mode": mode, "tracker": name}, caps(), {})
    assert e.status == 400 and e.message == f"The {name.lower()} tracker is chosen by the app, not by name. Choose Automatic."


def test_automatic_and_named_open_trackers():
    table = runapi.samples(ROOT)
    assert runapi.choose({"mode": "class"}, caps(), table)["tracker"] is None
    assert runapi.choose({"mode": "class", "tracker": "Automatic"}, caps(), table)["tracker"] is None
    assert runapi.choose({"mode": "class", "tracker": "bytetrack"}, caps(), table)["tracker"] == "bytetrack"
    assert runapi.choose({"mode": "single", "tracker": "bytetrack"}, caps(), table)["tracker"] is None
    assert err(runapi.choose, {"mode": "class", "tracker": "sam9"}, caps(), table).code == "unknown_tracker"
    down = caps(trackers={"local-open": {"ok": False, "why": "missing"}, "bytetrack": {"ok": True}})
    e = err(runapi.choose, {"mode": "class", "tracker": "local-open"}, down, table)
    assert e.status == 400 and e.message == "The local-open tracker is not available here."
    e = err(runapi.choose, {"mode": "class"}, caps(automatic={"ok": False}), table)
    assert e.message == "The Automatic tracker is not available here."


def test_backend_defaults_to_the_first_available_in_order():
    table = {}
    assert runapi.choose({"mode": "single"}, caps(), table)["backend"] == "gpu"
    cpu_only = caps(backends={"gpu": {"ok": False}, "cpu": {"ok": True}})
    assert runapi.choose({"mode": "single"}, cpu_only, table)["backend"] == "cpu"
    e = err(runapi.choose, {"mode": "single", "backend": "gpu"}, cpu_only, table)
    assert e.status == 400 and e.message == "The gpu backend is not available here."
    assert err(runapi.choose, {"mode": "single", "backend": "tpu"}, caps(), table).code == "unknown_backend"
    none = caps(backends={})
    e = err(runapi.choose, {"mode": "single"}, none, table)
    assert e.status == 503 and e.message == "No backend is available here right now."


def test_samples_must_exist():
    table = runapi.samples(ROOT)
    assert runapi.choose({"mode": "single", "sample": "single"}, caps(), table)["sample"] == "single"
    assert err(runapi.choose, {"mode": "single", "sample": "dance"}, caps(), table).code == "unknown_sample"
    assert err(runapi.choose, {"mode": "single", "sample": "../single"}, caps(), table).code == "unknown_sample"


# ---- create_job end to end (queue not started) ---------------------------------------------------------------------

@pytest.fixture
def queue(tmp_path):
    q = jobs.JobQueue(tmp_path / "jobs", jobs.Settings())
    yield q
    q.stop()


class NoRead:
    def read(self, n):
        raise AssertionError("the body must not be read")


def post(queue, fields, file=None, limits=runapi.Limits(), rfile=None, extra=None, capdoc=None):
    body, ctype = form(fields, file)
    h = headers(Content_Length=str(len(body)), Content_Type=ctype, **(extra or {}))
    return runapi.create_job(queue, capdoc or caps(), runapi.samples(ROOT), limits, h, rfile or io.BytesIO(body))


def job_dirs(queue):
    return sorted(p.name for p in queue.dir.iterdir()) if queue.dir.exists() else []


def test_a_sample_job_is_queued_reading_frames_in_place(queue):
    out = post(queue, {"mode": "class", "sample": "class"})
    assert out["state"] == "queued" and jobs.JOB_ID.fullmatch(out["id"])
    job = queue.get(out["id"])
    assert job.kind == "sample" and job.sample == "class" and job.mode == "class" and job.tracker is None
    assert job.input == str(ROOT / "fixtures" / "input" / "class" / "frames") and job.backend == "gpu"
    assert sorted(p.name for p in job.dir.iterdir()) == ["job.json"]


def test_a_photo_job_stores_one_upright_frame(queue):
    out = post(queue, {"mode": "single", "backend": "cpu"}, jpeg())
    job = queue.get(out["id"])
    assert job.kind == "photo" and job.backend == "cpu" and job.input == str(job.dir / "photo")
    assert sorted(p.name for p in (job.dir / "photo").iterdir()) == ["000000.jpg"]
    assert not (job.dir / "upload.bin").exists() and not (job.dir / "upload.part").exists()


@needs_ffmpeg
def test_a_video_job_stores_the_sniffed_video(queue, tmp_path):
    out = post(queue, {"mode": "single"}, video(tmp_path / "v.mp4", 1.0).read_bytes())
    job = queue.get(out["id"])
    assert job.kind == "video" and Path(job.input) == job.dir / "input.mp4" and Path(job.input).is_file()


@needs_ffmpeg
def test_runapi_refuses_422_given_more_frames_after_ingest_than_the_cap(queue, tmp_path):
    """The cap counts the frames the job's own ingest writes (part2 frames at the intake rate), not the source's."""
    from part2 import frames

    src = video(tmp_path / "v.mp4", 2.0, fps=25)
    n = len(frames.ingest(src, tmp_path / "ingested", fps=runapi.Limits().fps))
    assert n < 50                                              # 50 source frames, fewer after ingest at 10 fps
    e = err(post, queue, {"mode": "single"}, src.read_bytes(), limits=runapi.Limits(max_frames=n - 1))
    assert e.status == 422 and e.message == "Videos can be at most 60 seconds long."
    assert job_dirs(queue) == [] and queue.pending() == 0
    out = post(queue, {"mode": "single"}, src.read_bytes(), limits=runapi.Limits(max_frames=n))
    assert queue.get(out["id"]).kind == "video"


def test_refused_uploads_leave_nothing_behind(queue):
    e = err(post, queue, {"mode": "single"}, b"plain text, not a video\n" * 10)
    assert e.status == 415
    e = err(post, queue, {"mode": "single"}, b"")
    assert e.status == 415
    e = err(post, queue, {"mode": "single", "sample": "single"}, jpeg())
    assert e.status == 400 and e.message == "Send a file or a sample, not both."
    e = err(post, queue, {"mode": "single"})
    assert e.status == 400 and e.message == "Choose a file or a sample to run."
    e = err(post, queue, {"mode": "class", "tracker": "api-sam31", "sample": "class"})
    assert e.status == 400
    assert job_dirs(queue) == [] and queue.pending() == 0


def test_a_photo_over_its_own_cap_is_413(queue):
    big = jpeg((900, 900))
    limits = runapi.Limits(photo_bytes=len(big) - 1)
    e = err(post, queue, {"mode": "single"}, big, limits=limits)
    assert e.status == 413 and job_dirs(queue) == []


def test_an_oversized_body_is_refused_without_reading_it(queue):
    h = headers(Content_Length=str(201_000_000), Content_Type="multipart/form-data; boundary=x")
    e = err(runapi.create_job, queue, caps(), {}, runapi.Limits(), h, NoRead())
    assert e.status == 413 and job_dirs(queue) == []
    h = headers(Content_Length="5000", Content_Type="multipart/form-data; boundary=x", X_Part2_Test_Max_Body="4000")
    assert err(runapi.create_job, queue, caps(), {}, runapi.Limits(), h, NoRead()).status == 413


def test_missing_or_bad_length_and_a_non_form_body_are_refused_without_reading(queue):
    assert err(runapi.create_job, queue, caps(), {}, runapi.Limits(), headers(), NoRead()).status == 411
    assert err(runapi.create_job, queue, caps(), {}, runapi.Limits(), headers(Content_Length="ten"), NoRead()).status == 400
    h = headers(Content_Length="10", Content_Type="application/json")
    assert err(runapi.create_job, queue, caps(), {}, runapi.Limits(), h, NoRead()).code == "bad_form"
    assert job_dirs(queue) == []


def test_a_full_queue_is_429_before_reading(queue):
    for _ in range(5):
        post(queue, {"mode": "single", "sample": "single"})
    body, ctype = form({"mode": "single", "sample": "single"})
    h = headers(Content_Length=str(len(body)), Content_Type=ctype)
    e = err(runapi.create_job, queue, caps(), runapi.samples(ROOT), runapi.Limits(), h, NoRead())
    assert e.status == 429 and e.message == "The queue is full. Try again in a few minutes."
    assert len(job_dirs(queue)) == 5


def test_a_body_shorter_than_declared_is_400(queue):
    body, ctype = form({"mode": "single", "sample": "single"})
    h = headers(Content_Length=str(len(body) + 50), Content_Type=ctype)
    e = err(runapi.create_job, queue, caps(), runapi.samples(ROOT), runapi.Limits(), h, io.BytesIO(body))
    assert e.status == 400 and job_dirs(queue) == []


def test_every_error_message_is_plain():
    for code, text in runapi.MESSAGES.items():
        msg = text.format(name="gpu")
        assert "Traceback" not in msg and "/" not in msg and "Error" not in msg and msg.endswith("."), code


def test_the_frame_cap_admits_a_full_60_s_video_at_the_intake_rate():
    lim = runapi.Limits()
    assert lim.max_frames == int(lim.video_s * lim.fps) + 1  # frames at 0, 0.1, ..., 60.0 s


# ---- browser recordings without a duration (journey-followup.md, TICKET-039) -------------------------------

def video_without_duration(path: Path, seconds: float, fps=30, codec="libvpx", audio=True, frames=None) -> Path:
    """A WebM written to a pipe with `-live 1`, as MediaRecorder writes one: no container or stream duration."""
    args = ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"testsrc2=size=64x48:rate={fps}"]
    args += ["-f", "lavfi", "-i", "sine=frequency=440"] if audio else []
    args += (["-frames:v", str(frames)] if frames else ["-t", str(seconds)])
    args += ["-c:v", codec] + (["-c:a", "libopus"] if audio else []) + ["-live", "1", "-f", "webm", "pipe:1"]
    path.write_bytes(subprocess.run(args, check=True, capture_output=True, timeout=180).stdout)
    return path


def has_no_duration(path: Path) -> bool:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=duration",
                          "-of", "csv=p=0", str(path)], capture_output=True, text=True, check=True).stdout
    values = [v for v in out.replace(",", "\n").split() if v]
    return bool(values) and all(v == "N/A" for v in values)


@needs_ffmpeg
def test_j01_a_webm_without_any_duration_is_accepted(tmp_path):
    take = video_without_duration(tmp_path / "take.webm", 2)
    assert has_no_duration(take)  # the precondition: never passes on a file that has a duration
    assert runapi.probe_video(take, runapi.Limits()) == ".webm"


@needs_ffmpeg
@pytest.mark.parametrize("codec", ["libvpx", "libvpx-vp9"])
def test_j02_vp8_and_vp9_with_opus_work_and_the_count_matches_the_ingest(tmp_path, codec):
    from part2 import frames

    take = video_without_duration(tmp_path / "take.webm", 2, codec=codec)
    assert has_no_duration(take) and runapi.probe_video(take, runapi.Limits()) == ".webm"
    written = frames.ingest(take, tmp_path / "f", fps=10)
    assert runapi.ingest_frame_count(take, 10) == len(written)


@needs_ffmpeg
def test_j03_the_60_s_limit_holds_without_a_duration(tmp_path):
    # the span is pts[-1] - pts[0] (spec Dissent Review): 61 frames at 1 fps span 60 s, so 62 frames make the refused 61 s
    long = video_without_duration(tmp_path / "long.webm", 62, fps=1, audio=False)  # 62 frames: a 61 s span
    assert has_no_duration(long)
    e = err(runapi.probe_video, long, runapi.Limits())
    assert e.status == 422 and e.message == "Videos can be at most 60 seconds long."
    assert runapi.probe_video(video_without_duration(tmp_path / "ok.webm", 59, fps=1, audio=False),
                              runapi.Limits()) == ".webm"


@needs_ffmpeg
def test_j04_the_frame_cap_holds_without_a_duration(tmp_path):
    take = video_without_duration(tmp_path / "take.webm", 5, audio=False)
    e = err(runapi.probe_video, take, runapi.Limits(max_frames=5, fps=10))
    assert (e.status, e.code) == (422, "too_long")


@needs_ffmpeg
def test_j05_a_file_with_a_duration_reads_its_timestamps_exactly_once(tmp_path, monkeypatch):
    from part2 import frames

    calls = []
    real = frames._probe_timestamps
    monkeypatch.setattr(frames, "_probe_timestamps", lambda path: calls.append(path) or real(path))
    assert runapi.probe_video(video(tmp_path / "a.webm", 1.0, fmt="webm"), runapi.Limits()) == ".webm"
    assert len(calls) == 1
    calls.clear()
    assert runapi.probe_video(video_without_duration(tmp_path / "b.webm", 1), runapi.Limits()) == ".webm"
    assert len(calls) == 1


@needs_ffmpeg
def test_one_decoded_frame_and_no_duration_is_accepted(tmp_path):
    take = video_without_duration(tmp_path / "one.webm", 1, audio=False, frames=1)
    assert runapi.probe_video(take, runapi.Limits()) == ".webm"


@needs_ffmpeg
@pytest.mark.parametrize("failure", [RuntimeError("ffprobe failed"), ValueError("could not convert string to float")])
def test_j01_no_duration_and_unreadable_timestamps_is_415(tmp_path, monkeypatch, failure):
    from part2 import frames

    take = video_without_duration(tmp_path / "take.webm", 1, audio=False)
    assert has_no_duration(take)  # step 3 gives nothing, so step 4 reads the timestamps

    def unreadable(path):
        raise failure

    monkeypatch.setattr(frames, "_probe_timestamps", unreadable)
    e = err(runapi.probe_video, take, runapi.Limits())
    assert (e.status, e.code) == (415, "unsupported")
    assert e.message == "This file is not a video or photo the app can read."


@needs_ffmpeg
def test_j01_no_duration_and_no_decoded_frame_is_422(tmp_path, monkeypatch):
    from part2 import frames

    take = video_without_duration(tmp_path / "take.webm", 1, audio=False)
    assert has_no_duration(take)
    monkeypatch.setattr(frames, "_probe_timestamps", lambda path: [])  # packets were read, but no frame decodes
    e = err(runapi.probe_video, take, runapi.Limits())
    assert (e.status, e.code) == (422, "no_frames")
    assert e.message == "No frames could be read from this video."
