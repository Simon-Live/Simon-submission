"""A fake of Modal's client for tests and the local QA run: no network, no account. It keeps one workspace in a folder
(`FAKE_MODAL_ROOT`), so the real p2_client.py runs against it in a real child process. `<root>/mode` steers it:
ok, never-starts, over-limit, refused, no-app, wrong-version, no-result, no-delete, asr-failed, asr-bad. `<root>/read-fault.json` makes reads of one file fail (`_read_fault`) and
`<root>/reads.log` names every file read. `<root>/calls.jsonl` records every spawn with the
tokens the process held, so a test can compare them. Never used in a production path: only tests/part7/fake_modal/python
puts it on a module path."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
from pathlib import Path
import shutil
from types import SimpleNamespace

ROOT = Path(os.environ["FAKE_MODAL_ROOT"])


class exception:  # noqa: N801 (the real name)
    class NotFoundError(Exception):
        pass

    class AuthError(Exception):
        pass

    class PermissionDeniedError(Exception):
        pass

    class ResourceExhaustedError(Exception):
        pass

    class ExecutionError(Exception):
        pass

    class ServiceError(Exception):
        pass


def _mode() -> str:
    found = ROOT / "mode"
    return found.read_text(encoding="utf-8").strip() if found.exists() else "ok"


def _read_fault(name: str) -> dict | None:
    """`read-fault.json` is `{"file", "times" (null: every read), "error" (a class of `exception`), "text", "partial"}`:
    what this read of `name` fails with, or None."""
    found = ROOT / "read-fault.json"
    doc = json.loads(found.read_text(encoding="utf-8")) if found.exists() else None
    if doc is None or doc["file"] != name or doc["times"] == 0:
        return None
    if doc["times"] is not None:
        found.write_text(json.dumps({**doc, "times": doc["times"] - 1}), encoding="utf-8")
    return doc


def _guard() -> None:
    if _mode() == "refused":
        raise exception.AuthError("the token ak-must-not-be-printed was refused")


class _Batch:
    def __init__(self, vol: "_Volume") -> None:
        self.vol = vol

    def put_file(self, source: object, remote: str) -> None:
        dest = self.vol.base / remote.lstrip("/")
        dest.parent.mkdir(parents=True, exist_ok=True)
        if hasattr(source, "read"):
            dest.write_bytes(source.read())
        else:
            shutil.copyfile(source, dest)


class _Volume:
    def __init__(self, name: str) -> None:
        self.base = ROOT / "volumes" / name
        self.base.mkdir(parents=True, exist_ok=True)

    @contextlib.contextmanager
    def batch_upload(self, force: bool = False):
        yield _Batch(self)

    def read_file(self, path: str):
        found = self.base / path.lstrip("/")
        with (ROOT / "reads.log").open("a", encoding="utf-8") as fh:
            fh.write(found.name + "\n")
        if not found.is_file():
            raise FileNotFoundError(path)
        fault = _read_fault(found.name)
        data = found.read_bytes()
        if fault is not None:
            if fault.get("partial"):
                yield data[:len(data) // 2]
            raise getattr(exception, fault["error"])(fault["text"])
        yield data

    def iterdir(self, path: str, recursive: bool = True):
        base = self.base / path.lstrip("/")
        if not base.is_dir():
            raise FileNotFoundError(path)
        for item in sorted(base.rglob("*")):
            yield SimpleNamespace(path=str(item.relative_to(self.base)), type=2 if item.is_dir() else 1,
                                  size=item.stat().st_size)

    def remove_file(self, path: str, recursive: bool = False) -> None:
        if _mode() == "no-delete":
            raise RuntimeError("the delete did not reach Modal")
        found = self.base / path.lstrip("/")
        if found.is_dir():
            shutil.rmtree(found)
        elif found.exists():
            found.unlink()
        else:
            raise FileNotFoundError(path)


class Volume:
    @staticmethod
    def from_name(name: str, create_if_missing: bool = False, version: int | None = None) -> _Volume:
        _guard()
        if not create_if_missing and not (ROOT / "volumes" / name).is_dir():
            raise exception.NotFoundError(name)
        return _Volume(name)


class App:
    @staticmethod
    def lookup(name: str, create_if_missing: bool = False) -> object:
        _guard()
        if _mode() == "no-app":
            raise exception.NotFoundError(name)
        return object()


class _Call:
    def cancel(self) -> None:
        with (ROOT / "cancelled").open("a", encoding="utf-8") as fh:
            fh.write("1\n")


class _Fn:
    def __init__(self, app: str = "") -> None:
        self.app = app

    def spawn(self, key: str, argv: list[str], names: list[str], sha: str) -> _Call:
        mode = _mode()
        _guard()
        if mode == "over-limit":
            raise exception.ResourceExhaustedError("over a limit")
        with (ROOT / "calls.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"key": key, "app": self.app, "argv": argv, "names": names, "sha": sha,
                                 "had_token": bool(os.environ.get("MODAL_TOKEN_SECRET")),
                                 "token_sha": hashlib.sha256(os.environ.get("MODAL_TOKEN_SECRET", "").encode()).hexdigest(),
                                 "inputs": sorted(p.name for p in (ROOT / "volumes/simon-part2-store" / key / "in").glob("*"))}) + "\n")
        if mode == "never-starts":
            return _Call()
        folder = ROOT / "volumes" / "simon-part2-store" / key
        (folder / "started.json").write_text("{}", encoding="utf-8")
        shutil.rmtree(folder / "in", ignore_errors=True)
        if mode == "no-result":
            return _Call()
        (folder / "out").mkdir()
        (folder / "out" / "result.txt").write_text("fake", encoding="utf-8")
        (folder / "log.txt").write_text("part2: done\n", encoding="utf-8")
        (folder / "metrics.json").write_text(json.dumps({"container_cold": True, "container_up_s": 40.5, "gpu_s": 90.0,
                                                         "peak_gpu_mib": 5000, "peak_ram_mib": 9000, "note": "x" * 9}))
        (folder / "result.json").write_text(json.dumps({"exit": 0}), encoding="utf-8")
        return _Call()


class _Asr:
    def spawn(self, key: str) -> _Call:  # AC-SC15: a key and nothing else; any other argument fails here
        mode = _mode()
        _guard()
        folder = ROOT / "volumes" / "simon-part2-store" / key
        with (ROOT / "calls.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"key": key, "asr": True, "inputs": sorted(p.name for p in (folder / "in").glob("*"))}) + "\n")
        if mode == "never-starts":
            return _Call()
        shutil.rmtree(folder / "in", ignore_errors=True)
        if mode == "asr-failed":
            (folder / "result.json").write_text(json.dumps({"exit": 1}), encoding="utf-8")
            return _Call()
        doc = "not a transcript" if mode == "asr-bad" else json.dumps(
            {"transcript": "lift your arms", "turns": [{"startMs": 0, "endMs": 900, "transcript": "lift your arms"}]})
        (folder / "transcript.json").write_text(doc, encoding="utf-8")
        (folder / "result.json").write_text(json.dumps({"exit": 0}), encoding="utf-8")
        return _Call()


class Cls:
    @staticmethod
    def from_name(app: str, cls: str):
        return lambda: SimpleNamespace(run_part2_store=_Fn(app), transcribe_store=_Asr())
