"""Private mode (TICKET-147): fault wording by a local Muse Glimmer through Part 5's `local-llm` backend.

Spec: docs/specs/private-mode.md. ADR-0005 and ASM-007 (Part 5 backend, Ollama). Stdlib only.
"""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import shutil
import urllib.request
from typing import Callable, Iterator, Mapping

from part7 import applog, gpu_lock

SWITCH_ENV = "SIMON7_PRIVATE"
MODEL_ENV = "SIMON7_PRIVATE_MODEL"
DEFAULT_MODEL = "muse-glimmer:30b"  # ollama.com/library/muse-glimmer, 18 GB, Apache 2.0
OLLAMA_HOST = "127.0.0.1:11434"  # fixed in Part 5 local_llm.URL; the check must probe the same address
PART5_MODEL_ENV = "PART5_OLLAMA_MODEL"
PART5_BUDGET_ENV = "PART5_PHRASING_BUDGET_S"
BUDGET_S = "300"  # a 30B model that is partly on the CPU needs more than Part 5's 20 s default
PART5_TIMEOUT_ENV = "PART5_LOCAL_LLM_TIMEOUT_S"
TIMEOUT_S = "90"  # measured: 43 s for one fault-sized call on CPU with thinking off (demos/rubric/147/direct_timing.json)
PART5_THINK_ENV = "PART5_LOCAL_LLM_THINK"
THINK = "0"  # thinking on spent all 256 tokens and returned no line (124 s CPU, 74 s default placement)
FLOOR_ENV = "SIMON7_PRIVATE_MIN_FREE_MIB"
# Measured (demos/rubric/147/vram.json): loading muse-glimmer:30b took 18275 MiB of GPU memory by nvidia-smi
# (ollama ps: 16001 MiB, 32768 context). 20480 leaves about 2 GiB of margin and keeps it off a warm Part 2 worker.
DEFAULT_FLOOR_MIB = 20480
WAIT_ENV = "SIMON7_PRIVATE_WAIT_S"
DEFAULT_WAIT_S = 300.0  # a private take waits this long for the GPU, then takes the standard wording
# Capability probe (TICKET-147): Part 5 documents the last local-phrasing fix (the 2048-token allowance) as this setting
# in its published developer guide. Part 5 rewrites history on publish, so a commit id cannot be used (07a7fd8 is not in
# its published history); the documented setting is the contract.
PART5_FIX_MARKER = "PART5_LOCAL_LLM_MAX_TOKENS"
PART5_FIX_DOC = Path("docs") / "dev" / "DEVELOPING.md"
OLD_PART5_NOTE = "Private wording needs a newer Part 5; this take used the standard wording."
KEEP_ALIVE = "10m"
LOAD_TIMEOUT_S = 600.0
PROBE_TIMEOUT_S = 3.0
TRUE_VALUES = {"1", "true", "yes", "on"}
EXTRA_BIN_DIRS = (Path.home() / ".local" / "bin", Path.home() / ".local" / "ollama" / "bin")


@dataclass(frozen=True)
class Plan:
    """What private mode asks of the Part 5 call: `argv` and `env` to add, and `note` for the job's notes."""

    active: bool
    argv: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    note: str | None = None
    model: str | None = None


def enabled(env: Mapping[str, str] | None = None, job_flag: bool | None = None) -> bool:
    """True when the job asks for private mode, else when `SIMON7_PRIVATE` is a true value (AC-001)."""
    if job_flag is not None:
        return bool(job_flag)
    source = os.environ if env is None else env
    return source.get(SWITCH_ENV, "").strip().lower() in TRUE_VALUES


def model_name(env: Mapping[str, str] | None = None) -> str:
    source = os.environ if env is None else env
    return source.get(MODEL_ENV, "").strip() or DEFAULT_MODEL


def _fetch_tags(host: str) -> dict:
    with urllib.request.urlopen(f"http://{host}/api/tags", timeout=PROBE_TIMEOUT_S) as response:  # noqa: S310
        return json.loads(response.read())


def _has_binary() -> bool:
    path = os.pathsep.join([os.environ.get("PATH", ""), *(str(d) for d in EXTRA_BIN_DIRS)])
    return shutil.which("ollama", path=path) is not None


def local_status(model: str, host: str = OLLAMA_HOST, fetch: Callable[[str], dict] | None = None,
                 has_binary: Callable[[], bool] = _has_binary) -> str | None:
    """None when the local model can be used, else a short reason (AC-003). Never raises."""
    if not has_binary():
        return "ollama not found"
    try:
        tags = (fetch or _fetch_tags)(host)
    except Exception:  # any probe failure is a reason, not an error
        return "ollama is not answering"
    names = {m.get("name") for m in tags.get("models", []) if isinstance(m, dict)}
    wanted = {model} if ":" in model else {model, f"{model}:latest"}
    if not names & wanted:
        return f"model {model} is not pulled"
    return None


def part5_has_fix(clone: Path | str) -> bool:
    """True when the clone's developer guide documents `PART5_FIX_MARKER`. Reads one text file, imports no Part 5 code.

    Any failure (no clone, no guide, unreadable) is False: the pin cannot phrase locally.
    """
    try:
        text = (Path(clone) / PART5_FIX_DOC).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return PART5_FIX_MARKER in text


def plan(env: Mapping[str, str] | None = None, job_flag: bool | None = None,
         status_fn: Callable[[str], str | None] | None = None, part5_clone: Path | str | None = None,
         supports_fn: Callable[[Path | str], bool] = part5_has_fix) -> Plan:
    """The Part 5 flags and environment for this job (AC-002 to AC-004, AC-007).

    With `part5_clone` given, a Part 5 without the local-phrasing fix keeps the mode inert (standard wording).
    """
    if not enabled(env, job_flag):
        return Plan(active=False)
    if part5_clone is not None and not supports_fn(part5_clone):
        return Plan(active=False, argv=["--phrasing", "template"], note=OLD_PART5_NOTE)
    model = model_name(env)
    reason = (status_fn or local_status)(model)
    if reason:
        return Plan(active=False, argv=["--phrasing", "template"],
                    note=f"private mode: {reason}, template wording used")
    base_path = (os.environ if env is None else env).get("PATH", "")
    path = os.pathsep.join([*(str(d) for d in EXTRA_BIN_DIRS), base_path]).rstrip(os.pathsep)
    return Plan(active=True, argv=["--phrasing", "local-llm"], model=model,
                env={PART5_MODEL_ENV: model, PART5_BUDGET_ENV: BUDGET_S,
                     PART5_TIMEOUT_ENV: TIMEOUT_S, PART5_THINK_ENV: THINK, "PATH": path})


def _post(host: str, body: dict) -> None:
    request = urllib.request.Request(
        f"http://{host}/api/generate", data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=LOAD_TIMEOUT_S) as response:  # noqa: S310
        response.read()


def _log(msg: str, job_dir: Path | str | None) -> None:
    job = applog.job_id_of(job_dir) if job_dir is not None else None
    applog.log(msg, job, job_dir)


def _number(env: Mapping[str, str] | None, name: str, default: float) -> float:
    try:
        value = float((os.environ if env is None else env).get(name, "").strip())
    except ValueError:
        return default
    return value if value >= 0 else default


@contextmanager
def gpu_turn(the_plan: Plan, job_dir: Path | str | None = None, lock_path: Path | str | None = None,
             post: Callable[[str, dict], None] | None = None, host: str = OLLAMA_HOST,
             memory_fn: Callable[[], int | None] | None = None,
             env: Mapping[str, str] | None = None) -> Iterator[Plan]:
    """Wait for the GPU lock and a free-memory floor, load the model, yield the plan to use, unload, release.

    AC-005, AC-008. The yielded plan is `the_plan`, or a template plan with a note when the floor
    (`SIMON7_PRIVATE_MIN_FREE_MIB`, default 20480) was not met within `SIMON7_PRIVATE_WAIT_S`: the model is then
    not loaded and the caller must build the Part 5 call from the yielded plan. Inactive plans pass through.
    """
    if not the_plan.active:
        yield the_plan
        return
    send = post or _post
    floor = int(_number(env, FLOOR_ENV, DEFAULT_FLOOR_MIB))
    wait = _number(env, WAIT_ENV, DEFAULT_WAIT_S)
    stack = ExitStack()
    try:
        stack.enter_context(gpu_lock.acquire(lock_path=lock_path, min_free_mib=floor, timeout_s=wait,
                                             memory_fn=memory_fn, job_dir=job_dir))
    except TimeoutError:
        note = f"private mode: the GPU was not free ({floor} MiB needed) within {wait:g} s, template wording used"
        _log(note, job_dir)
        yield Plan(active=False, argv=["--phrasing", "template"], note=note)
        return
    with stack:
        try:
            send(host, {"model": the_plan.model, "prompt": "", "keep_alive": KEEP_ALIVE})
        except Exception as exc:  # a failed load only means per-fault template fallback inside Part 5
            _log(f"private mode: model load failed ({type(exc).__name__}), Part 5 falls back per fault", job_dir)
        try:
            yield the_plan
        finally:
            try:
                send(host, {"model": the_plan.model, "prompt": "", "keep_alive": 0})
            except Exception as exc:  # an unload that fails leaves the daemon's own keep-alive to free the model
                _log(f"private mode: model unload failed ({type(exc).__name__}), keep-alive {KEEP_ALIVE} frees it", job_dir)


def recorded_backend(analysis: Mapping) -> tuple[str, str | None]:
    """`(backend, model)` that phrased the take, read from Part 5's `phrasing` record (AC-006)."""
    record = analysis.get("phrasing") or {}
    for entry in record.get("faults") or []:
        if entry.get("backend") == "local-llm":
            return "local-llm", entry.get("model")
    return "template", None
