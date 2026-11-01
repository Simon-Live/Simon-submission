"""The timed prompt for a language-model backend (ADR-0008, TICKET-045, TICKET-046).

A fault that carries `at_s` is phrased live: the model gets the measured record plus the time, the
subject's own side words and the template's timed words, and writes one calm, matter-of-fact sentence that
says the time. The validator (`template.line_problem(..., timed=True)`) holds the sentence to those
facts, so the prompt can set the tone but cannot widen what a line may claim. A fault line
carries no praise (ADR-0008, R2): this text names no praise phrase, because a phrase in a prompt
comes back in nearly every line, and the validator rejects `template.PRAISE_PHRASES` anyway. For the
same reason it offers no closing phrase: the lines of a result are written in parallel, and an offered
ending came back in every one. Each fault gets one of `SHAPES` by its position so that lines start
differently (docs/specs/second-opinion.md AC-VA-01); `variety.repeats` is the guarantee. For a language other
than English the reply is a JSON pair (`lang.reply_instruction`) and the shapes that quote an English opener drop it
(`SHAPE_TIME_FIRST_OTHER`, `SHAPE_AROUND_OTHER`, `SHAPE_COMPARED_OTHER`). `docs/phrasing-review.md` records how the text
was tuned.
"""
import json

from ..measures import ALL_SPECS
from .lang import EN, reply_instruction
from .template import LANDMARKS

TIMED_KEYS = ("measure", "body_part", "joint", "side", "direction", "lateral",
              "magnitude_deg", "threshold_deg", "text_timed")

SYSTEM_TIMED = (
    "Rewrite one measured fault as one short feedback sentence in a calm, matter-of-fact tone. "
    "The user message is the fault as JSON; `text_timed` is a correct plain version. {reply}\n"
    "- Keep the body part, the side and the direction words of `text_timed` (for example \"too far "
    "right\", \"too low\", \"not raised enough\", \"not bent enough\", \"caving in\", \"turned out\", "
    "\"rolling out\"). Add small words so it reads naturally (\"Your\", \"is\", \"are\", \"looks\").\n"
    "- The sentence reports a fault, so it carries no praise or congratulation, at the start or at the "
    "end. Say what is off, not how well the person is doing. Add no closing phrase, encouragement or "
    "filler: the sentence ends with the fault or its reference point.\n"
    "- Say the time once, as the `at_s` number then \" s\", like 1.9 s. No other digit or number.\n"
    "- Say \"left\" or \"right\" only as `text_timed` does. Add no direction word of your own.\n"
    "- Describe what is off; give no fix-it verbs such as bend, lift, raise, lower, push or pull.\n"
    "- Name no other body part, except one word from `may_mention` if it is not empty (for example "
    "\"under your hip\"). Never the head, trunk or hips unless `text_timed` has it.\n"
    "- Use normal punctuation and end the sentence with a full stop.\n"
    "- {shape}\n"
    "- One sentence, at most 120 characters. Example: Your right foot drifts too far to the right at "
    "1.9 s, out past your hip."
)
# Sentence shapes, one per fault by its position in the result (AC-VA-01). The fourth is used once only: its opening
# words would repeat in a second line. Each line still has to pass the word test.
SHAPES = (
    "Start the sentence with the time, like: At 1.9 s, your right foot ...",
    "Start the sentence with the body part and put the time at the end.",
    "Start the sentence with \"Around\" and the time.",
    "Start the sentence with \"Compared with the recording,\" then the body part.",
)
# The shapes that quote an English opener, for a reply in another language, without it: the model copied the first
# example's "At" into the translated line (TICKET-052), "Around" is just as English (TICKET-054 R9), and the fourth
# quotes the English phrase "Compared with the recording," (TICKET-054). `lang.check_translated` rejects a copied time
# word; this keeps the prompt from asking for any of them. The second shape quotes nothing and is the same everywhere.
SHAPE_TIME_FIRST_OTHER = "Start the sentence with the time, then the body part."
SHAPE_AROUND_OTHER = ("Start the sentence with the time, introduced by a short word in the reply language that "
                      "makes it approximate.")
SHAPE_COMPARED_OTHER = ("Start the sentence with a short phrase in the reply language that compares the take with the "
                        "recording, then the body part.")
OTHER_LANGUAGE_SHAPES = {SHAPES[0]: SHAPE_TIME_FIRST_OTHER, SHAPES[2]: SHAPE_AROUND_OTHER,
                         SHAPES[3]: SHAPE_COMPARED_OTHER}


def shape_for(index, language=EN):
    """The sentence shape for the fault at `index` of a result: 0, 1, 2, 3, then 0, 1, 2 again. For a language other
    than English the first is `SHAPE_TIME_FIRST_OTHER`, the third `SHAPE_AROUND_OTHER` and the fourth
    `SHAPE_COMPARED_OTHER`; the second and every English shape are `SHAPES`."""
    shape = SHAPES[index] if index < len(SHAPES) else SHAPES[index % (len(SHAPES) - 1)]
    return shape if language == EN else OTHER_LANGUAGE_SHAPES.get(shape, shape)


def timed_record(fault):
    """The measured record sent to the model: TIMED_KEYS, `at_s` formatted to 0.1 s and the landmarks."""
    record = {k: fault.get(k) for k in TIMED_KEYS}
    record["at_s"] = f"{float(fault['at_s']):.1f}"
    record["may_mention"] = list(LANDMARKS.get(fault["measure"], ()))
    return record


def _measure_meaning(measure):
    spec = ALL_SPECS.get(f"left_{measure}") or ALL_SPECS.get(measure)
    return f" The measure is: {spec.description}." if spec else ""


def system_timed(shape=0, language=EN):
    """The timed system text for the fault at position `shape` of a result, replying in `language`."""
    return SYSTEM_TIMED.format(reply=reply_instruction(language), shape=shape_for(shape, language))


def timed_messages(fault, shape=0, language=EN):
    return [{"role": "system", "content": system_timed(shape, language) + _measure_meaning(fault["measure"])},
            {"role": "user", "content": json.dumps(timed_record(fault), sort_keys=True)}]
