"""Part 2 on a job owner's own Modal account, and the BYOK-only rule of prod (docs/specs/byok-prod.md).

`byok_only()` is true in prod (`prod_mode.is_prod()`) and under PROD_COMPUTE=byok. Then a Part 2 call runs only on the
modal route with the owner's credentials in hand: anything else is refused before it starts (`refusal`), and nothing
falls back, not to this machine, not to the server's Modal account (BYOK-C2, BYOK-H1).

The own route runs `deploy/serverless/p2_client.py --own` under `python -I`. That launcher gives the Modal client a
fresh env (the two token variables, PATH, an empty HOME and the uv cache paths), so the server's env, its Modal
profile and its keys never reach the process that talks to the user's app (BYOK-M1). The client never unpickles a
result: it spawns the call and reads JSON and plain files back from a Modal Volume, with caps (BYOK-C1, BYOK-M2).
"""

from __future__ import annotations

import os
from pathlib import Path
import sys

from part7 import compute_mode, config, own_clients, prod_mode, runner

PROD_COMPUTE_ENV = "PROD_COMPUTE"
CREDS_REFUSED_EXIT = 77  # p2_client.CREDS_REFUSED_EXIT (a test keeps them equal); a Part 2 exit 77 arrives as 1 (R2)
BYOK_REFUSED_EXIT = 78   # the call never started: this server runs model jobs on the owner's credentials only
CLIENT = config.REPO_ROOT / "deploy" / "serverless" / "p2_client.py"
MSG_NEEDS_OWN = ("This server runs takes on your own Modal account. Add your Modal token on the Me page, "
                 "then try again.")


MSG_PAUSED = "Bring-your-own compute is paused. Simon runs the GPU work for now."
MSG_HOST_OFF = "Simon runs takes on its own GPU service, not on this machine."


def byok_only() -> bool:
    """Every model job needs its owner's own credentials (prod, or PROD_COMPUTE=byok), unless serverless mode runs them
    on the operator's workspace (docs/specs/serverless-compute.md)."""
    if compute_mode.serverless():
        return False
    return prod_mode.is_prod() or os.environ.get(PROD_COMPUTE_ENV, "").strip().lower() == "byok"


MSG_NO_HOST_MODELS = "Making a model from photos or a mesh is not available on this server."


def host_models_refused() -> bool:
    """ADR-0024 item 9: under BYOK-only no model runs on this machine, whatever files exist here. The avatar, autorig
    and image3d jobs, the person detector, the muse-fix re-measure and reskin ask this before they start a process
    (prod verify nofallback D1); a Part 2 GPU venv found at HOME's default path changes nothing. Serverless mode too:
    "never on the host" stays."""
    return byok_only() or compute_mode.serverless()


def command(sub: list[str], sha: str) -> list[str]:
    """Part 2 `sub` on the owner's Modal account through the launcher (no server env, no pickle). Inside
    `own_clients.job` the launcher registers itself so Remove, the drain and down.sh can stop it (BYOK-M6)."""
    return [sys.executable, "-I", str(CLIENT), "--own", *own_clients.launcher_args(), "--sha", sha, "--", *sub]


def transcribe_command(wav: Path | str, out: Path | str) -> list[str]:
    """Trainer captions on the owner's Modal account through the same launcher (BYOK-M7)."""
    return [sys.executable, "-I", str(CLIENT), "--own", *own_clients.launcher_args(), "--transcribe",
            "--input", str(wav), "--out", str(out)]


def check_command() -> list[str]:
    """"Check my credentials" through the same launcher: `modal.App.lookup` only."""
    return [sys.executable, "-I", str(CLIENT), "--own", "--check"]


def refusal(first_route: str, own_env: dict[str, str] | None) -> str | None:
    """The reason a Part 2 call may not start here, or None."""
    if compute_mode.serverless():
        return MSG_HOST_OFF if first_route != "modal" else None
    if byok_only() and (first_route != "modal" or own_env is None):
        return MSG_PAUSED if compute_mode.byok_paused() else MSG_NEEDS_OWN
    return None


def refused_step(commit12: str, cwd: Path | str, log: Path, reason: str) -> runner.Step:
    """A failed step for a call that was never started; same keys as `runner.run`, the reason in its log."""
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(f"byok: {reason}\n", encoding="utf-8")
    return runner.Step(part=2, commit=commit12, argv=[], cwd=str(cwd), exit=BYOK_REFUSED_EXIT, timed_out=False,
                       duration_s=0.0, log=str(log), refused=True)


def may_fall_back(own: bool, exit_code: int, fallback_on: bool) -> bool:
    """Whether a failed call runs once more on the other route. Never under BYOK-only. An own-account call only when
    Modal refused the credentials (R1), and then to this machine, never the server's account."""
    if byok_only() or compute_mode.serverless():
        return False
    if own:
        return exit_code == CREDS_REFUSED_EXIT
    return fallback_on
