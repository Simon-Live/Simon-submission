"""One log line at the start and end of every chain stage (TICKET-064, processor.md "Logs").

`stage(work, name, steps, **facts)` logs `stage <name> start: <facts>` and then either `stage <name> end in
<s> s: <part:exit ...>` or `stage <name> failed in <s> s: <reason>; part <n> exit <code>, log <path>: <last
lines>`. Lines go through `applog.log`, so they are redacted, land in `<state>/part7.log` and in the job's own
`steps/part7.log`.
"""

from __future__ import annotations

from contextlib import contextmanager
import logging
from pathlib import Path
import re
import time
from typing import Any, Iterator

from part7 import applog, media

TAIL_LINES = 8


def video_facts(path: Path | str) -> str:
    """`<name> <w>x<h> <fps> fps <ms> ms` of a video, or `<name> unreadable`."""
    name = Path(path).name
    try:
        meta = media.probe(path)
    except ValueError:
        return f"{name} unreadable"
    counted = " (counted)" if meta.get("fps_counted") else ""
    return f"{name} {meta['width']}x{meta['height']} {meta['fps']:g} fps{counted} {meta['duration_ms']} ms"


def facts_text(facts: dict[str, Any]) -> str:
    """`key=value` pairs in the given order; None values are left out."""
    return " ".join(f"{k}={v}" for k, v in facts.items() if v is not None) or "-"


def tail(text: str, n: int = TAIL_LINES) -> str:
    """The last `n` non-empty lines of `text`, joined with ` | `."""
    lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    return " | ".join(lines[-n:])


def step_failure(step: dict[str, Any]) -> str:
    """`part <n> exit <code> (timed out), log <path>: <last lines>` for a failed step."""
    timed = " (timed out)" if step.get("timed_out") else ""
    log = step.get("log") if isinstance(step.get("log"), str) and "\n" not in str(step.get("log")) else None
    where = f", log {log}" if log else ""
    out = tail(getattr(step, "stdout", "") or "")
    return f"part {step.get('part')} exit {step.get('exit')}{timed}{where}" + (f": {out}" if out else "")


def last_meaningful(log_path: Path | str | None, size: int = 4096) -> str:
    """The last log line that says something: not blank, not a progress bar or a rule of dashes."""
    if not log_path:
        return ""
    try:
        with Path(log_path).open("rb") as fh:
            fh.seek(0, 2)
            fh.seek(max(0, fh.tell() - size))
            lines = fh.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return ""
    for line in reversed(lines):
        text = line.strip().split("\r")[-1].strip()
        if len(text) > 3 and re.search(r"[A-Za-z]{3}", text) and "%|" not in text:
            return text[:300]
    return ""


def _slow(name: str, job: str, work: Path | str, seconds: float, failed: bool) -> None:
    limit = applog.slow_stage_limit(name)
    if seconds > limit:
        applog.anomaly("slow_stage", job=job, job_dir=work, stage=name, seconds=seconds, limit=limit,
                       failed=failed or None)


def _exits(steps: list[dict[str, Any]]) -> str:
    return " ".join(f"{s.get('part')}:{s.get('exit')}" for s in steps) or "no part calls"


@contextmanager
def stage(work: Path | str, name: str, steps: list[Any] | None = None, **facts: Any) -> Iterator[dict[str, Any]]:
    """Log the start and end of stage `name` of the job that owns `work`; the yielded dict adds end facts.

    `steps` is the run's step list: the steps added during the stage are summarized at the end, and on a
    failure the last failed one is quoted with its log path and last lines.
    """
    job = applog.job_id_of(work)
    start_n = len(steps) if steps is not None else 0
    applog.log(f"stage {name} start: {facts_text(facts)}", job, work)
    applog.fact(job, "_stage", name)
    t0 = time.monotonic()
    end: dict[str, Any] = {}
    try:
        yield end
    except BaseException as exc:
        new = list(steps[start_n:]) if steps is not None else []
        failed = [s for s in new if s.get("exit") != 0]
        result = getattr(exc, "result", None)
        reason = result.get("error") if isinstance(result, dict) else applog.cause(exc)
        detail = f"; {step_failure(failed[-1])}" if failed else ""
        took = time.monotonic() - t0
        applog.log(f"stage {name} failed in {took:.1f} s: {reason}{detail}", job, work, logging.WARNING)
        _slow(name, job, work, took, True)
        raise
    new = list(steps[start_n:]) if steps is not None else []
    extra = f" {facts_text(end)}" if end else ""
    took = time.monotonic() - t0
    applog.log(f"stage {name} end in {took:.1f} s: exits {_exits(new)}{extra}", job, work)
    _slow(name, job, work, took, False)
