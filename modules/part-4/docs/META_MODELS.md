# Meta models in Part 4

Part 4 rebuilds a 30 fps skeleton with classical cubic interpolation of joint
rotations. That path is what `make check-4` runs. It does not read an API key
and it does not open a socket.

Meta models are optional hooks around that result: a critique of keyframe
spacing, an advisory phase plan, a demo poster, a coaching-note transcript, a
person segment, and two open-weight local reviewers. Live HTTP calls are
blocked unless you set `META_LIVE=1`. Nothing in this repo invents a model
response when the call does not happen. Offline hooks say `source: offline`.

## Keys and the live switch

Meta Model API is OpenAI-chat compatible.

| | |
| --- | --- |
| Base URL | `https://api.meta.ai/v1` |
| Auth | `Authorization: Bearer …` |
| Key variable | `META_API_KEY`, or `MODEL_API_KEY` if that is what the dashboard gave you |
| Live switch | `META_LIVE=1` |

```bash
export META_API_KEY="paste-the-key-from-https://dev.meta.ai"
export META_LIVE=1
```

Leave `META_LIVE` unset in CI and for `make check-4`. A key alone does not
enable calls. This cloud agent cannot see the key; run the commands below on
a machine where you have exported it.

Chat calls use the `developer` role, not `system`. The working text call is:

`POST /v1/chat/completions` with `"model": "muse-spark-1.3"`.

The body we read is the probed chat completion shape:

- `choices[0].message.content`
- `choices[0].finish_reason` (`stop` or `length`)
- `usage.prompt_tokens`, `usage.completion_tokens`, `usage.total_tokens`
- `usage.completion_tokens_details.reasoning_tokens`
- `usage.prompt_tokens_details.cached_tokens`

Muse Spark always reasons, and reasoning tokens are spent from `max_tokens`
before any visible reply. A small `max_tokens` comes back as `content: null`
and `finish_reason: "length"`. The client floors `max_tokens` at 1024 and
raises if the reply is still truncated. It does not fill in a fake answer.
Live smoke of the Spark critique and Wonder plan needed 2048: with 1024 the
finish reason was `length` and content was empty, because reasoning tokens
consume the budget first. Those two hooks request 2048. A truncated reply is
still appended to the spend ledger as `<call>:truncated`.

## What each model does here

| Model | When | What it does for this part |
| --- | --- | --- |
| `muse-spark-1.3` | `META_LIVE=1` | Reads the largest keyframe-to-keyframe joint steps and critiques whether that spacing can survive the 8° hidden-frame test. |
| `muse-wonder-1.0` | `META_LIVE=1` | Writes a short advisory phase plan from the keyframe names. It does not edit `animation.json`. |
| `muse-image-1.0` | `META_LIVE=1` | `POST /v1/images/generations`. One demo poster per clip, about $0.01. Written under `demo/posters/` (gitignored). |
| `muse-voice-transcribe-1.0` | `META_LIVE=1` and a wav path | `POST /v1/asr/transcribe`. Turns a coaching recording into text. Offline, the authored `coaching_note.txt` is returned and labeled as such. |
| `sam-3.1` | `META_LIVE=1` and an image URL | `POST /v1/responses` with text `person` plus the image. Raw boxes/masks are returned only if the API sends them. No mask is synthesized offline. |
| Muse Glimmer | local only | Open weights. Set `META_LOCAL=1` and `GLIMMER_BASE_URL` to an OpenAI-compatible server you already run (vLLM, llama.cpp, LM Studio). Default model id `muse-glimmer` (`GLIMMER_MODEL` overrides). This repo does not download the weights. Offline, a geometric caption is used. |
| Muse Spark Open | local only | Same pattern: `META_LOCAL=1` and `SPARK_OPEN_BASE_URL`. Default model id `muse-spark-open`. Asks for a short code review of the interpolator, in the Muse Code style (developer role, short review prompt). Offline, the two known failure modes are listed and labeled offline. |

Prices charged to the ledger (ballpark): Spark $1.25 / $4.25 per million input / output tokens; Wonder $4 / $20; Image $0.01 per image; voice $0.18 per hour; SAM 3.1 $2.50 per 1,000 images. `completion_tokens` already includes reasoning tokens, so those are billed once, as output. Cached prompt tokens are not discounted. Local open-weight calls are logged at $0.

## Commands

From the repo root, with `PYTHONPATH=src` (the Makefile exports it):

```bash
python3 -m simon_anim.meta_hooks status
python3 -m simon_anim.meta_hooks self-test          # proves the live gate blocks a call
python3 -m simon_anim.meta_hooks critique --set exercise
python3 -m simon_anim.meta_hooks plan --set dance
python3 -m simon_anim.meta_hooks poster --set exercise
python3 -m simon_anim.meta_hooks transcript --set exercise
python3 -m simon_anim.meta_hooks transcript --set exercise --wav coach.wav
python3 -m simon_anim.meta_hooks segment --image-url https://example.com/person.png
python3 -m simon_anim.meta_hooks caption --set dance
python3 -m simon_anim.meta_hooks review-open
```

Without `META_LIVE=1`, `critique`, `plan`, `poster`, `transcript`, and `segment` return immediately and do not call `api.meta.ai`.

Spend is appended to `docs/meta-api-spend.md` and `docs/meta-api-spend.json` only after a real call returns. Crossing $5, $10, $15, … prints `SPEND ALERT` and records it in the ledger.
