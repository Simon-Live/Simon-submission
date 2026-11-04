"""Ask this take (TICKET-081, docs/specs/ask-this-take.md, ADR-0022): a muse-wonder-1.0 agent whose tools read only one
analysed take, returning a `simon.ask.v1` document whose answer passed the validator, or the measured facts, or the cached
demo answer.

    tools    `Take` (one analysis and the replay written with it, and its body mask), the five tools, `run_tool` and the
             word guard on their arguments, `strict_json`
    agent    the readers of what a caller sends (`ask_question`, `ask_take`, `ask_request_from`, `ask_files`), the loop, the
             budget (ASM-016), the cache, the fallback and the document (`ask_run`)

The event stream is not in this package: `sse` and `ask_events`, an exchange as a text/event-stream, are in
`part5/opinion/__init__.py`, because the write gate refused `part5/ask/stream.py`, a name no spec on main held (the spec's
placement note). The validator (`guard.check_answer`, `guard.measured_facts`, `guard.shown_problem`), the prompt and the one
spend path (`meta_api.call`) stay in `part5/opinion/` too, which the second opinion and the history opinion share. The modules
here were the "Ask this take" sections of `part5/opinion/__init__.py` and `part5/replay.py` until the 1.14.0 round moved them,
unchanged, as the spec planned; the 1.14.0 review's fixes R1, R3 and R4 changed them after the move.
"""
