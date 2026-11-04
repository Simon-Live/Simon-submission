"""byok-prod.md AC-BY12 (BYOK-M7, prod verify a11y B3): under BYOK-only trainer captions come from the trainer's own
Modal account in the format the caption code reads, and an entry without captions has no sound in its public video.

The launcher is real (`p2_client.py --own --transcribe`); the Modal client it starts is a stand-in
(`SIMON7_MODAL_PYTHON`) that writes `transcript.json` like `transcribe_own` would. The client side of the call
(`transcribe_own`) runs against a fake `modal` module. Nothing reaches Modal."""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
import struct
import subprocess
import sys
from types import SimpleNamespace
from typing import Any
import wave

import pytest

from part7 import byok_route, narration, narration_api, narration_own
from part7.parts import p2_pose
from test_byok_client import AuthError, NotFoundError, Volume, load_client, no_pickle

TOKENS = {"MODAL_TOKEN_ID": "ak-CaptionToken00001", "MODAL_TOKEN_SECRET": "as-CaptionSecret0001"}
TURNS = [{"startMs": 400, "endMs": 1600, "transcript": "Keep your back straight"},
         {"startMs": 2200, "endMs": 3400, "transcript": "now lower slowly"}]

# The launcher gives its child a fresh env, so the stand-in gets its paths from its own text, not from variables.
STAND_IN = r'''
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
Path(LOG).write_text(json.dumps({"args": args, "env": sorted(os.environ)}))
if Path(FAIL).exists():
    sys.exit(1)
out = Path(args[args.index("--out") + 1])
out.mkdir(parents=True, exist_ok=True)
(out / "transcript.json").write_text(json.dumps({"transcript": "", "turns": TURNS}))
'''


def tone(path: Path, seconds: float = 4.0, rate: int = 16000) -> Path:
    """A mono 16 kHz WAV with a loud tone (speech-like level for the silence check)."""
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"".join(struct.pack("<h", int(12000 * math.sin(i / 8))) for i in range(int(seconds * rate))))
    return path


@pytest.fixture
def own_route(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    script = tmp_path / "stand_in.py"
    head = f"LOG = {str(tmp_path / 'call.json')!r}\nFAIL = {str(tmp_path / 'fail')!r}\nTURNS = {TURNS!r}\n"
    script.write_text(head + STAND_IN, encoding="utf-8")
    fake = tmp_path / "modal-python"
    # the launcher runs `<python> -I p2_client.py --own-child ...`: the stand-in takes the place of p2_client.py
    fake.write_text(f'#!/bin/sh\nshift 2\nexec "{sys.executable}" "{script}" "$@"\n', encoding="utf-8")
    fake.chmod(0o755)
    monkeypatch.setenv("SIMON7_MODAL_PYTHON", str(fake))
    monkeypatch.setenv("FAKE_TURNS", "server env only")
    monkeypatch.setenv(byok_route.PROD_COMPUTE_ENV, "byok")
    monkeypatch.delenv("FIRM_ENV", raising=False)
    return {"log": tmp_path / "call.json", "fail": tmp_path / "fail"}


def test_captions_come_from_the_owners_account_in_the_caption_format(tmp_path: Path, own_route: dict[str, Any]) -> None:
    wav = tone(tmp_path / "voice.wav")
    with p2_pose.job_modal_env_set(TOKENS):
        doc = narration.build(wav, {}, 4000, ledger=tmp_path / "spend.jsonl")
    assert doc is not None and doc["source"] == narration_own.MODEL and doc["estimated_usd"] == 0.0
    assert [c["text"] for c in doc["cues"]] == ["Keep your back straight", "now lower slowly"]
    assert all({"start_s", "end_s", "text", "section"} <= set(c) for c in doc["cues"])
    call = json.loads(own_route["log"].read_text())
    assert call["args"][:2] == ["--own-child", "--transcribe"]
    assert {"MODAL_TOKEN_ID", "MODAL_TOKEN_SECRET"} <= set(call["env"]) and "FAKE_TURNS" not in call["env"], \
        "the Modal client gets the launcher's fresh env, not the server's"
    assert not (tmp_path / "spend.jsonl").exists(), "no operator spend is booked"


def test_without_owner_credentials_no_call_is_made(tmp_path: Path, own_route: dict[str, Any],
                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(narration_api, "transcribe", lambda *a, **k: pytest.fail("Muse was called under BYOK"))
    with pytest.raises(narration_api.NarrationError, match="no owner credentials"):
        narration.build(tone(tmp_path / "voice.wav"), {}, 4000)
    assert not own_route["log"].exists()


def test_a_failed_own_call_raises_and_writes_nothing(tmp_path: Path, own_route: dict[str, Any],
                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    own_route["fail"].write_text("1")
    with p2_pose.job_modal_env_set(TOKENS), pytest.raises(narration_api.NarrationError, match="exit"):
        narration_own.transcribe(tone(tmp_path / "voice.wav"), timeout=30)


def test_narration_error_names_the_timeout_and_the_call_given_a_captions_call_that_never_answers(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Prod read "ended with exit None" and kept nothing else: the wording hid a timeout and the call to look up at Modal."""
    monkeypatch.setattr(narration_own.compute_mode, "serverless", lambda: True)
    said = "modal: captions call fc-01\n\npart 7 timed out after 300 s\n"
    monkeypatch.setattr(narration_own.runner, "run", lambda *a, **k: {"exit": None, "timed_out": True, "output": said})
    with pytest.raises(narration_api.NarrationError) as err:
        narration_own.transcribe(tone(tmp_path / "voice.wav"), timeout=300.0)
    text = str(err.value)
    assert "timed out after 300 s" in text and "modal: captions call fc-01" in text and "Simon's GPU service" in text
    assert "exit None" not in text and "owner's" not in text


def test_narration_error_keeps_the_exit_and_only_the_clients_lines_given_a_failed_call(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # negative: a failure is not called a timeout
    monkeypatch.setattr(narration_own.compute_mode, "serverless", lambda: True)
    said = "Traceback secret-text\nmodal: the workspace cannot run this (AuthError)\n"
    monkeypatch.setattr(narration_own.runner, "run", lambda *a, **k: {"exit": 80, "timed_out": False, "output": said})
    with pytest.raises(narration_api.NarrationError) as err:
        narration_own.transcribe(tone(tmp_path / "voice.wav"), timeout=300.0)
    text = str(err.value)
    assert "ended with exit 80" in text and "cannot run this (AuthError)" in text
    assert "timed out" not in text and "secret-text" not in text


def test_captions_budget_is_short_enough_not_to_hold_a_movement_for_minutes() -> None:
    assert narration_own.BUDGET_S <= 120.0


# ----- no sound without captions ---------------------------------------------------------------------------------
def clip_with_sound(path: Path) -> Path:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=gray:s=64x64:d=2", "-f", "lavfi",
                    "-i", "sine=frequency=440:duration=2", "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", str(path)], check=True, timeout=60)
    return path


def audio_streams(path: Path) -> str:
    return subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of",
                           "csv=p=0", str(path)], capture_output=True, text=True, timeout=30).stdout.strip()


def test_an_entry_without_captions_loses_its_sound(tmp_path: Path, own_route: dict[str, Any],
                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    entry = tmp_path / "catalog" / "squat-1"
    entry.mkdir(parents=True)
    video = clip_with_sound(entry / "video.mp4")
    assert audio_streams(video)
    monkeypatch.setenv("SIMON7_NARRATION", "off")  # any way of ending without narration.json
    assert narration.attach(video, entry, video=video) is None
    assert video.is_file() and audio_streams(video) == "", "a public clip with sound and no captions"
    assert narration_own.drop_audio(entry) is False, "already silent"


def test_outside_byok_the_sound_stays(tmp_path: Path, own_route: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(byok_route.PROD_COMPUTE_ENV)
    entry = tmp_path / "e"
    entry.mkdir()
    video = clip_with_sound(entry / "video.mp4")
    monkeypatch.setenv("SIMON7_NARRATION", "off")
    assert narration.attach(video, entry, video=video) is None and audio_streams(video)


def test_when_the_sound_cannot_be_dropped_the_clip_goes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    entry = tmp_path / "e"
    entry.mkdir()
    (entry / "video.mp4").write_bytes(b"not a video")
    monkeypatch.setattr(narration_own.ffsafe, "run", lambda argv, **k: SimpleNamespace(returncode=1, stdout="x", stderr=""))
    assert narration_own.drop_audio(entry) is True and not (entry / "video.mp4").exists()


# ----- the client side: capped JSON, no pickle -------------------------------------------------------------------
class AsrFake:
    def __init__(self, write: Any) -> None:
        self.vol, self.spawned, self.cancelled = Volume(), [], 0
        fake = self

        class Call:
            def get(self, timeout: float | None = None) -> Any:
                pytest.fail("the result of the call was fetched")

            def cancel(self) -> None:
                fake.cancelled += 1

        class Method:
            def spawn(self, key: str, audio: bytes) -> Any:
                fake.spawned.append((key, len(audio)))
                write(fake.vol, key)
                return Call()

        self.module = SimpleNamespace(
            Volume=SimpleNamespace(from_name=lambda name, create_if_missing=False: fake.vol),
            Cls=SimpleNamespace(from_name=lambda app, cls: (lambda: SimpleNamespace(transcribe_io=Method()))
                                if cls == "Transcribe" else pytest.fail(cls)),
            exception=SimpleNamespace(AuthError=AuthError, NotFoundError=NotFoundError),
        )


def written(doc: Any, code: int = 0, raw: bytes | None = None) -> Any:
    def write(vol: Volume, key: str) -> None:
        vol.files[f"{key}/transcript.json"] = raw if raw is not None else json.dumps(doc).encode()
        vol.files[f"{key}/result.json"] = json.dumps({"exit": code}).encode()
    return write


def test_transcribe_own_reads_capped_json_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = load_client()
    no_pickle(monkeypatch)
    wav = tone(tmp_path / "a.wav", 1.0)
    good = AsrFake(written({"transcript": "hi", "turns": TURNS, "model": "small"}))
    assert client._guarded(good.module, lambda: client.transcribe_own(good.module, wav, tmp_path / "out")) == 0
    assert json.loads((tmp_path / "out" / "transcript.json").read_text())["turns"] == TURNS
    assert good.vol.removed, "the Volume folder is removed"
    cases = [written({"turns": [{"startMs": {"nested": 1}}]}), written({"turns": TURNS * 300}),
             written(None, raw=b"x" * (client.MAX_TRANSCRIPT_BYTES + 1)), written({"turns": TURNS}, code=1)]
    for write in cases:
        bad = AsrFake(write)
        out = tmp_path / f"bad-{len(os.listdir(tmp_path))}"
        assert client._guarded(bad.module, lambda: client.transcribe_own(bad.module, wav, out)) == client.FAILED_EXIT
        assert not (out / "transcript.json").exists()
    monkeypatch.setattr(client, "MAX_AUDIO_BYTES", 10)
    big = AsrFake(written({"turns": TURNS}))
    assert client.transcribe_own(big.module, wav, tmp_path / "o2") == client.FAILED_EXIT and big.spawned == []


def test_the_modal_app_and_the_client_agree_on_caps() -> None:
    client = load_client()
    app = (byok_route.CLIENT.parent / "part2_app.py").read_text(encoding="utf-8")
    assert f'ASR_CLASS = "{client.ASR_CLASS}"' not in app and f"class {client.ASR_CLASS}:" in app
    assert "MAX_AUDIO_BYTES = 40 * 2**20" in app and client.MAX_AUDIO_BYTES == 40 * 2**20
    assert f"MAX_TURNS = {client.MAX_TURNS}" in app and "def transcribe_io(self, key: str, audio: bytes) -> None:" in app
