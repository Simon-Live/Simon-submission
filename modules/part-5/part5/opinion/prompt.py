"""The second-opinion request (TICKET-045, docs/specs/second-opinion.md AC-SO-01).

One Responses body: the instructions, the teacher's recording and the student's take as uploaded files, each after
a text label, and the measured faults as JSON. The model's answer is shown to students after the guardrail
(`guard.read_answer`), so the instructions ask for plain sentences about what is visible, no praise and no health
words; the guardrail enforces each of those, the prompt only asks.

The history opinion (TICKET-072, docs/specs/history-opinion.md) lives in the second half of this module: the
allowlist and the facts read from a series of analyses (`READS`, `load_allowlist`, `facts_of`, `build_series`) and its text-only
request (`history_request`). `guard.read_history_answer` reads the answer and `opinion.history_run` makes the call.

Ask this take (TICKET-081, docs/specs/ask-this-take.md) is the last part: muse-wonder-1.0 and its rates, the
instructions, the five tool declarations (`ask_tools`) and one turn's Responses body (`ask_opening`, `ask_request`).
"""
import json
import math
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from ..phrasing import lang as phrasing_lang
from .meta_api import MODEL

MAX_NOTE = 140
MAX_OBSERVATIONS = 2
# The output allowance of a per-take call (TICKET-102): the model reasons before it writes and the reasoning is counted
# as output, so a live call on 7071 input tokens used all of 3000 and left a half-written JSON (job 23d13c0b27e7, the
# same cut the history opinion had, and fixed the same way: `HISTORY_MAX_OUTPUT_TOKENS`). 8000 x USD 4.25 per million is
# USD 0.034 on top of the input, well under the 0.50 per-call ceiling; the estimate, the cap check and an estimated
# ledger line follow the request's own allowance (`meta_api.call`).
SECOND_MAX_OUTPUT_TOKENS = 8000

INSTRUCTIONS = (
    "You check a movement analysis. Clip 1 is a teacher's recording. Clip 2 is a student copying it. A skeleton "
    "measurement found the differences listed at the end in clip 2. Watch both clips.\n"
    "1. For each difference, say whether clip 2 shows it at that time (agrees true or false), with one plain "
    "sentence of at most {max_note} characters saying what you see.\n"
    "2. Then add at most {max_obs} things you notice in clip 2 that the list does not hold, such as balance, "
    "tempo, range of movement or where the person looks, each with the time in clip 2 in seconds.\n"
    "Rules: describe only what is visible. Name only body parts you can see in clip 2. Every time is between 0 "
    "and {duration} s of clip 2. Write no other numbers, and call the clips the recording and the take, never by "
    "number. No praise. Never mention health, pain, injury, medicine "
    "or therapy. Write in English.\n"
    "Reply with only JSON: {{\"verdicts\": [{{\"fault_index\": 0, \"agrees\": true, \"note\": \"...\"}}], "
    "\"observations\": [{{\"at_s\": 2.5, \"text\": \"...\"}}]}}"
)


def fault_list(faults):
    """What the model is told about each fault: its index, its plain words, side, time and span in clip 2."""
    out = []
    for i, f in enumerate(faults):
        item = {"fault_index": i, "what": f.get("text_timed") or f["text"], "measure": f["measure"],
                "side": f["side"], "direction": f["direction"]}
        if f.get("at_s") is not None:
            item["at_s"] = round(float(f["at_s"]), 1)
        if f.get("follower_t_s"):
            item["from_s"], item["to_s"] = (round(float(t), 1) for t in f["follower_t_s"])
        out.append(item)
    return out


def request(expected_id, follower_id, faults, duration_s):
    """The Responses body for one second opinion on clip ids `expected_id` (teacher) and `follower_id` (student)."""
    text = INSTRUCTIONS.format(max_note=MAX_NOTE, max_obs=MAX_OBSERVATIONS, duration=f"{duration_s:.1f}")
    content = [
        {"type": "input_text", "text": text},
        {"type": "input_text", "text": "Clip 1, the teacher's recording:"},
        {"type": "input_file", "file_id": expected_id},
        {"type": "input_text", "text": f"Clip 2, the student's take ({duration_s:.1f} s long):"},
        {"type": "input_file", "file_id": follower_id},
        {"type": "input_text", "text": "Measured differences in clip 2 (JSON): "
         + json.dumps(fault_list(faults), sort_keys=True)},
    ]
    return {"model": MODEL, "max_output_tokens": SECOND_MAX_OUTPUT_TOKENS, "reasoning": {"effort": "low"},
            "input": [{"type": "message", "role": "user", "content": content}]}


# ---- the history opinion (TICKET-072, docs/specs/history-opinion.md) ----------------------------------------------
PROMPT_VERSION = "history-opinion-2"   # raised whenever the instructions, the facts or the allowlist change
HISTORY_FIELDS_FILE = Path(__file__).resolve().parents[2] / "contracts" / "history-fields.json"   # TICKET-070
HISTORY_DEFAULT_N, HISTORY_MAX_N = 5, 10   # observations asked for by default, and the most that can be asked for
# The output allowance of a history call. The model appears to reason before it writes, and that reasoning is counted
# as output: the one live call of 2026-11-01 (about 1.1k input tokens) used all of 3000 and left no JSON, and two
# per-take calls on 5k to 6k tokens of input reached 2948 and 3000. So: twice the 3000 seen, for the reasoning, plus
# 1400 for the reply (10 observations at about 140 tokens: the cited values, a 140-character sentence and a
# 200-character line), rounded up.
# The worst case is 8000 x $4.25 per million = $0.034 on top of the input, well under the $0.50 per-call ceiling.
HISTORY_MAX_OUTPUT_TOKENS = 8000
MAX_TAKES = 40
MAX_FAULTS = 30       # fault rows kept per take (faults are sorted largest first, so the rest are the smallest)
MAX_WARNINGS = 5
MAX_FILE_BYTES = 16 * 1024 * 1024   # an analysis file; the API's body limit is `api.MAX_BODY_BYTES`
# Both are read with `fullmatch`: a `$` would let a trailing newline through.
TAKE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,63}")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,39}")
ROW_LIMITS = {"faults": MAX_FAULTS, "warnings": MAX_WARNINGS}


class HistoryError(ValueError):
    """The series cannot be read. `field` names the request field at fault for the API."""

    def __init__(self, message, field="analyses"):
        super().__init__(message)
        self.field = field


class UsageError(HistoryError):
    """The series was asked for wrongly (take ids): the CLI exits 2 for it, 1 for any other HistoryError."""


class ContractError(HistoryError):
    """`contracts/history-fields.json` cannot be read or no longer lists a field the opinion reads. It is the server's
    fault, not the request's: the CLI exits 1 with the message and the API answers 500."""

    def __init__(self, message):
        super().__init__(message, "contract")


@dataclass(frozen=True)
class Field:
    """One allowlisted path: `score.value` (an object key) or `faults[].measure` (a key of each row of a list).

    `kind` is `id` (a short identifier), `score` (a whole number 0 to 100), `number` (finite, at most 1e6, 2 decimals)
    or `seconds` (0 to 36000, 0.1 s). `needed` marks a value a list row cannot do without. `meaning` is sent to the
    model."""
    path: str
    kind: str
    meaning: str
    needed: bool = False

    @property
    def group(self):
        """The list this field is a row key of (`faults`), or None."""
        return self.path.partition("[].")[0] if "[]." in self.path else None

    @property
    def keys(self):
        """The object keys down to the value (`("score", "value")`); for a list field the single row key."""
        return tuple((self.path.partition("[].")[2] if self.group else self.path).split("."))


# The fields the opinion reads, as (path, needed); `needed` marks a value a list row cannot do without. This list says which
# fields may be read, and nothing else is: no free text, only short identifiers and numbers. What each field means and what
# kind of value it is come from `contracts/history-fields.json` (TICKET-070), so the model is told what Part 7 is promised. A path the contract does not list stops the opinion (`ContractError`).
READS = (
    ("schema_version", False),
    ("profile", False),
    ("status.code", False),
    ("score.version", False),
    ("score.value", False),
    ("score.grade", False),
    ("warnings[].code", True),
    ("faults[].measure", True),
    ("faults[].side", True),
    ("faults[].body_part", True),
    ("faults[].direction", True),
    ("faults[].magnitude_deg", False),
    ("faults[].at_s", False),
)
# The kind of value (see `Field`) for the units the contract gives a field; `none` is a label or a code, read as an identifier.
KIND_OF_UNITS = {"none": "id", "score points": "score", "degrees": "number", "seconds": "seconds"}
VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")


@lru_cache(maxsize=4)
def _allowlist_from(path):
    """`(allowlist_version, fields)` read from the history contract at `path` (a str, so the result can be cached)."""
    name = Path(path).name
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
        listed = {entry["path"]: entry for entry in doc["fields"]}
        version = doc["version"]
    except (OSError, ValueError, KeyError, TypeError, RecursionError):
        raise ContractError(f"the history contract {name} cannot be read") from None
    if not isinstance(version, str) or not VERSION.fullmatch(version):
        raise ContractError(f"the history contract {name} has no version such as 1.1.0")
    fields = []
    for read_path, needed in READS:
        entry = listed.get(read_path)
        entry = entry if isinstance(entry, dict) else {}
        kind, meaning = KIND_OF_UNITS.get(entry.get("units")), entry.get("meaning")
        if kind is None or not isinstance(meaning, str) or not meaning.strip():
            raise ContractError(f"the history contract {name} does not list {read_path} with units and a meaning")
        fields.append(Field(read_path, kind, " ".join(meaning.split()), needed))
    return f"history-fields-{version}", tuple(fields)


def load_allowlist(path=None):
    """The fields read from each analysis: `READS`, with the kind and the meaning the history contract gives each.
    `path` is another contract file (the tests'); ContractError when it cannot be read or lacks a field."""
    return _allowlist_from(str(path or HISTORY_FIELDS_FILE))[1]


def allowlist_version(path=None):
    """The allowlist's version as the document states it: `history-fields-` and the contract's own `version`."""
    return _allowlist_from(str(path or HISTORY_FIELDS_FILE))[0]


def _number(raw):
    """`raw` as a float when it is a finite number (not a bool), else None."""
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    try:
        return float(raw) if math.isfinite(raw) else None
    except OverflowError:   # an integer too large for a float
        return None


def _value(raw, kind):
    """`raw` as it is sent, or None when it is not of its `kind`."""
    if kind == "id":
        return raw if isinstance(raw, str) and _ID.fullmatch(raw) else None
    number = _number(raw)
    if number is None:
        return None
    if kind == "score":
        return raw if isinstance(raw, int) and 0 <= raw <= 100 else None
    if kind == "seconds":
        return round(number, 1) if 0 <= number <= 36000 else None
    return round(number, 2) if abs(number) <= 1e6 else None


def _dig(doc, keys):
    for key in keys:
        doc = doc.get(key) if isinstance(doc, dict) else None
    return doc


def _put(facts, keys, value):
    for key in keys[:-1]:
        facts = facts.setdefault(key, {})
    facts[keys[-1]] = value


def _row(item, fields):
    """The allowlisted keys of one list item, or None when it is not an object or lacks a needed value."""
    if not isinstance(item, dict):
        return None
    row = {f.keys[0]: v for f in fields if (v := _value(item.get(f.keys[0]), f.kind)) is not None}
    return row if all(f.keys[0] in row for f in fields if f.needed) else None


def _rows(items, fields, limit):
    """(rows, omitted): the kept rows of `items`; a row that is not valid and every row past `limit` is counted."""
    rows, omitted = [], 0
    for item in items if isinstance(items, list) else []:
        row = _row(item, fields)
        if row is None or len(rows) >= limit:
            omitted += 1
        else:
            rows.append(row)
    return rows, omitted


def facts_of(doc, allowlist=None):
    """`(facts, faults_omitted)` for one analysis: its allowlisted values and nothing else."""
    fields = allowlist if allowlist is not None else load_allowlist()
    facts, omitted = {}, 0
    for f in fields:
        value = _value(_dig(doc, f.keys), f.kind) if f.group is None else None
        if value is not None:
            _put(facts, f.keys, value)
    for group in dict.fromkeys(f.group for f in fields if f.group):
        group_fields = [f for f in fields if f.group == group]
        rows, left_out = _rows(doc.get(group), group_fields, ROW_LIMITS.get(group, MAX_FAULTS))
        facts[group] = rows
        omitted += left_out if group == "faults" else 0
    return facts, omitted


def analysis_problem(doc):
    """None when `doc` looks like a Part 5 analysis (an object with a `simon.analysis.*` format and a faults list)."""
    if not isinstance(doc, dict):
        return "not an analysis (not a JSON object)"
    if not (isinstance(doc.get("format"), str) and doc["format"].startswith("simon.analysis.")):
        return "not an analysis (format is not simon.analysis.*)"
    if not isinstance(doc.get("faults"), list):
        return "not an analysis (no faults list)"
    return None


def take_id_from(path):
    """The take id of a file: its name without `.json`, or the folder's name for a file called `analysis.json`."""
    path = Path(path)
    name = path.name[:-5] if path.name.lower().endswith(".json") else path.name
    return path.resolve().parent.name if name.lower() == "analysis" else name


def check_ids(ids, count):
    """Raise UsageError unless `ids` are `count` valid, different take ids."""
    if len(ids) != count:
        raise UsageError(f"{len(ids)} take ids for {count} analyses: give one for each, in order")
    if not all(isinstance(tid, str) and TAKE_ID.fullmatch(tid) for tid in ids):
        raise UsageError("a take id uses letters, digits, dot, underscore, plus and hyphen only, starts with a letter "
                         "or digit and has at most 64 characters")
    if len(set(ids)) != len(ids):
        raise UsageError(f"take id {next(t for t in ids if ids.count(t) > 1)!r} is used twice: name the takes with "
                         "--take-id")


@dataclass(frozen=True)
class Series:
    """The takes in order. `takes` are the facts as sent (`take`, `position` and the allowlisted values); `faults` are
    each take's fault rows, the only things an observation may cite; `omitted` counts faults left out per take."""
    takes: tuple
    faults: dict
    omitted: dict

    def citable(self):
        """True when some fault has a second to cite."""
        return any("at_s" in row for rows in self.faults.values() for row in rows)

    def summary(self):
        """One row per take for the document."""
        return [{"take_id": t["take"], "position": t["position"], "faults_sent": len(self.faults[t["take"]]),
                 "faults_omitted": self.omitted[t["take"]]} for t in self.takes]


def build_series(docs, ids, labels=None):
    """The `Series` of the analyses `docs` named `ids` (in order, oldest first). HistoryError for a series that is empty
    or over MAX_TAKES, or a document that is not an analysis (named by `labels`, default the take ids); UsageError for
    take ids that are wrong."""
    if not docs:
        raise HistoryError("give at least one analysis")
    if len(docs) > MAX_TAKES:
        raise HistoryError(f"{len(docs)} analyses, the limit is {MAX_TAKES}")
    check_ids(list(ids), len(docs))
    takes, faults, omitted = [], {}, {}
    for position, (tid, doc, label) in enumerate(zip(ids, docs, labels or ids), 1):
        problem = analysis_problem(doc)
        if problem:
            raise HistoryError(f"{label}: {problem}")
        facts, left_out = facts_of(doc)
        takes.append({"take": tid, "position": position, **facts})
        faults[tid], omitted[tid] = tuple(facts.get("faults", ())), left_out
    return Series(tuple(takes), faults, omitted)


HISTORY_INSTRUCTIONS = (
    "You read the measured results of one person's takes of the same movement, oldest first. A skeleton measurement "
    "compared each take with a teacher's recording and listed the faults it found. You have no video: the facts "
    "below are all you know.\n"
    "Each take holds only these fields (a missing one was not available):\n{guide}\n"
    "Say what the series shows about its faults: one that repeats, appears, grows, shrinks or goes away. Each "
    "observation is about ONE fault of ONE take. Cite it by copying five values from that fault's row: take (the take "
    "id), at_s, measure, side and body_part. A fault with no at_s cannot be cited. Cite the take where the fault is "
    "clearest.\n"
    "Rules for the sentence (text): one plain sentence of at most {max_text} characters, in English. Write no numbers "
    "and no take ids; say \"the earlier takes\", \"the later takes\" or \"this take\" in words. Name only the body "
    "part of the cited fault, and a side only if it is the cited side. Do not say what caused anything and do not "
    "compare with other people. No praise. Never mention health, pain, injury, medicine or therapy. Call the "
    "teacher's clip \"the recording\". Say nothing the facts do not show; if they show nothing worth saying, reply "
    "with an empty list.\n"
    "Reply with only JSON: {{\"observations\": [{{\"take\": \"<take id>\", \"at_s\": 0.7, "
    "\"measure\": \"knee_flexion\", \"side\": \"left\", \"body_part\": \"legs\", \"text\": \"...\", "
    "\"line\": \"...\"}}]}}. Add \"line\" only when the question asks for another language."
)


def field_guide(allowlist=None):
    """The meaning of each allowlisted path, one per line: what the model is told about the fields."""
    return "\n".join(f"- {f.path}: {f.meaning}" for f in (allowlist if allowlist is not None else load_allowlist()))


def history_question(language, limit):
    """The question, the one part of the request that changes between calls on one series."""
    asked = (f"Question: what does this series show about its faults? Give at most {limit} observations, the most "
             "useful first. ")
    if language == phrasing_lang.EN:
        return asked + "Write each sentence in English."
    other = phrasing_lang.name(language)
    return asked + f"Write each sentence in English in \"text\" and the same sentence in {other} in \"line\", with no digit."


def history_request(series, language, limit):
    """The Responses body for a history opinion on `series`: text only, the stable content first (instructions, then
    the facts) and the question last, so the provider's prompt cache can apply to the first two."""
    text = HISTORY_INSTRUCTIONS.format(guide=field_guide(), max_text=MAX_NOTE)
    facts = "Takes, oldest first (JSON): " + json.dumps(series.takes, sort_keys=True, separators=(",", ":"))
    content = [{"type": "input_text", "text": part} for part in (text, facts, history_question(language, limit))]
    return {"model": MODEL, "max_output_tokens": HISTORY_MAX_OUTPUT_TOKENS, "reasoning": {"effort": "low"},
            "input": [{"type": "message", "role": "user", "content": content}]}


# ---- Ask this take (TICKET-081, docs/specs/ask-this-take.md "The agent loop", ADR-0022) ------------------------------
ASK_MODEL = "muse-wonder-1.0"
# USD per million tokens, Model API pay-as-you-go Standard mode (https://dev.meta.ai/docs/pricing-rate-limits, checked
# 2026-11-02 by the orchestrator); `meta_api.call` prices and records every ask turn at these.
ASK_RATES = {"input": 4.00, "cached": 0.20, "output": 20.00}
# Raised whenever the instructions or the tool declarations change. "ask-2" names a trial of lane/fix114b that was taken
# back (docs/meta-api-spend.md), so the last-turn message of N4 of the 1.14.0 recheck is "ask-3", and the message of the
# turn before it, which asks for the seek and the spotlight (TICKET-081, lane/askseek), is "ask-4".
ASK_PROMPT_VERSION = "ask-4"
# A tool turn writes a few short calls and an answer is at most 80 words; the rest is room for the model's reasoning,
# which is billed as output. The worst case is 3000 x $20 per million = $0.06 on top of the input.
ASK_MAX_OUTPUT_TOKENS = 3000
MAX_QUESTION_CHARS = 500
ASK_INSTRUCTIONS = (
    "You answer one question about one recorded take of a movement. A skeleton measurement compared the take with a "
    "teacher's example. Use the tools to read this take's measurements; they read only this take.\n"
    "Rules: every number you write must be copied, as digits, from a tool result in this conversation; when no tool "
    "gave you a number, write none. Times are seconds on the take's own clock. Answer in at most 80 words of plain "
    "English about what was measured, in one paragraph. When a moment of the take answers the question, call seek "
    "with that time, and call spotlight with the limb or joint it is about. Answer only about this take; for any other "
    "question, say that you can only answer about this take. No praise. Never mention health, pain, injury, medicine "
    "or therapy."
)
# N4 of the 1.14.0 recheck (TICKET-081): the model asked for tools on the last turn, which is sent without them, and the
# exchange ended in the measured facts. The last turn now says so plainly, after the tool results.
ASK_LAST_TURN = (
    "No more tools are available: this is the last turn, and a tool call now cannot be answered. Answer the question "
    "now, in text, from the tool results you already have, following the rules above."
)
# TICKET-081, lane/askseek: with no tool left on the last turn (N4), the two live answers had read all the way and moved
# the page's replay nowhere. The turn before it says so, so the model calls seek and spotlight in that turn, beside any
# read it still needs, for the moment and the limb it will answer about.
ASK_SEEK_TURN = (
    "This is the last turn with tools: the next turn has none. In this turn, call seek with the time of the moment you "
    "will answer about and spotlight with the limb or joint it is about, together with any reads you still need. "
    "You need not repeat a seek or a spotlight you already made for that moment."
)


def _tool(name, description, properties=None, required=()):
    """One function declaration as the Responses API reads it: the fields at the top level, not under `function`."""
    return {"type": "function", "name": name, "description": description,
            "parameters": {"type": "object", "properties": properties or {}, "required": list(required),
                           "additionalProperties": False}}


def ask_tools(joints, limbs):
    """The five tool declarations; `joints` are the joints with a measure and `limbs` every name `spotlight` takes."""
    def seconds(what):
        return {"type": "number", "description": f"{what}, in seconds on the take's own clock"}

    joint = {"type": "string", "enum": list(joints), "description": "a joint of the take that has a measure"}
    return [
        _tool("get_faults", "The differences the measurement found in this take: what differed, the side, the size in "
              "degrees, the time, the take's first and last time, and any warning."),
        _tool("get_joint_angle", "The take's measures at one joint, in degrees, between two times: the smallest, the "
              "largest, the mean, and when the smallest and the largest happen.",
              {"joint": joint, "t0": seconds("the start"), "t1": seconds("the end, not before t0")},
              ("joint", "t0", "t1")),
        _tool("compare_with_teacher", "The take's measures at one joint at one time against the example's at the "
              "moment the alignment matches with it, and the difference (the take's minus the example's, in degrees).",
              {"joint": joint, "t": seconds("the time")}, ("joint", "t")),
        _tool("seek", "Move the player to a time of the take.", {"t": seconds("the time")}, ("t",)),
        _tool("spotlight", "Highlight a limb or a joint in the player at a time.",
              {"limb": {"type": "string", "enum": list(limbs)}, "t": seconds("the time")}, ("limb", "t")),
    ]


def ask_opening(question, start_s, end_s, joints, limbs):
    """The first turn's input: one user message, the stable instructions first and the question last."""
    take = (f"The take runs from {start_s:.2f} s to {end_s:.2f} s. Joints with a measure: {', '.join(joints)}. "
            f"Limbs for spotlight: {', '.join(limbs)}.")
    content = [{"type": "input_text", "text": part} for part in (ASK_INSTRUCTIONS, take, f"Question: {question}")]
    return [{"type": "message", "role": "user", "content": content}]


def _user_message(text):
    return {"type": "message", "role": "user", "content": [{"type": "input_text", "text": text}]}


def ask_request(items, tools=None, previous_id=None, *, last=False, seek=False):
    """One turn's Responses body: `items` as the input, `tools` when the model may still call one, and the previous
    turn's id when `items` are the results of its calls. The last allowed turn (`last`) has no tools and ends with one
    user message, `ASK_LAST_TURN`. The turn before it (`seek`) keeps its tools and ends with `ASK_SEEK_TURN`; the last
    turn wins when both are asked for."""
    if last:
        tools, items = None, [*items, _user_message(ASK_LAST_TURN)]
    elif seek:
        items = [*items, _user_message(ASK_SEEK_TURN)]
    body = {"model": ASK_MODEL, "max_output_tokens": ASK_MAX_OUTPUT_TOKENS, "input": items}
    if tools:
        body["tools"] = tools
    if previous_id:
        body["previous_response_id"] = previous_id
    return body
