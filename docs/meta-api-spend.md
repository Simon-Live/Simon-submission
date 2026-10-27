# Meta Model API spend ledger

Estimated spend for live calls made by this repo. Classical `make check-4`
does not call the API. Open-weight local runs are logged at $0.

Cumulative estimated spend: **$0.0000**

Alert thresholds crossed: none

Alerts fire when cumulative estimated spend reaches $5, $10, $15, and so on.
Token prices used here: Muse Spark $1.25 / $4.25 per million input / output tokens
(reasoning tokens count as output, and `completion_tokens` already includes them);
Muse Wonder $4 / $20 per million; Muse Image $0.01 per image; Muse Voice Transcribe
$0.18 per hour; SAM 3.1 $2.50 per 1,000 images. Cached prompt tokens are not discounted.

A coordinator probe outside this repo made 3 tiny Muse Spark calls (<< $0.01).
Those calls are not in the table below.

| When (UTC) | Model | Call | Prompt tokens | Completion tokens | Reasoning tokens | Estimated USD | Cumulative |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| — | — | no live calls | 0 | 0 | 0 | 0.0000 | 0.0000 |
