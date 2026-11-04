"""The per-take "Run on" choice (TICKET-364, parts-harness.md AC-H12): this machine or serverless (Modal).

`modal_configured` says whether this server can offer the serverless route, from the presence of configuration
only: it never opens a token file and never returns a value. A take's choice is stored in its job record as
`run_on` and becomes the first Part 2 route of that job (`p2_pose.job_route`); SIMON7_PART2_FALLBACK still decides
whether a failure runs once more on the other route. Takes only: model import (trainer jobs) gets no choice.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from part7 import applog
from part7.jobs import JobContext, JobFn
from part7.parts import p2_pose

FIELD = "run_on"
CHOICES = {"local": "local", "serverless": "modal"}  # the request's value -> the Part 2 route
MSG_BAD = "Choose This machine or Serverless."
MSG_NOT_SET_UP = "Serverless is not set up on this server. Choose This machine."
TOKEN_ENV = ("MODAL_TOKEN_ID", "MODAL_TOKEN_SECRET")
CONFIG_PATH_ENV = "MODAL_CONFIG_PATH"


def _modal_config_file() -> Path:
    """Where the Modal client keeps its profile (`modal token new`); only its existence is checked."""
    return Path(os.environ.get(CONFIG_PATH_ENV) or Path.home() / ".modal.toml")


def modal_configured() -> bool:
    """True when the serverless route is set up here: SIMON7_PART2_REMOTE=modal, SIMON7_PART2_FALLBACK on, both
    Modal token variables set (not read), or a Modal profile file present (not opened)."""
    if p2_pose.remote() or p2_pose.fallback():
        return True
    if all(os.environ.get(name, "").strip() for name in TOKEN_ENV):
        return True
    return _modal_config_file().is_file()


def parse(doc: dict[str, Any]) -> tuple[str | None, str | None]:
    """`(choice, error)` for a request's optional `run_on`: (None, None) when absent (the job keeps the env route)."""
    value = doc.get(FIELD)
    if value is None:
        return (None, None)
    if not isinstance(value, str) or value not in CHOICES:  # a list or dict is a 400, never a crash
        return (None, MSG_BAD)
    if value == "serverless" and not modal_configured():
        return (None, MSG_NOT_SET_UP)
    return (value, None)


def resumed(value: Any, job_id: str) -> str | None:
    """The choice of a job resumed after a restart, checked again: serverless no longer set up runs on this machine,
    an invalid stored value keeps the env route; each is logged."""
    choice, bad = parse({FIELD: value})
    if bad is None:
        return choice
    if value == "serverless":
        applog.log("resume: serverless is no longer set up; the job runs on this machine", job_id, level=logging.WARNING)
        return "local"
    applog.log(f"resume: stored run_on {str(value)[:40]!r} is not valid; the job keeps the env route", job_id,
               level=logging.WARNING)
    return None


def record(choice: str | None) -> dict[str, str]:
    """The job-record field for `choice`; nothing when the take made no choice."""
    return {FIELD: choice} if choice else {}


def _no_local_gpu() -> bool:
    """True when this machine has no NVIDIA GPU to run Part 2 on (no nvidia-smi), as on a judge's laptop."""
    from part7 import gpu_lock  # here: gpu_lock is not needed for the other choices
    return not gpu_lock.nvidia_smi_path()


def bind(fn: JobFn, choice: str | None) -> JobFn:
    """`fn` with its Part 2 calls on the route `choice` names; `fn` itself when there is no choice. "This machine" on a
    machine with no GPU, while the serverless route is set up (the judges' relay), runs on Modal: the picker defaults
    to This machine, and a local Part 2 there can only fail ("the gpu backend needs CUDA")."""
    if not choice:
        return fn
    chosen = CHOICES[choice]

    def run(ctx: JobContext) -> dict[str, Any]:
        route = chosen
        if route == "local" and p2_pose.remote() and _no_local_gpu():
            applog.log("run_on: This machine has no GPU and serverless is set up; the take runs on Modal")
            route = "modal"
        with p2_pose.job_route_set(route):
            return fn(ctx)

    return run
