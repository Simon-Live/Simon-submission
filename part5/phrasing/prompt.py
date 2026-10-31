"""The timed prompt for a language-model backend (ADR-0008).

A fault that carries `at_s` is phrased live: the model gets the measured record plus the time, the
subject's own side words and the template's timed words, and writes one calm, friendly sentence that
says the time. The validator (`template.line_problem(..., timed=True)`) holds the sentence to those
facts, so the prompt can ask for a kind tone but cannot widen what a line may claim. A fault line
carries no praise (ADR-0008, R2): this text names no praise phrase, because a phrase in a prompt
comes back in nearly every line, and the validator rejects `template.PRAISE_PHRASES` anyway.
`docs/phrasing-review.md` records how the text was tuned.
"""
import json

from ..measures import ALL_SPECS
from .template import LANDMARKS

TIMED_KEYS = ("measure", "body_part", "joint", "side", "direction", "lateral",
              "magnitude_deg", "threshold_deg", "text_timed")

SYSTEM_TIMED = (
    "Rewrite one measured fault as one short coaching sentence in a calm, friendly, matter-of-fact tone. "
    "The user message is the fault as JSON; `text_timed` is a correct plain version. Reply with only the "
    "sentence.\n"
    "- Keep the body part, the side and the direction words of `text_timed` (for example \"too far "
    "right\", \"too low\", \"not raised enough\", \"not bent enough\", \"caving in\", \"turned out\", "
    "\"rolling out\"). Add small words so it reads naturally (\"Your\", \"is\", \"are\", \"looks\").\n"
    "- The sentence reports a fault, so it carries no praise or congratulation, at the start or at the "
    "end. Say what is off, not how well the person is doing. A short encouraging ending such as "
    "\"keep going\" is allowed and not needed.\n"
    "- Say the time once, as the `at_s` number then \" s\", like 1.9 s. No other digit or number.\n"
    "- Say \"left\" or \"right\" only as `text_timed` does. Add no direction word of your own.\n"
    "- Describe what is off; give no fix-it verbs such as bend, lift, raise, lower, push or pull.\n"
    "- Name no other body part, except one word from `may_mention` if it is not empty (for example "
    "\"keep it under your hip\"). Never the head, trunk or hips unless `text_timed` has it.\n"
    "- Use normal punctuation: put a comma before a closing phrase such as \"keep going\", and end the "
    "sentence with a full stop.\n"
    "- One sentence, at most 120 characters. Example: Your right foot drifts too far to the right at "
    "1.9 s; keep it under your hip."
)


def timed_record(fault):
    """The measured record sent to the model: TIMED_KEYS, `at_s` formatted to 0.1 s and the landmarks."""
    record = {k: fault.get(k) for k in TIMED_KEYS}
    record["at_s"] = f"{float(fault['at_s']):.1f}"
    record["may_mention"] = list(LANDMARKS.get(fault["measure"], ()))
    return record


def _measure_meaning(measure):
    spec = ALL_SPECS.get(f"left_{measure}") or ALL_SPECS.get(measure)
    return f" The measure is: {spec.description}." if spec else ""


def timed_messages(fault):
    return [{"role": "system", "content": SYSTEM_TIMED + _measure_meaning(fault["measure"])},
            {"role": "user", "content": json.dumps(timed_record(fault), sort_keys=True)}]
