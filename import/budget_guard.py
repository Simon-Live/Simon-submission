"""Local spending guard for the Meta Model API.

Meta only offers a monthly email alert, not a hard cap, so every API call goes
through here. Spend is appended to .budget/ledger.jsonl at the repo root.

- Calls are refused once recorded spend reaches META_BUDGET_USD.
- Every META_BUDGET_REMIND_EVERY_USD crossed triggers a reminder (stderr,
  .budget/alerts.log, and a macOS notification when available).

Only spend made through this module is counted: Playground use, other machines,
and teammates' keys do not show up here. Check dev.meta.ai/usage for the truth.

Usage:
    from budget_guard import call
    resp = call("/chat/completions", {"model": "muse-spark-1.3", "messages": [...]})

    python import/budget_guard.py status
"""

from __future__ import annotations

import fcntl
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUDGET_DIR = ROOT / ".budget"
LEDGER = BUDGET_DIR / "ledger.jsonl"
ALERTS = BUDGET_DIR / "alerts.log"
BASE_URL = "https://api.meta.ai/v1"

# USD per 1M tokens: (cached input, input, output). From dev.meta.ai/docs/pricing-rate-limits, Oct 26 2026.
TOKEN_PRICES = {
    "muse-wonder-1.0": (0.20, 4.00, 20.00),
    "muse-spark-1.3": (0.15, 1.25, 4.25),
    "muse-spark-1.2": (0.15, 1.25, 4.25),
    "muse-spark-1.1": (0.15, 1.25, 4.25),
    "muse-spark-1.3-contributor": (0.002, 0.10, 0.20),
    "muse-spark-1.2-contributor": (0.002, 0.10, 0.20),
}
SAM_IMAGE_USD = 2.50 / 1000
SAM_FRAME_USD = 0.20 / 1000
SAM_MIN_FRAMES = 50
TRANSCRIBE_USD_PER_SECOND = 0.18 / 3600
MUSE_IMAGE_USD = 0.01


class BudgetExceeded(RuntimeError):
    pass


def _load_env() -> None:
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


_load_env()


def limit_usd() -> float:
    return float(os.environ.get("META_BUDGET_USD", "120"))


def remind_every_usd() -> float:
    return float(os.environ.get("META_BUDGET_REMIND_EVERY_USD", "20"))


@contextmanager
def _locked():
    BUDGET_DIR.mkdir(exist_ok=True)
    with open(BUDGET_DIR / ".lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def spent_usd() -> float:
    if not LEDGER.exists():
        return 0.0
    with open(LEDGER) as f:
        return sum(json.loads(line)["usd"] for line in f if line.strip())


def check(estimate_usd: float = 0.0) -> None:
    """Raise BudgetExceeded if this call could push spend past the limit."""
    spent, limit = spent_usd(), limit_usd()
    if spent + estimate_usd >= limit:
        raise BudgetExceeded(
            f"Meta API budget reached: ${spent:.2f} spent + ${estimate_usd:.2f} estimated "
            f">= ${limit:.2f} limit. Raise META_BUDGET_USD in .env to continue."
        )


def _remind(message: str) -> None:
    print(f"[budget] {message}", file=sys.stderr)
    with open(ALERTS, "a") as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")
    if sys.platform == "darwin":
        script = f'display notification "{message}" with title "Simon: Meta API spend"'
        subprocess.run(["osascript", "-e", script], capture_output=True, check=False)


def record(model: str, usd: float, **details) -> float:
    """Append a cost entry and fire a reminder for each threshold crossed. Returns total spent."""
    with _locked():
        before = spent_usd()
        entry = {"ts": time.time(), "model": model, "usd": round(usd, 6), **details}
        with open(LEDGER, "a") as f:
            f.write(json.dumps(entry) + "\n")
        after = before + usd
    step = remind_every_usd()
    if step > 0:
        for n in range(int(before // step) + 1, int(after // step) + 1):
            _remind(f"Spent ${n * step:.0f} of ${limit_usd():.0f} (total now ${after:.2f}).")
    return after


def token_cost(model: str, usage: dict) -> float:
    cached_price, input_price, output_price = TOKEN_PRICES[model]
    # Chat Completions uses prompt/completion_tokens; Responses and Messages use input/output_tokens.
    input_tokens = usage.get("prompt_tokens", usage.get("input_tokens", 0))
    output_tokens = usage.get("completion_tokens", usage.get("output_tokens", 0))
    details = usage.get("prompt_tokens_details") or usage.get("input_tokens_details") or {}
    cached = details.get("cached_tokens", usage.get("cached_tokens", 0)) or 0
    return ((input_tokens - cached) * input_price + cached * cached_price + output_tokens * output_price) / 1e6


def response_cost(model: str, response: dict) -> float:
    usage = response.get("usage") or {}
    if model in TOKEN_PRICES:
        return token_cost(model, usage)
    if model == "sam-3.1":
        if "video_frames_processed" in usage:
            return max(usage["video_frames_processed"], SAM_MIN_FRAMES) * SAM_FRAME_USD
        return SAM_IMAGE_USD
    if model == "muse-image-1.0":
        return MUSE_IMAGE_USD * max(len(response.get("data", [])), 1)
    raise KeyError(f"No price for model {model!r}; add it to budget_guard.py")


def call(path: str, payload: dict, estimate_usd: float = 0.0, timeout: float = 600) -> dict:
    """POST to the Meta Model API with the budget checked before and recorded after."""
    check(estimate_usd)
    key = os.environ.get("MODEL_API_KEY")
    if not key:
        raise RuntimeError("MODEL_API_KEY is not set (see .env.example)")
    request = urllib.request.Request(
        BASE_URL + path,
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as resp:
        body = json.load(resp)
    model = payload.get("model") or body.get("model", "")
    record(model, response_cost(model, body), path=path, usage=body.get("usage"))
    return body


def record_transcription(seconds: float, model: str = "muse-voice-transcribe-1.0") -> float:
    """Transcription responses carry no usage block; record by audio length instead."""
    return record(model, int(seconds) * TRANSCRIBE_USD_PER_SECOND, audio_seconds=int(seconds))


def status() -> str:
    spent, limit, step = spent_usd(), limit_usd(), remind_every_usd()
    next_reminder = (int(spent // step) + 1) * step if step > 0 else None
    lines = [
        f"Spent:          ${spent:.4f}",
        f"Limit:          ${limit:.2f}  ({spent / limit:.1%} used)",
        f"Next reminder:  ${next_reminder:.0f}" if next_reminder else "Reminders off",
        f"Ledger:         {LEDGER}",
    ]
    if LEDGER.exists():
        by_model: dict[str, float] = {}
        with open(LEDGER) as f:
            for line in f:
                if line.strip():
                    e = json.loads(line)
                    by_model[e["model"]] = by_model.get(e["model"], 0) + e["usd"]
        lines += [f"  {m:<28} ${v:.4f}" for m, v in sorted(by_model.items(), key=lambda kv: -kv[1])]
    return "\n".join(lines)


if __name__ == "__main__":
    if sys.argv[1:] == ["status"]:
        print(status())
    else:
        print("usage: python import/budget_guard.py status", file=sys.stderr)
        sys.exit(2)
