"""api-sam31: SAM 3.1 through the Meta Model API (part2.track's API path via part2.meta_api).

Spec: docs/specs/tracker-registry.md (Trackers, Budget, Keys). ADR-0003.

The key file MODEL_API_KEY is read through part2.keys at use and set as MODEL_API_KEY in this process's own
environment for the duration of the call only (part2.meta_api reads it there); the prior value is restored.

Budgets, every one of which must accept the reservation (part2.meta_api.Budget guard kept):
- run: META_BUDGET_USD (default 25) on META_SPEND_LEDGER (default ~/.simon/meta_spend.jsonl);
- staging job: the job worker sets META_SPEND_LEDGER=~/.simon/meta_spend_staging.jsonl and META_BUDGET_USD=10,
  plus PART2_JOB_LEDGER, a ledger in the job directory capped at PART2_JOB_BUDGET_USD (default 0.50).
"""
import contextlib
import os

from part2.trackers import BudgetReached, Tracker, call_with_key

KEY = "MODEL_API_KEY"
RUN_BUDGET_USD = 25.0
JOB_BUDGET_USD = 0.50
JOB_LEDGER_ENV = "PART2_JOB_LEDGER"
JOB_BUDGET_ENV = "PART2_JOB_BUDGET_USD"


class Budgets:
    """A meta_api.Budget look-alike over several ledgers: reserve asks each, record writes each."""

    def __init__(self, budgets):
        self.budgets = list(budgets)

    def refusing(self, usd: float):
        """The first budget that would refuse `usd`, else None."""
        return next((b for b in self.budgets if usd > 0 and b.spent() + usd > b.limit), None)

    def reserve(self, usd: float, what: str) -> None:
        for b in self.budgets:
            b.reserve(usd, what)

    def record(self, usd: float, what: str, model: str) -> float:
        return [b.record(usd, what, model) for b in self.budgets][0]

    def spent(self) -> float:
        return self.budgets[0].spent()


def budgets(job_ledger=None) -> Budgets:
    from part2 import meta_api

    run_limit = meta_api._env("META_BUDGET_USD", None)
    out = [meta_api.Budget(limit_usd=float(run_limit) if run_limit else RUN_BUDGET_USD)]
    job_ledger = job_ledger or os.environ.get(JOB_LEDGER_ENV)
    if job_ledger:
        out.append(meta_api.Budget(limit_usd=float(os.environ.get(JOB_BUDGET_ENV) or JOB_BUDGET_USD),
                                   remind_every_usd=0, ledger=job_ledger))
    return Budgets(out)


@contextlib.contextmanager
def _in_env(name: str, value: str):
    prior = os.environ.get(name)
    os.environ[name] = value
    try:
        yield
    finally:
        if prior is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = prior


class ApiSam31(Tracker):
    name = "api-sam31"
    key = KEY
    mask_source = "sam"
    detector = "sam-3.1 text prompt"
    modules = ("meta_sam_parser",)
    prompt = "person"

    def __init__(self, client=None, job_ledger=None, **_):
        self.client = client  # callable(frames_dir, recs, budget=) -> detections; default track.api_tracker
        self.job_ledger = job_ledger
        self.spend_usd = None

    @staticmethod
    def estimate(n_frames) -> float:
        from part2 import meta_api

        return meta_api.sam_video_cost(int(n_frames or 0))

    def available(self, n_frames=None):
        ok, reason = super().available(n_frames)
        if ok and budgets(self.job_ledger).refusing(self.estimate(n_frames)):
            return False, "budget"
        return ok, reason

    def require(self, n_frames=None) -> None:
        b = budgets(self.job_ledger).refusing(self.estimate(n_frames))
        if b is not None and super().available(n_frames)[0]:
            raise BudgetReached(self.name, b.limit, b.ledger)
        super().require(n_frames)

    def models(self):
        return [{"name": "sam-3.1", "source": "Meta Model API https://api.meta.ai/v1", "weights_sha256": None,
                 "licence": "Meta Model API terms (ADR-0005)"}]

    def params(self):
        return {"prompt": self.prompt}

    def detect(self, frames_dir, frame_records):
        from part2 import meta_api, track

        guard = budgets(self.job_ledger)
        est = self.estimate(len(frame_records))
        b = guard.refusing(est)
        if b is not None:
            raise BudgetReached(self.name, b.limit, b.ledger)
        client = self.client or track.load_sam31_tracker()

        def call(secret):
            with _in_env(KEY, secret):
                try:
                    return client(frames_dir, frame_records, budget=guard)
                except meta_api.BudgetExceeded:
                    refused = guard.refusing(est) or guard.budgets[0]
                    raise BudgetReached(self.name, refused.limit, refused.ledger) from None

        detections = call_with_key(self.name, KEY, call)
        self.spend_usd = est
        return detections
