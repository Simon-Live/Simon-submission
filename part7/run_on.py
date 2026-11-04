"""The per-take "Run on" choice (TICKET-364, parts-harness.md AC-H12): this machine or serverless (Modal).

`modal_configured` says whether this server can offer the serverless route, from the presence of configuration
only: it never opens a token file and never returns a value. A take's choice is stored in its job record as
`run_on` and becomes the first Part 2 route of that job (`p2_pose.job_route`); SIMON7_PART2_FALLBACK still decides
whether a failure runs once more on the other route. Takes only: model import (trainer jobs) gets no choice.

TICKET-367 (AC-H16): a signed-in user with their own Modal credentials (`modal_creds`) may choose serverless even when
this server has none. Their job reads the credentials when it runs, passes them to its own Modal client only and
records `"modal": "own"`. Outside BYOK-only mode, removed before the run or refused by Modal, the take runs on this
machine, never on the server's Modal account (B2, BYOK-H1).

BYOK-only (docs/specs/byok-prod.md, `byok_route.byok_only`, always in prod): every take runs on its owner's own
account. No choice means serverless; This machine, no credentials, credentials removed, expired or refused, and a
resumed job without them are refused with MSG_NEEDS_OWN, never run here or on the server's account (BYOK-C2).
A job on the owner's credentials records `"compute_owner": true`; ranked and sponsored boards exclude it unless
`prod_mode.policy("byok_ranked")` is on (BYOK-H3, #415; the one check is `challenges.ranks_owner_compute`).

Serverless mode (docs/specs/serverless-compute.md, `SIMON7_COMPUTE=serverless`): every job runs on the operator's Modal
workspace, for a signed-in person only, with no choice and no fallback. BYOK is paused (`compute_mode.byok_paused`): a
stored token is never used and `This machine` is refused.
"""

from __future__ import annotations

import functools
import logging
import os
from pathlib import Path
from typing import Any

from part7 import applog, byok_route, compute_mode, modal_creds, own_clients, serverless_route
from part7.jobs import DRAIN_CUT_REASON, JobContext, JobFailed, JobFn
from part7.parts import p2_pose

FIELD = "run_on"
CHOICES = {"local": "local", "serverless": "modal"}  # the request's value -> the Part 2 route
MSG_BAD = "Choose This machine or Serverless."
MSG_NOT_SET_UP = "Serverless is not set up on this server. Choose This machine."
MSG_OWN_REFUSED = "Your Modal credentials did not work; this take ran on this machine."
MSG_NEEDS_OWN = byok_route.MSG_NEEDS_OWN
MSG_PAUSED = byok_route.MSG_PAUSED
MSG_HOST_OFF = byok_route.MSG_HOST_OFF
MSG_REFUSED_BYOK = ("Modal did not accept your token. Make a new one in your Modal settings, add it on the Me page, "
                    "then try again.")
MSG_KEY_DOWN = modal_creds.MSG_KEY_DOWN  # lifecycle R2: the server's key is unusable; the saved token is kept
MSG_REMOVED = ("Your Modal token was removed while this take ran, so it stopped. Add a token on the Me page, "
               "then record again.")
MODAL_FIELD, OWN = "modal", "own"  # job.json says whose Modal account, never a value
COMPUTE_OWNER_FIELD = "compute_owner"  # top level of the job record; boards exclude it (lane/ph-policy contract)
STAGE = "pose"
TOKEN_ENV = ("MODAL_TOKEN_ID", "MODAL_TOKEN_SECRET")
CONFIG_PATH_ENV = "MODAL_CONFIG_PATH"


def byok_only() -> bool:
    return byok_route.byok_only()


def health_fields() -> dict[str, Any]:
    """For api/health (firm/prod/CONTRACT.md "Health line"): who pays for compute and the idle TTL this build enforces."""
    from part7 import config  # config.byok_idle_ttl_s reads modal_creds.IDLE_TTL_S: one source for the TTL

    if compute_mode.serverless():
        return {"compute": compute_mode.SERVERLESS, "compute_provider": compute_mode.PROVIDER}
    return {"compute": "byok" if byok_only() else "host", "byok_idle_ttl_s": config.byok_idle_ttl_s()}


def config_fields() -> dict[str, Any]:
    """For api/config: what the take screen says about Run on. Never a value of a token."""
    return {"compute": compute_mode.SERVERLESS if compute_mode.serverless() else "default",
            "byok_paused": compute_mode.byok_paused()}


def _modal_config_file() -> Path:
    """Where the Modal client keeps its profile (`modal token new`); only its existence is checked."""
    return Path(os.environ.get(CONFIG_PATH_ENV) or Path.home() / ".modal.toml")


def modal_configured() -> bool:
    """True when the server's own serverless route is set up here: SIMON7_PART2_REMOTE=modal, SIMON7_PART2_FALLBACK
    on, both Modal token variables set (not read), or a Modal profile file present (not opened). Never under BYOK-only:
    the server's account is not offered there."""
    if byok_only() or compute_mode.serverless():  # serverless: the one route, so there is no choice to offer
        return False
    if p2_pose.remote() or p2_pose.fallback():
        return True
    if all(os.environ.get(name, "").strip() for name in TOKEN_ENV):
        return True
    return _modal_config_file().is_file()


def own(state: Path | str | None, user_id: str | None) -> bool:
    """The person has their own Modal credentials stored (presence only). Never while BYOK is paused."""
    if compute_mode.byok_paused():
        return False
    return bool(state is not None and user_id and modal_creds.is_set(state, user_id))


def offered(state: Path | str | None, user_id: str | None) -> bool:
    """Serverless is offered to this person: the server's own route, or their own stored credentials."""
    return modal_configured() or own(state, user_id)


def parse(doc: dict[str, Any], state: Path | str | None = None, user_id: str | None = None) -> tuple[str | None, str | None]:
    """`(choice, error)` for a request's optional `run_on`: (None, None) when absent (the job keeps the env route).
    Under BYOK-only, absent means serverless, and anything but the person's own credentials is an error."""
    value = doc.get(FIELD)
    if value is not None and (not isinstance(value, str) or value not in CHOICES):  # a list or dict is a 400
        return (None, MSG_BAD)
    if compute_mode.serverless():
        if value == "local":
            return (None, MSG_HOST_OFF)
        return ("serverless", None) if user_id else (None, serverless_route.MSG_SIGN_IN)
    if byok_only():
        if compute_mode.byok_paused():
            return (None, MSG_PAUSED)
        if value != "local" and own(state, user_id):
            return ("serverless", None)
        return (None, MSG_KEY_DOWN if value != "local" and modal_creds.key_unavailable(state, user_id) else MSG_NEEDS_OWN)
    if value is None:
        return (None, None)
    if value == "serverless" and not offered(state, user_id):
        return (None, MSG_NOT_SET_UP)
    return (value, None)


def resumed(value: Any, job_id: str, state: Path | str | None = None, user_id: str | None = None) -> str | None:
    """The choice of a job resumed after a restart, checked again: serverless no longer set up runs on this machine,
    an invalid stored value keeps the env route; each is logged. (A job of the owner's own account: `resume_bind`.)"""
    choice, bad = parse({FIELD: value}, state, user_id)
    if bad is None:
        return choice
    if value == "serverless":
        applog.log("resume: serverless is no longer set up; the job runs on this machine", job_id, level=logging.WARNING)
        return "local"
    applog.log(f"resume: stored run_on {str(value)[:40]!r} is not valid; the job keeps the env route", job_id,
               level=logging.WARNING)
    return None


def byok_job(doc: dict[str, Any], state: Path | str | None, user_id: str | None) -> tuple[str | None, str | None, str | None]:
    """`(choice, owner, error)` for a job that offers no "Run on" choice (trainer, group): under BYOK-only it is parsed
    like a take's, so it runs on its owner's own credentials or is refused; in serverless mode too (the operator's
    workspace, signed in only); otherwise `(None, None, None)`."""
    if not byok_only() and not compute_mode.serverless():
        return (None, None, None)
    choice, bad = parse(doc, state, user_id)
    return (choice, owner_for(choice, state, user_id), bad)


def owner_for(choice: str | None, state: Path | str | None, user_id: str | None) -> str | None:
    """The user whose own Modal account a serverless take uses, or None (the server's route, or no choice)."""
    return user_id if choice == "serverless" and own(state, user_id) else None


def record(choice: str | None, owner: str | None = None) -> dict[str, Any]:
    """The job-record fields for `choice`; nothing when the take made no choice. A job on the owner's own credentials
    gets `"modal": "own"` (never a value) and `"compute_owner": true`, the field ranked and sponsored boards exclude
    (BYOK-H3; the board contract of lane/ph-policy af9be2c2)."""
    if not choice:
        return {}
    if not owner:
        return {FIELD: choice}
    return {FIELD: choice, MODAL_FIELD: OWN, COMPUTE_OWNER_FIELD: True}


def _refusing(reason: str) -> JobFn:
    def refuse(ctx: JobContext) -> dict[str, Any]:
        applog.log(f"run on: refused ({reason})", ctx.id, level=logging.WARNING)
        raise JobFailed(STAGE, reason, "byok")

    return refuse


def _on_operator(fn: JobFn, state: Path | str) -> JobFn:
    """The job on the operator's workspace; a call Modal would not run ends it with a plain reason, never elsewhere."""

    def run(ctx: JobContext) -> dict[str, Any]:
        with p2_pose.job_route_set("modal"), serverless_route.job(state, ctx.id) as stops:
            try:
                out = fn(ctx)
            except JobFailed as exc:
                if stops:
                    raise JobFailed(STAGE, serverless_route.MESSAGES[stops[0]], "serverless") from None
                if getattr(ctx, "draining", False):
                    raise JobFailed(exc.stage, DRAIN_CUT_REASON, "serverless") from None
                raise
        if stops:
            raise JobFailed(STAGE, serverless_route.MESSAGES[stops[0]], "serverless")
        return out  # type: ignore[return-value]

    return run


def _on_route(fn: JobFn, route: str) -> JobFn:
    def run(ctx: JobContext) -> dict[str, Any]:
        with p2_pose.job_route_set(route):
            return fn(ctx)  # type: ignore[return-value]

    return run


def bind(fn: JobFn, choice: str | None, state: Path | str | None = None, owner: str | None = None) -> JobFn:
    """`fn` with its Part 2 calls on the route `choice` names; `fn` itself when there is no choice. With `owner`, the
    owner's credentials are read when the job runs (not now), so a Remove before the run takes effect. Under
    BYOK-only a job without an owner is refused when it runs. In serverless mode `choice` and `owner` change nothing."""
    if compute_mode.serverless():
        return _refusing(MSG_HOST_OFF) if state is None else _on_operator(fn, state)
    if byok_only() and (owner is None or state is None or choice != "serverless"):
        return _refusing(MSG_NEEDS_OWN)
    if not choice:
        return fn
    route = CHOICES[choice]
    if os.environ.get("SIMON_PART2_RELAY", "").strip() and owner is None:  # the judges' relay: a saved "This machine" does not run locally
        if route != "modal":
            applog.log("run_on: the take asked for This machine; Part 2 runs on the server's serverless route")
        return fn
    if owner is None or state is None or route != "modal":
        return _on_route(fn, route)

    def run_own(ctx: JobContext) -> dict[str, Any]:
        env = modal_creds.env_for(state, owner)  # also resets the idle clock (BYOK-H2)
        if env is None and byok_only():
            return _refusing(MSG_KEY_DOWN if modal_creds.key_unavailable(state, owner) else MSG_NEEDS_OWN)(ctx)
        if env is None:  # removed or expired before the run: this machine, never the server's own Modal account
            applog.log("run on: the owner's Modal credentials are gone; the take runs on this machine", ctx.id,
                       level=logging.WARNING)
            return _on_route(fn, "local")(ctx)
        gate = functools.partial(modal_creds.launch_gate, state, owner)  # go-live BYOK N1: read again at each start
        with p2_pose.job_route_set("modal"), own_clients.job(state, owner), p2_pose.job_modal_env_set(env, gate) as refused:
            try:
                out = fn(ctx)
            except JobFailed as exc:
                if refused[0] and byok_only():  # say why: the step did not fall back (byok_route.may_fall_back)
                    raise JobFailed(STAGE, MSG_REFUSED_BYOK, "byok") from None
                cut = _cut_reason(ctx, state, owner)
                if cut is not None:  # go-live BYOK N2: a client stopped by Remove or the drain, said plainly
                    raise JobFailed(exc.stage, cut, "byok") from None
                raise
        if refused[0] and byok_only():
            return _refusing(MSG_REFUSED_BYOK)(ctx)
        if refused[0]:
            applog.log("run on: Modal refused the owner's credentials; the take ran on this machine", ctx.id,
                       level=logging.WARNING)
            if isinstance(out, dict) and isinstance(out.get("result"), dict):
                out["result"]["run_on_note"] = MSG_OWN_REFUSED
        return out  # type: ignore[return-value]

    return run_own


def _cut_reason(ctx: JobContext, state: Path | str, owner: str) -> str | None:
    """Why a take on the owner's account stopped part way, when it was cut off and not failed: the token went
    (Remove, account deletion; MSG_REMOVED names the Me page) or the server drained for a restart. None otherwise:
    the step's own reason stands."""
    if modal_creds.key_unavailable(state, owner):
        return None
    if not modal_creds.is_set(state, owner):
        return MSG_REMOVED
    return DRAIN_CUT_REASON if getattr(ctx, "draining", False) else None


def resume_bind(fn: JobFn, record_: dict[str, Any], state: Path | str | None, owner: str | None) -> JobFn:
    """The job function of a job resumed after a restart (resume.py). A job of the owner's own account stays on it,
    or runs on this machine when the owner or their credentials are gone (deleted account, removed, expired, failed
    owner lookup), never on the server's Modal account (B2); under BYOK-only it is refused instead."""
    job_id = str(record_.get("id") or "")
    if compute_mode.byok_paused() and record_.get(MODAL_FIELD) == OWN:
        return _refusing(MSG_PAUSED)
    if compute_mode.serverless():
        return bind(fn, "serverless", state, None)
    if record_.get(MODAL_FIELD) == OWN:
        if owner is not None and own(state, owner):
            return bind(fn, "serverless", state, owner)
        applog.log("resume: the owner's Modal credentials are gone; the job "
                   + ("is refused" if byok_only() else "runs on this machine"), job_id, level=logging.WARNING)
        return bind(fn, "local", state, None)
    if byok_only():
        return _refusing(MSG_NEEDS_OWN)
    return bind(fn, resumed(record_.get(FIELD), job_id, state, None), state, None)
