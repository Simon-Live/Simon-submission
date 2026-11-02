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

## History opinion (TICKET-072, branch `lane/history-opinion`)

The history opinion (`part5 history-opinion`, `POST api/history-opinion`, `docs/specs/history-opinion.md`) is a second
Meta call, separate from the Baseten phrasing above: one text-only Responses call to Muse Spark 1.3 on the Meta Model API
through the same client, per-call ceiling, spend cap and ledger as the per-take second opinion (`part5/opinion/meta_api.py`
and `docs/specs/second-opinion.md`). No field that `make check-5` scores depends on it.

| Run | Called? |
|---|---|
| `make test`, `make check-5`, `make check-5-contract`, `make output-examples` | No. Tests use a fake client. |
| `part5 history-opinion` or the route, with live mode off or no Meta Model API key file | No. A `skipped` document with the reason. |
| The same with live mode on and the key, and at least one fault with a second | Yes, one call per request. |

| Limit | Value | Where |
|---|---|---|
| Per-call ceiling | $0.50 (`PART5_META_CALL_MAX_USD`), on the counted input plus the full output allowance | `part5/opinion/meta_api.py` |
| Output allowance | 8000 tokens for a history call (`HISTORY_MAX_OUTPUT_TOKENS`), 3000 for the per-take opinion; the estimate and an estimated ledger line use the request's own | `part5/opinion/prompt.py`, `part5/opinion/meta_api.py` |
| Spend cap on the ledger total | $5.00 (`PART5_META_SPEND_CAP_USD`) | `part5/opinion/meta_api.py` |
| Takes, faults per take | 40 takes, 30 faults each | `part5/opinion/prompt.py` |
| Route requests per client | 6 a minute, one at a time, as for Muse Spark phrasing; 50 s timeout on the call | `part5/api.py` |

Every attempted call appends one line to `~/.simon/meta_usage.jsonl` (`PART5_META_USAGE_FILE` in tests): UTC time, model,
HTTP status, tokens, USD, `purpose` `history_opinion` and `prompt_version`. The key and the text never go in it. The stable
part of the request comes first and the question last, so cached input is priced at the cache rate when the provider reports it.
