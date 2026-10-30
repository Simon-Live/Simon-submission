"""Part 6 adapter: child catalog server lifecycle, HTTP client, CLI import, and doctor (TICKET-005, 010)."""

from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from part7 import config, pins, runner


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _normalize_simon6_base(base_path: str | None) -> str:
    b = (base_path or "/").strip()
    if not b.startswith("/"):
        b = "/" + b
    b = b.rstrip("/")
    if not b:
        return "/catalog"
    if b == "/catalog" or b.endswith("/catalog"):
        return b
    return b + "/catalog"


class Child:
    """Manages Part 6's catalog HTTP server as a child subprocess of Part 7."""

    def __init__(
        self,
        catalog_dir: Path | str | None = None,
        base_path: str = "/catalog",
        follow_url: str | None = None,
        *,
        state: Path | str | None = None,
        port: int = 0,
        max_recordings: int = 30,
        lock: pins.Lock | None = None,
        parts_state: Path | str | None = None,
    ) -> None:
        if catalog_dir is not None:
            cpath = Path(catalog_dir)
            if state is None and cpath.name in ("dev", "staging", "app", "state", "simon-part-7"):
                self.catalog_dir = cpath / "catalog"
            else:
                self.catalog_dir = cpath
        elif state is not None:
            self.catalog_dir = Path(state) / "catalog"
        else:
            self.catalog_dir = config.dev_dir() / "catalog"

        self.base_path = _normalize_simon6_base(base_path)
        self.follow_url = follow_url
        self._requested_port = int(port)
        self.port: int = int(port)
        self.max_recordings = int(max_recordings)
        self._lock = lock
        self._parts_state = parts_state
        self._proc: subprocess.Popen[bytes] | None = None
        self._log_handle: Any = None
        self._restarted = False

    @property
    def catalog(self) -> Path:
        return self.catalog_dir

    def url(self, subpath: str = "") -> str:
        """Build an absolute URL targeting this Part 6 child server."""
        s = (subpath or "").strip()
        if not s.startswith("/"):
            s = "/" + s
        if (
            s == self.base_path
            or s.startswith(self.base_path + "/")
            or s.startswith(self.base_path + "?")
        ):
            return f"http://127.0.0.1:{self.port}{s}"
        if s == "/catalog" or s.startswith("/catalog/") or s.startswith("/catalog?"):
            rest = s[len("/catalog") :]
            return f"http://127.0.0.1:{self.port}{self.base_path}{rest}"
        return f"http://127.0.0.1:{self.port}{self.base_path}{s}"

    def _spawn(self) -> int:
        lk = self._lock or pins.load()
        clone6 = lk.path("6", state=self._parts_state)
        self.port = self._requested_port or _free_port()
        self.catalog_dir.mkdir(parents=True, exist_ok=True)

        argv = [
            "python3",
            "-m",
            "part6",
            "serve",
            "--host",
            "127.0.0.1",
            "--port",
            str(self.port),
            "--catalog",
            str(self.catalog_dir.resolve()),
            "--max-recordings",
            str(self.max_recordings),
        ]
        if self.follow_url:
            argv.extend(["--follow-url", self.follow_url])

        env = os.environ.copy()
        env["SIMON6_BASE_PATH"] = self.base_path
        env.pop("PYTHONPATH", None)  # ADR-0006: Part 6 runs from its clone alone, with no SIMON7_* variable
        for name in [n for n in env if n.startswith("SIMON7_")]:
            env.pop(name)
        if not self.follow_url:
            env.pop("SIMON6_FOLLOW_URL", None)

        log_path = self.catalog_dir.parent / "part6.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        self._log_handle = open(log_path, "ab")
        self._proc = subprocess.Popen(
            argv,
            cwd=str(clone6),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=self._log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )

        deadline = time.monotonic() + 15.0
        while time.monotonic() < deadline:
            if self._proc.poll() is not None:
                break
            h = self.health()
            if isinstance(h, dict) and h.get("ok"):
                return self.port
            time.sleep(0.05)
        return self.port

    def start(self) -> int:
        """Start the Part 6 child server (if not already running) and return its port."""
        if self._proc is not None and self._proc.poll() is None:
            return self.port
        self._restarted = False
        return self._spawn()

    def stop(self) -> None:
        """Stop the Part 6 child server."""
        if self._proc is not None:
            if self._proc.poll() is None:
                try:
                    os.killpg(self._proc.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    self._proc.wait(timeout=3.0)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(self._proc.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    self._proc.wait(timeout=1.0)
            self._proc = None
        if self._log_handle is not None:
            try:
                self._log_handle.close()
            except OSError:
                pass
            self._log_handle = None

    def ensure_running(self) -> bool:
        """Return True when the child is healthy; if it exited, restart it at most once."""
        if self._proc is not None and self._proc.poll() is None:
            return self.health() is not None
        if self._restarted:
            return False
        self.stop()
        self._restarted = True
        self._spawn()
        return self._proc is not None and self._proc.poll() is None and self.health() is not None

    def health(self) -> dict[str, Any] | None:
        """Call `GET api/health` on the Part 6 child."""
        if not self.port:
            return None
        req = Request(self.url("api/health"), method="GET")
        try:
            with urlopen(req, timeout=2.0) as resp:
                if resp.status != 200:
                    return None
                data = json.loads(resp.read().decode("utf-8"))
                return data if isinstance(data, dict) else None
        except (URLError, HTTPError, OSError, json.JSONDecodeError):
            return None

    def list_entries(self, query: str = "") -> list[dict[str, Any]]:
        """Call `GET api/entries` on the Part 6 child."""
        q_suffix = f"?q={quote(query)}" if query else ""
        req = Request(self.url(f"api/entries{q_suffix}"), method="GET")
        try:
            with urlopen(req, timeout=5.0) as resp:
                if resp.status != 200:
                    return []
                data = json.loads(resp.read().decode("utf-8"))
                entries = data.get("entries") if isinstance(data, dict) else None
                return entries if isinstance(entries, list) else []
        except (URLError, HTTPError, OSError, json.JSONDecodeError):
            return []

    def get_entry(self, entry_id: str) -> dict[str, Any] | None:
        """Call `GET api/entries/<entry_id>` on the Part 6 child."""
        req = Request(self.url(f"api/entries/{quote(entry_id)}"), method="GET")
        try:
            with urlopen(req, timeout=5.0) as resp:
                if resp.status != 200:
                    return None
                data = json.loads(resp.read().decode("utf-8"))
                return data if isinstance(data, dict) else None
        except (URLError, HTTPError, OSError, json.JSONDecodeError):
            return None

    def get_entry_file(self, entry_id: str, filename: str) -> bytes | None:
        """Call `GET api/entries/<entry_id>/<filename>` on the Part 6 child."""
        req = Request(
            self.url(f"api/entries/{quote(entry_id)}/{quote(filename)}"),
            method="GET",
        )
        try:
            with urlopen(req, timeout=10.0) as resp:
                if resp.status != 200:
                    return None
                return resp.read()
        except (URLError, HTTPError, OSError):
            return None

    def create_entry(
        self,
        name: str,
        category: str,
        duration_ms: int,
    ) -> tuple[int, dict[str, Any]]:
        """Call `POST api/entries` on the Part 6 child and return `(status, body_dict)`."""
        payload = json.dumps(
            {
                "name": name,
                "category": category,
                "duration_ms": int(duration_ms),
            }
        ).encode("utf-8")
        req = Request(
            self.url("api/entries"),
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(req, timeout=10.0) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                return (int(resp.status), body if isinstance(body, dict) else {})
        except HTTPError as exc:
            try:
                body = json.loads(exc.read().decode("utf-8", errors="replace"))
            except json.JSONDecodeError:
                body = {"error": str(exc)}
            return (int(exc.code), body if isinstance(body, dict) else {"error": str(body)})
        except (URLError, OSError) as exc:
            return (503, {"error": f"catalog unavailable: {exc}"})

    def get_job(self, job_id: str) -> tuple[int, dict[str, Any] | None]:
        """Call `GET api/jobs/<job_id>` on the Part 6 child."""
        clean_id = job_id
        if clean_id.startswith("api/jobs/"):
            clean_id = clean_id[len("api/jobs/") :]
        req = Request(self.url(f"api/jobs/{quote(clean_id)}"), method="GET")
        try:
            with urlopen(req, timeout=5.0) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                return (int(resp.status), body if isinstance(body, dict) else None)
        except HTTPError as exc:
            try:
                body = json.loads(exc.read().decode("utf-8", errors="replace"))
            except json.JSONDecodeError:
                body = None
            return (int(exc.code), body if isinstance(body, dict) else None)
        except (URLError, OSError):
            return (503, None)


def doctor(
    target: Path | str,
    work: Path | str,
    lock: pins.Lock | None = None,
    state: Path | str | None = None,
) -> runner.Step:
    """Run `python3 -m part6 doctor <target>` in the Part 6 clone."""
    lk = lock or pins.load()
    clone = lk.path("6", state=state)
    work_p = Path(work)
    return runner.run(
        6,
        ["python3", "-m", "part6", "doctor", str(Path(target).resolve())],
        cwd=clone,
        timeout_s=config.TIMEOUTS["doctor"],
        log_path=work_p / "steps" / "part6_doctor.log",
        lock=lk,
    )


def import_entry(
    catalog_dir: Path | str,
    folder: Path | str,
    name: str,
    category: str,
    parts: dict[str, int],
    work: Path | str,
    lock: pins.Lock | None = None,
    state: Path | str | None = None,
) -> tuple[runner.Step, dict[str, Any] | None]:
    """Import an entry folder into `catalog_dir` using Part 6's `import` CLI with `--part` flags."""
    lk = lock or pins.load()
    clone = lk.path("6", state=state)
    work_p = Path(work)
    part_map = parts or {"keyframes": 1, "skeleton": 3, "animation": 4}

    argv = [
        "python3",
        "-m",
        "part6",
        "import",
        str(Path(folder).resolve()),
        "--catalog",
        str(Path(catalog_dir).resolve()),
        "--name",
        name,
        "--category",
        category,
    ]
    for kind, part_num in part_map.items():
        argv.extend(["--part", f"{kind}={int(part_num)}"])

    step = runner.run(
        6,
        argv,
        cwd=clone,
        timeout_s=config.TIMEOUTS["6"],
        log_path=work_p / "steps" / "part6_import.log",
        lock=lk,
    )
    if step["exit"] == 0 and step.get("stdout"):
        try:
            manifest = json.loads(step["stdout"])
            if isinstance(manifest, dict):
                return (step, manifest)
        except json.JSONDecodeError:
            pass
    return (step, None)
