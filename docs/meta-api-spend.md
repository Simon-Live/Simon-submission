# Meta API spend: Part 5

Part 5 calls one Meta model: Muse Spark (`meta-models/muse-spark-open-1026`) served by Baseten. It rewords each
fault as a coaching line (#20, ADR-0005, ADR-0008). No field that `make check-5` scores depends on it.

## When a call is made

| Run | Muse Spark called? |
|---|---|
| `make test`, `make check-5`, `make check-5-contract`, `make output-examples` | No. Phrasing is forced to `template`. |
| `part5 analyse` without live mode | No. `template`, or with `--phrasing muse-spark` the template line and the reason "live calls are off". |
| Live mode on (`--live`, `SIMON5_LIVE=1` or `META_LIVE=1`) and the key file present | Yes, one call per fault. |
| Live mode on and no key file | No. The template line and the reason "no key". |

Every fault records its wording in `analysis.json` under `phrasing.faults[k]`: `backend`, `model` and
`fallback_reason`. A call that fails, times out or breaks the validator falls back to the template line for that
fault.

## Budget guard

| Limit | Value | Where |
|---|---|---|
| Calls per minute, per process | 30 (`PART5_MUSE_PER_MINUTE`) | `part5/phrasing/muse_spark.py` |
| Timeout per call | 10 s | `part5/phrasing/__init__.py` |
| Time one analysis may spend on phrasing | 20 s (`PART5_PHRASING_BUDGET_S`) | `part5/phrasing/__init__.py` |
| Muse Spark requests per client on the analysis server | 6 a minute, one at a time | `part5/api.py` |
| `max_tokens` per call | 2048, reasoning effort low | `part5/phrasing/muse_spark.py` |

## Ledger

Every call, whether it succeeds or not, appends one line to `~/.simon/baseten_usage.jsonl` (`PART5_BASETEN_USAGE_FILE`
in tests): UTC time, model, HTTP status and token counts. The key and the text never go in it.

Totals on the maintainers' host, read from that file on 2026-10-31 (last line 17:33:28Z):

| Calls | HTTP 200 | Prompt tokens | Completion tokens | Of which reasoning |
|---|---|---|---|---|
| 160 | 160 | 88,311 | 132,536 | 128,118 |

Calls by day: 1 on 2026-10-29, 37 on 2026-10-30, 122 on 2026-10-31. `docs/phrasing-review.md` counts 88 calls for
its first review, more than the ledger held then; the ledger is the record. No price per token is recorded here, so
the spend is given in tokens.

The 2026-10-31 no-praise re-review (`docs/phrasing-review.md`, "Re-review 2026-10-31") is 20 of those calls: HTTP 200
each, 12,324 prompt tokens, 14,363 completion tokens, 13,872 of them reasoning (the ledger held 140 lines before it
and 160 after).
