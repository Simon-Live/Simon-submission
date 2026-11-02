# Provenance of the recorded language analyses (TICKET-080, docs/specs/language-cues.md AC-LC-09)

Three analyses of seed 5 Take 03 (`exercise_front_good_03_foot_out-right`, the exercise example, with both feet files),
made through the product path `part5 analyse` with the live switch on, one in each of Spanish, Arabic and Hindi. They are
recorded outputs: `make check-5-contract` validates them and loads them through `part5.output` but does not rebuild them,
because a model's text cannot be rebuilt. The key is never in them.

## Command

Run once per language from the repository root on 2026-11-02 between 05:14:34Z and 05:15:17Z, with `<tag>` set to `es`, `ar`
and `hi` and `<file>` to `fixtures/output/lang/analysis.<tag>.json`:

```
uv run python -m part5 analyse \
  --expected fixtures/input/expected/exercise/animation.json \
  --follower fixtures/input/followers/exercise/exercise_front_good_03_foot_out-right/skeleton.json \
  --expected-feet fixtures/input/expected-feet/exercise/feet.json \
  --follower-feet fixtures/input/followers/exercise/exercise_front_good_03_foot_out-right/feet.json \
  --out <file> --live --lang <tag>
```

`--live` with no `--phrasing` selects Muse Spark (`phrasing.selected_by` is `live`). Each run made two calls to
`meta-models/muse-spark-open-1026` on Baseten: one for the fault line and one batched call for the cues and reasons. Six calls
in all, the bound the ticket set; none was repeated.

## Ledger lines (`~/.simon/baseten_usage.jsonl`, lines 1222 to 1227; the file held 1221 lines before and 1227 after)

| Language | Line | Time (UTC) | Call | HTTP | Prompt tokens | Completion tokens | Of which reasoning |
|---|---|---|---|---|---|---|---|
| es | 1222 | 2026-11-02T05:14:40Z | fault line | 200 | 689 | 1106 | 1048 |
| es | 1223 | 2026-11-02T05:14:43Z | cues and reasons | 200 | 442 | 692 | 636 |
| ar | 1224 | 2026-11-02T05:14:55Z | fault line | 200 | 689 | 933 | 873 |
| ar | 1225 | 2026-11-02T05:15:00Z | cues and reasons | 200 | 442 | 1190 | 1128 |
| hi | 1226 | 2026-11-02T05:15:13Z | fault line | 200 | 689 | 1066 | 1003 |
| hi | 1227 | 2026-11-02T05:15:17Z | cues and reasons | 200 | 442 | 569 | 512 |

## Cost

The Baseten ledger records tokens and no USD, and no Baseten price for this model is recorded in the repository. The USD below is
an estimate at the list rates `docs/meta-api-spend.md` already uses for the Meta Model API (USD 1.25 per million input tokens and
4.25 per million output tokens, Part 1's `spend.py` list rates), so read it as a figure of that order, not as an invoice.

| Language | Prompt tokens | Completion tokens | Estimated USD |
|---|---|---|---|
| es | 1131 | 1798 | 0.00906 |
| ar | 1131 | 2123 | 0.01044 |
| hi | 1131 | 1635 | 0.00836 |
| all | 3393 | 5556 | 0.02785 |

No USD cap applies to the Baseten ledger (the USD 5.00 cap of `docs/meta-api-spend.md` is the Meta Model API's, in its own
ledger, and was not touched). The only bounds were the six calls and the per-minute limit of 30.

## What came back

Every item of every file was written by the model: no fallback. Each `phrasing.faults[0]` and each of the four
`phrasing.cues[]` entries has `backend` `muse-spark`, `model` `meta-models/muse-spark-open-1026`, `lang` the requested
language and `fallback_reason` null. Each file has `phrasing.native_review` `false`.

| Language | Fault line (`faults[0].coaching`) | Cue (`faults[0].cue`, the miss, `insights[0].cue`) | Reason (`insights[0].why`) |
|---|---|---|---|
| es | A 1.9 s tu pie derecho está demasiado a la derecha fuera de tu cadera. | Entra el pie derecho hacia dentro | Pie derecho demasiado a la derecha a los 1.9 s |
| ar | 1.9 s قدمك اليمنى بعيدة جداً إلى اليمين، خارج وركك. | حرك قدمك اليمنى إلى الداخل | القدم اليمنى بعيدة جدا إلى اليمين عند 1.9 s |
| hi | 1.9 s पर आपका दायाँ पैर बहुत ज़्यादा दाएँ है, आपके कूल्हे से बाहर। | दायाँ पैर अंदर रखें | 1.9 s पर दायाँ पैर बहुत दाएँ था |

The three cue paths (`faults[0].cue`, `score.timeline[0].misses[0].cue`, `insights[0].cue`) share one English text, "Step your
right foot in", which was asked once; `insights[0].why` is "Right foot too far right at 1.9 s". The English fields are unchanged
in each file.

## Not reviewed by a native reader

No native reader has checked any of this text; that is what `phrasing.native_review: false` says. The checks that ran (numbers, one
line, length, no praise, no English time phrase, the script of the language) cannot read the meaning or the side
(`docs/assumptions/ASM-015.yaml`). One observation, not a review: the Spanish cue "Entra el pie derecho hacia dentro" uses "entra"
(enter) where a Spanish coach would say something like "mete el pie derecho". That is the kind of difference a native read is for.

## Changed at the 1.14.0 merge (lane/v114)

The three runs were made on a tree without the credit's own grade scale (the team's 8f135ee, `score.credit.grades`), which the
1.14.0 schema requires. At the merge `score.credit.grades` was added to each file, after `bands`, with the scale the shipped
goldens carry (S 95, A 85, B 75, C 65, D 55, E 45, F 30). The credit percent of each file, 92.9, is an A on that scale as
it was before, so `score.credit.grade` did not change. No other byte changed: no model text, no phrasing entry and no other score
field.

## No `quality` block (R9 of the 1.14.0 review)

The three files carry no top-level `quality` block, though they are labelled `1.14.0` and `contracts/history-fields.json` says
`quality` is in every document Part 5 writes from `1.13.0`. They predate it: the runs were made on lane/lang-cues (8e1689c),
which branched before TICKET-079's quality block landed on main (6b448a5) and had no `part5/quality.py`, so the pipeline that
wrote them had no quality block to write.

It was not added at the merge, as `score.credit.grades` was, for two reasons. The schema requires the grades, so the files
could not validate without them, while `quality` is optional: a document without it reads as not assessed (`docs/schemas.md`).
And the grades are a fixed scale copied from the goldens, while `quality` is measured from the take by the pipeline: writing it
by hand would put readings in a recorded output that no run of the product made. Read these three files as not assessed for
quality. A rerun of the three commands above on a tree with the quality block would add it, at the cost of six more Baseten
calls.
