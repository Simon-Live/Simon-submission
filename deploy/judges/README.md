# The judges' relay

Judges run Simon on their own machine with Simon's Meta API key and Simon's Modal GPU, without being given either.
Their Simon sends its Meta API calls and its Part 2 runs to this relay, which holds the key and calls Part 2 on Modal.

- **Open to anyone with the repo's link, until Nov 9, 2026, 11:59 PM ET.** After that every call gets 410.
- **$200 cap** across every judge, Meta API calls and Modal GPU time together (warm-ups included). Past it every call gets 402.
- **Warm start from Nov 5, 2026, 12:00 AM ET:** when `run.sh` starts it asks the relay to keep Part 2's GPU container
  warm for an hour (a ping every 4 minutes), so the judge's first take skips the model load. About $1.95 an hour,
  counted against the cap; a second start during that hour only adds the rest of its own hour.
- **Per address:** $25 a UTC day, 60 requests a minute.
- **Only Simon's calls are forwarded:** the four Meta API paths Simon uses (`files`, `responses`, `responses/input_tokens`, `asr/transcribe`), with Simon's five models. Anything else gets 403, so the key cannot be used for other work.
- **Part 2 always tracks on the GPU** (`local-sam31`): a Meta-API tracker inside Modal would spend the key without the relay counting it.
- **Alerts to the owner through ntfy:** one for every call (what, from which address, how it went, its cost and the total), including blocked and refused ones, and urgent ones at 50%, 80% and 100% of the cap. `modal run deploy/judges/relay.py::ping` sends a test.

The rules and every number above are in [rules.py](rules.py) and checked by `tests/test_judges_relay.py`.

## Setting it up (team)

1. **Make a Meta API key for judging only** at dev.meta.ai, so it can be revoked after judging without touching simon.live. Set a spending limit on it there if the console offers one.
2. **Pick an ntfy topic** nobody can guess, for example `simon-judges-` followed by 20 random letters, and subscribe to it in the ntfy app (iOS, Android or ntfy.sh in a browser).
3. **Create the relay's secret**, typing the values yourself:
   ```
   modal secret create simon-judges-relay MODEL_API_KEY=<the judging key> NTFY_TOPIC=<the topic>
   ```
4. **Set Modal's own budget limit** in the workspace's billing settings (Usage and billing), as a backstop if the relay's count is ever wrong.
5. **Deploy Part 2 from this repo**, so its version matches `modules/PINS.json` (Part 2 refuses a run from another version):
   ```
   modal deploy deploy/judges/part2_app.py
   ```
6. **Deploy the relay:**
   ```
   modal deploy deploy/judges/relay.py
   ```
   It answers at `https://shrutidoshi94--simon-judges-relay-web.us-east.modal.run`. `/health` shows whether it is open and what has been spent.

## While judging runs

```
modal run deploy/judges/relay.py::status        # spent so far, alerts sent, open until
modal run deploy/judges/relay.py::switch --off  # close it now
modal run deploy/judges/relay.py::switch --on   # open it again (still only until the end date)
```

To move the end date or the cap, set `RELAY_ENDS` (ISO 8601) or `RELAY_CAP_USD` in the secret and deploy again.

## After judging

Revoke the judging key at dev.meta.ai, run `modal app stop simon-judges-relay`, and delete the secret
(`modal secret delete simon-judges-relay`).

## How a judge's Simon uses it

The judge sets these in Simon's `.env` (the repo README's "Run the full pipeline" section):

```
SIMON_META_API=https://shrutidoshi94--simon-judges-relay-web.us-east.modal.run/meta/v1
SIMON_PART2_RELAY=https://shrutidoshi94--simon-judges-relay-web.us-east.modal.run
SIMON7_PART2_REMOTE=modal
MODEL_API_KEY=judges-relay
```

`MODEL_API_KEY` is a placeholder: Simon's parts need a value there, and the relay drops it and uses its own key.
The address change is in this repo only (`SIMON_META_API` in Part 1, Part 5 and Part 7's Meta callers,
`SIMON_PART2_RELAY` in `deploy/serverless/p2_client.py`); without them set, Simon behaves as it does on simon.live.
