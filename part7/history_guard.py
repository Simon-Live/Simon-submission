"""The citation guard for the history report (docs/specs/history-meta.md, TICKET-181 AC-7 to AC-13).

`check(answer, facts, narration, words, clip_takes=())` reads the model's `simon.history.v1` answer and keeps only the items that
pass ten deterministic rules against the stored data. Nothing the model says reaches a student unless the fact
table, the stored analyses and the teacher's own narration back it. Each failing item moves to `rejected` with the
rule and a plain reason; the guard never repairs an item.

Rules (the `rule` number in `rejected`; ten):
1. cited: every item cites takes that are in the input set, with `at_s` finite and inside that take's duration.
2. fault claims: a cited `at_s` is inside the take's measured `span` for the same measure and side, or within
   FAULT_SLACK_S of a measured `at_s`.
3. trend `kind` agrees with the fact table's status for that measure and side (`unverified` is never a kind). `plateau`
   is a kind only where `facts["series"]` lists that plateau (same measure and side) and cites only its takes; a
   fault that has not moved is a plateau, whatever its status. `early_sign` is a kind only where the series lists
   that early sign, and cites its `near_take` (no time: a near miss has no measured moment) and its `fault_take`.
4. numbers: only cited times, the cited takes' exact scores and the cited take labels ("take 2").
5. `focus.cue` is verbatim from the latest take's cues; a teacher quote is verbatim from narration.json.
6. no banned word, no praise, one line of at most MAX_LINE characters.
7. a dropped summary is replaced by the fact-table summary, labelled `source: "fact_table"`.
8. an observation (something seen in a take's video) is kept only for a take whose clip was sent in this request
   (`clip_takes`, the take numbers `history_prompt.pack` returns as `clip_takes`).
9. side and body-part words in a trend or focus must match the cited fault's measure, side and joint; in an
   observation, they must match a fault measured at the cited moment when there is one.
10. a rep number ("rep 3", "reps 2 and 3") must be a rep Part 5 gave data for in a cited take: its `faults[].rep_sizes`
    or `score.per_rep` (analysis 1.12.0), numbered from 1 as the prompt sends them (the row's `rep_numbers`). A take with
    none (an older document, or one not compared rep by rep) backs no rep number.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
import re
from typing import Any

from part7 import shown_score

MAX_TRENDS = 5
MAX_OBSERVATIONS = 3
MAX_LINE = 160
FAULT_SLACK_S = 1.0
SERIES_KINDS = ("plateau", "early_sign")   # backed by `facts["series"]` (TICKET-218), not by a measure's status
KINDS = ("improved", "persistent", "fixed", "new", "came_back") + SERIES_KINDS
LABEL = "model_opinion"

# Data, not code: `words` (contracts/student-words.json, TICKET-183) may replace either list. A trailing `*` is a
# prefix match; every other entry is the whole word.
DEFAULT_WORDS: dict[str, list[str]] = {
    "banned": ["coach*", "medic*", "injur*", "pain", "painful", "rehab*", "therap*", "diagnos*", "health*"],
    "praise": ["great", "good", "nice", "well done", "excellent", "perfect", "awesome", "impressive", "fantastic",
               "amazing", "bravo", "congrat*", "proud", "keep it up", "nailed it", "brilliant", "superb"],
}

# Body parts and sides a claim may name. Each word maps to one part; a claim may name only the parts its fault is about.
PARTS: dict[str, str] = {
    "knee": "knee", "knees": "knee", "hip": "hip", "hips": "hip", "elbow": "elbow", "elbows": "elbow",
    "shoulder": "shoulder", "shoulders": "shoulder", "ankle": "ankle", "ankles": "ankle", "wrist": "wrist", "wrists": "wrist",
    "arm": "arm", "arms": "arm", "leg": "leg", "legs": "leg", "foot": "foot", "feet": "foot", "head": "head", "neck": "neck",
    "spine": "trunk", "trunk": "trunk", "torso": "trunk", "chest": "trunk",
}
_SIDE_WORD = re.compile(r"\b(left|right)\b", re.I)
_PART_WORD = re.compile(r"\b(" + "|".join(PARTS) + r")\b", re.I)
_NUMBER = re.compile(r"(?<![\w.])\d+(?:\.\d+)?")
_GROUPED = re.compile(r"(\d),(\d{3})\b")  # "16,239" is one number (the shown points), not 16 and 239
_QUOTE = re.compile(r"[\"“]([^\"”]+)[\"”]")
_REPS = re.compile(r"\b(?:reps?|repetitions?)\s+(\d+(?:\s*(?:,|and|&|to|-)\s*\d+)*)", re.I)
_TAKES = re.compile(r"\btakes?\s+(\d+(?:\s*(?:,|and|&)\s*\d+)*)", re.I)


def _num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


_ZERO_WIDTH = dict.fromkeys(map(ord, "\u200b\u200c\u200d\u2060\ufeff"))
WORDS_FILE = "contracts/student-words.json"   # in the pinned Part 5 clone (TICKET-183)


def _word_regex(entries: list[str]) -> re.Pattern[str] | None:
    """Case-insensitive, word-bounded; the words of a phrase are joined by whitespace or a hyphen."""
    parts = []
    for entry in entries:
        words = entry.strip().lower().split() if isinstance(entry, str) else []
        if not words:
            continue
        escaped = [re.escape(w[:-1]) + r"\w*" if w.endswith("*") else re.escape(w) for w in words]
        parts.append(r"[\s\-]+".join(escaped))
    return re.compile(r"\b(?:" + "|".join(parts) + r")\b", re.I) if parts else None


def _ignored_table(raw: Any) -> dict[int, None]:
    """Part 5's `ignored_characters` (a string, or a list of characters or "U+200B" names) joined to the zero-width set."""
    chars = list(raw) if isinstance(raw, str) else [x for x in raw if isinstance(x, str)] if isinstance(raw, list) else []
    table = dict(_ZERO_WIDTH)
    for item in chars:
        code = re.fullmatch(r"(?:U\+|\\u)([0-9A-Fa-f]{4,6})", item.strip())
        for char in ([chr(int(code.group(1), 16))] if code else list(item)):
            table[ord(char)] = None
    return table


def load_words(path: Path | str | None = None) -> dict[str, Any]:
    """Part 5's `simon.student-words.v1` when the file exists and parses, else DEFAULT_WORDS.

    The file's `banned` stems and `praise` phrases are used as given (a trailing `*` is a prefix); the whole-word "pain"
    of DEFAULT_WORDS applies to our own defaults only. Its other keys are ignored, except `ignored_characters`, which
    is kept as `ignored` and removed from the answer before the rules read it."""
    from part7 import config
    file = Path(path) if path is not None else config.part_dir(5) / WORDS_FILE
    try:
        doc = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return DEFAULT_WORDS
    if not isinstance(doc, dict) or not (doc.get("banned") or doc.get("praise")):
        return DEFAULT_WORDS
    words: dict[str, Any] = {k: doc[k] if isinstance(doc.get(k), list) and doc[k] else DEFAULT_WORDS[k] for k in DEFAULT_WORDS}
    if "ignored_characters" in doc:
        words["ignored"] = doc["ignored_characters"]
    return words


def clean_text(text: str, table: dict[int, None] | None = None) -> str:
    return text.translate(table or _ZERO_WIDTH)


class _Words:
    def __init__(self, words: dict[str, Any] | None):
        words = words if isinstance(words, dict) else load_words()
        self.banned = _word_regex(words.get("banned") or DEFAULT_WORDS["banned"])
        self.praise = _word_regex(words.get("praise") or DEFAULT_WORDS["praise"])
        self.ignored = _ignored_table(words.get("ignored"))


Words = _Words  # the public name, for history_ask_guard


class _Context:
    """The facts, indexed once for all the rules."""

    def __init__(self, facts: dict[str, Any], narration: dict[str, Any] | None, words: dict[str, Any] | None,
                 clip_takes: Any = ()):
        self.words = _Words(words)
        self.clip_takes = {n for n in clip_takes or () if isinstance(n, int) and not isinstance(n, bool)}
        self.takes = {t["take"]: t for t in facts.get("takes") or [] if isinstance(t, dict) and "take" in t}
        self.measures = {(m.get("measure"), m.get("side")): m for m in facts.get("measures") or []
                         if isinstance(m, dict)}
        series = facts.get("series") if isinstance(facts.get("series"), dict) else {}
        self.plateaus = [p for p in series.get("plateaus") or [] if isinstance(p, dict)]
        self.early_signs = [e for e in series.get("early_signs") or [] if isinstance(e, dict)]
        latest = facts.get("latest")
        latest = latest.get("take") if isinstance(latest, dict) else latest
        self.latest = latest if latest in self.takes else (max(self.takes) if self.takes else None)
        cues = narration.get("cues") if isinstance(narration, dict) else None
        self.narration = {c.get("index"): c.get("text") for c in cues or []
                          if isinstance(c, dict) and isinstance(c.get("text"), str)}

    def latest_cues(self) -> set[str]:
        take = self.takes.get(self.latest) or {}
        found = {c if isinstance(c, str) else c.get("cue") for c in take.get("cues") or []
                 if isinstance(c, str) or isinstance(c, dict)}
        found |= {f.get("cue") for f in take.get("faults") or [] if isinstance(f, dict)}
        return {c for c in found if isinstance(c, str)}


Problem = tuple[int, str]


def _cites(cites: Any, ctx: _Context) -> tuple[list[dict[str, Any]], Problem | None]:
    """Rule 1 on a `cites` list; returns the normalised cites."""
    if not isinstance(cites, list) or not cites:
        return [], (1, "no citation")
    clean = []
    for cite in cites:
        take = cite.get("take") if isinstance(cite, dict) else None
        if not isinstance(take, int) or isinstance(take, bool) or take not in ctx.takes:
            return [], (1, "cites a take that was not in the input")
        at_s = cite.get("at_s")
        if at_s is None:
            clean.append({"take": take})
            continue
        duration = ctx.takes[take].get("duration_s")
        if not _num(at_s) or at_s < 0 or (_num(duration) and at_s > duration):
            return [], (1, "cites a time outside the take")
        clean.append({"take": take, "at_s": at_s})
    return clean, None


def _fault_ok(take: dict[str, Any], measure: Any, side: Any, at_s: float) -> bool:
    for fault in take.get("faults") or []:
        if not isinstance(fault, dict) or fault.get("measure") != measure or fault.get("side") != side:
            continue
        span = fault.get("span") or fault.get("follower_t_s")
        if isinstance(span, (list, tuple)) and len(span) == 2 and all(_num(s) for s in span) \
                and span[0] <= at_s <= span[1]:
            return True
        if _num(fault.get("at_s")) and abs(fault["at_s"] - at_s) <= FAULT_SLACK_S:
            return True
    return False


def _rule2(item: dict[str, Any], cites: list[dict[str, Any]], ctx: _Context) -> Problem | None:
    for cite in cites:
        if "at_s" in cite and not _fault_ok(ctx.takes[cite["take"]], item.get("measure"), item.get("side"),
                                            cite["at_s"]):
            return 2, "a fault time is not where the analysis measured that fault"
    return None


def _rule3_series(item: dict[str, Any], cites: list[dict[str, Any]], ctx: _Context) -> Problem | None:
    """Rule 3 for `plateau` and `early_sign`: the item must be one the series lists, citing what that row cites."""
    key = (item.get("measure"), item.get("side"))
    taken = [c["take"] for c in cites]
    if item["kind"] == "plateau":
        rows = [p for p in ctx.plateaus if (p.get("measure"), p.get("side")) == key]
        if not rows or not set(taken) <= set(rows[0].get("takes") or []):
            return 3, "the series has no such plateau"
        return None
    rows = [e for e in ctx.early_signs if (e.get("measure"), e.get("side")) == key
            and {e.get("near_take"), e.get("fault_take")} <= set(taken)]
    if not rows:
        return 3, "the series has no such early sign"
    if any("at_s" in c for c in cites if c["take"] == rows[0]["near_take"]):  # a near miss has no measured moment to cite
        return 3, "a near miss has no time to cite"
    return None


def _rule3(item: dict[str, Any], ctx: _Context, cites: list[dict[str, Any]] | None = None) -> Problem | None:
    if item.get("kind") in SERIES_KINDS:
        return _rule3_series(item, cites or [], ctx)
    entry = ctx.measures.get((item.get("measure"), item.get("side")))
    if entry is None:
        return 3, "the fact table has no such measure and side"
    if item.get("kind") not in KINDS or item["kind"] != entry.get("status"):
        return 3, "the kind does not agree with the fact table"
    return None


def _parts_of(*names: Any) -> set[str]:
    """The body parts a fault is about: the words of its measure, joint and body part, as PARTS knows them."""
    found = set()
    for name in names:
        for word in re.split(r"[^a-z]+", name.lower()) if isinstance(name, str) else []:
            if word in PARTS:
                found.add(PARTS[word])
    return found


def _named_matches(text: str, fault: dict[str, Any]) -> bool:
    """True when every side and body-part word of `text` is one the fault's measure, side and joint allow."""
    side = fault.get("side") if isinstance(fault.get("side"), str) else "center"
    if side != "both" and any(w.lower() != side for w in _SIDE_WORD.findall(text)):
        return False
    allowed = _parts_of(fault.get("measure"), fault.get("joint"), fault.get("body_part"))
    return all(PARTS[w.lower()] in allowed for w in _PART_WORD.findall(text))


def _reference_fault(item: dict[str, Any], ctx: _Context) -> dict[str, Any]:
    """The fault a trend or focus talks about: its measure and side, with the joint and body part any take recorded."""
    for take in ctx.takes.values():
        for fault in take.get("faults") or []:
            if isinstance(fault, dict) and fault.get("measure") == item.get("measure") and fault.get("side") == item.get("side"):
                return fault
    return {"measure": item.get("measure"), "side": item.get("side")}


def _rule9(kind: str, item: dict[str, Any], cites: list[dict[str, Any]], ctx: _Context) -> Problem | None:
    text = _outside_quotes(str(item.get("text")))
    if not (_SIDE_WORD.search(text) or _PART_WORD.search(text)):
        return None
    if kind == "observation":  # it cites no fault: it must agree with any fault measured at the moment it cites
        take = ctx.takes[cites[0]["take"]]
        near = [f for f in take.get("faults") or [] if isinstance(f, dict)
                and _fault_ok({"faults": [f]}, f.get("measure"), f.get("side"), cites[0]["at_s"])]
        if near and not any(_named_matches(text, f) for f in near):
            return 9, "names a side or body part the analysis did not measure there"
        return None
    if not _named_matches(text, _reference_fault(item, ctx)):
        return 9, "names a side or body part that is not the cited fault's"
    return None


def _outside_quotes(text: str) -> str:
    return _QUOTE.sub(" ", text)


def _rule4(text: str, cites: list[dict[str, Any]], ctx: _Context) -> Problem | None:
    cited = {c["take"] for c in cites}
    times = {round(float(c["at_s"]), 3) for c in cites if "at_s" in c}
    scores = {round(float(ctx.takes[t]["score"]), 3) for t in cited if _num(ctx.takes[t].get("score"))}
    figures = set().union(*(shown_score.numbers_in(ctx.takes[t].get("shown")) for t in cited))  # one-letter.md L7: 16,239 of 22,367

    def labels(match: re.Match[str]) -> str:
        numbers = [int(n) for n in re.findall(r"\d+", match.group(1))]
        return "take" if all(n in cited for n in numbers) else match.group(0)

    bare = _REPS.sub("rep", _TAKES.sub(labels, _outside_quotes(text)))  # rep numbers are checked by rule 10
    tokens = {round(float(token), 3) for token in _NUMBER.findall(_GROUPED.sub(r"\1\2", bare))}
    if tokens - (times | scores | figures):
        return 4, "a number that is not a cited time or a cited score"
    shown = {t for t in cited if _num(ctx.takes[t].get("score")) and round(float(ctx.takes[t]["score"]), 3) in tokens}
    if len({_scale(ctx.takes[t]) for t in shown}) > 1:  # TICKET-208: a score line is one section, mode and score version
        return 4, "compares scores of takes that were not scored the same way"
    return None


def _rule10(texts: list[str], cites: list[dict[str, Any]], ctx: _Context) -> Problem | None:
    """Every rep number in the text exists in `rep_numbers` of at least one cited take."""
    known: set[int] = set()
    for c in cites:
        known |= {n for n in ctx.takes[c["take"]].get("rep_numbers") or [] if isinstance(n, int) and not isinstance(n, bool)}
    for text in texts:
        for match in _REPS.finditer(_outside_quotes(text) if isinstance(text, str) else ""):
            if any(int(n) not in known for n in re.findall(r"\d+", match.group(1))):
                return 10, "names a rep that is not in the cited take's rep sizes or per-rep scores"
    return None


def _scale(row: dict[str, Any]) -> tuple[Any, ...]:
    """What makes two scores comparable: section, mode, score version, and whether Part 7 found a person at all."""
    return row.get("section_key"), row.get("mode"), row.get("score_scale", row.get("score_version")), bool(row.get("no_person")), row.get("reference") or "teacher"


def _rule5_quotes(text: str, source: str | None) -> Problem | None:
    quotes = _QUOTE.findall(text)
    if not quotes or source is None:
        return 5, "no quote from the teacher's narration"
    if any(q not in source for q in quotes):
        return 5, "a quote is not verbatim from the teacher's narration"
    return None


def text_problem(text: Any, words: _Words, limit: int = MAX_LINE) -> str | None:
    """Why `text` is not one plain line of at most `limit` characters (empty, long, a banned word, praise), or None.

    The one place the line rules live: rule 6 below and the question answers of history_ask_guard both call it."""
    if not isinstance(text, str) or not text.strip():
        return "empty text"
    if "\n" in text or "\r" in text or len(text) > limit:
        return f"not one line of {limit} characters or fewer"
    text = clean_text(text, words.ignored)
    if words.banned and words.banned.search(text):
        return "uses a word this product does not use"
    if words.praise and words.praise.search(_outside_quotes(text)):
        return "adds praise"
    return None


def _rule6(text: Any, ctx: _Context) -> Problem | None:
    found = text_problem(text, ctx.words)
    return (6, found) if found else None


def _text_rules(texts: list[str], cites: list[dict[str, Any]], ctx: _Context) -> Problem | None:
    for text in texts:
        found = _rule6(text, ctx) or _rule4(text, cites, ctx)
        if found:
            return found
    return None


def _judge(item: Any, kind: str, ctx: _Context) -> tuple[dict[str, Any] | None, Problem | None]:
    """One item through the rules in order; returns the cleaned item or the first problem."""
    if not isinstance(item, dict):
        return None, (1, "not an object")
    if kind == "observation":
        cites, problem = _cites([{"take": item.get("take"), "at_s": item.get("at_s")}], ctx)
        if not problem and "at_s" not in cites[0]:
            problem = (1, "no time")
    else:
        cites, problem = _cites(item.get("cites"), ctx)
    if problem:
        return None, problem
    texts = [item.get("text")]
    if kind == "observation" and cites[0]["take"] not in ctx.clip_takes:
        problem = (8, "the video of that take was not sent")
    if not problem and kind in ("trend", "focus"):
        problem = _rule2(item, cites, ctx)
        if not problem and kind == "trend":
            problem = _rule3(item, ctx, cites)
    if not problem and kind == "focus":
        cue = item.get("cue")
        problem = None if cue in ctx.latest_cues() else (5, "the cue is not one of the latest take's cues")
        texts.append(cue)
    if not problem and kind == "teacher_link":
        source = ctx.narration.get(item.get("cue_index"))
        problem = (5, "no such narration cue") if source is None else _rule5_quotes(str(item.get("text")), source)
    problem = problem or _text_rules(texts, cites, ctx) or _rule10([t for t in texts if isinstance(t, str)], cites, ctx)
    if not problem and kind in ("trend", "focus", "observation"):
        problem = _rule9(kind, item, cites, ctx)
    return (None, problem) if problem else (_clean(item, kind, cites), None)


def _clean(item: dict[str, Any], kind: str, cites: list[dict[str, Any]]) -> dict[str, Any]:
    if kind == "observation":
        return {"take": cites[0]["take"], "at_s": cites[0]["at_s"], "text": item["text"], "label": LABEL}
    out = {"text": item["text"], "cites": cites}
    if kind == "trend":
        out.update(kind=item["kind"], measure=item["measure"], side=item["side"])
    if kind == "focus":
        out.update(measure=item["measure"], side=item["side"], cue=item["cue"])
    if kind == "teacher_link":
        out["cue_index"] = item["cue_index"]
    return out


def fact_summary(facts: dict[str, Any]) -> dict[str, Any]:
    """Rule 7: the summary computed from the fact table, with no model, labelled as such.

    Only takes of the latest take's section, mode and score version make one score line (`in_group` and the
    latest's `score_version`); a table without those marks counts every take, as before TICKET-206."""
    takes = sorted((t for t in facts.get("takes") or [] if isinstance(t, dict) and "take" in t), key=lambda t: t["take"])
    latest = next((t for t in reversed(takes) if t.get("in_group", True) and not t.get("no_person")), None) or (takes[-1] if takes else None)
    scale = lambda t: t.get("score_scale", t.get("score_version"))  # noqa: E731 (the v1 rescale of 2026-10-30 splits a version)
    line = [t for t in takes if t.get("in_group", True) and scale(latest or {}) == scale(t)]
    line = line or takes[-1:]
    scores = [t["score"] for t in line if _num(t.get("score"))]
    if len(scores) >= 2:
        text = f"Your score went from {scores[0]} to {scores[-1]} across {len(line)} takes."
    elif scores:
        text = f"You have one take so far, scored {scores[0]}."
    else:
        text = "There are no scored takes yet."
    return {"text": text, "cites": [{"take": t["take"]} for t in line], "source": "fact_table"}


def parse_answer(answer: Any) -> dict[str, Any] | None:
    """The answer as a dict: a dict as given, else JSON text (with a fallback to the outermost braces)."""
    if isinstance(answer, dict):
        return answer
    if not isinstance(answer, str):
        return None
    for candidate in (answer, answer[answer.find("{"):answer.rfind("}") + 1]):
        try:
            doc = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(doc, dict):
            return doc
    return None


def _list(doc: dict[str, Any], key: str, limit: int, kind: str, ctx: _Context,
          rejected: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items = doc.get(key)
    kept: list[dict[str, Any]] = []
    for i, item in enumerate(items if isinstance(items, list) else []):
        clean, problem = _judge(item, kind, ctx) if len(kept) < limit else (None, (0, f"more than {limit} items"))
        if clean is not None:
            kept.append(clean)
        else:
            rejected.append({"item": f"{key}[{i}]", "rule": problem[0] or None, "reason": problem[1]})
    return kept


def _single(doc: dict[str, Any], key: str, kind: str, ctx: _Context,
            rejected: list[dict[str, Any]]) -> dict[str, Any] | None:
    item = doc.get(key)
    if item is None:
        return None
    clean, problem = _judge(item, kind, ctx)
    if clean is None:
        rejected.append({"item": key, "rule": problem[0], "reason": problem[1]})
    return clean


def check(answer: Any, facts: dict[str, Any], narration: dict[str, Any] | None,
          words: dict[str, Any] | None, clip_takes: Any = ()) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """C-REPORT: `(kept, rejected)`. `kept` is `{summary, trends, focus, teacher_link, observations}`.

    `clip_takes` are the numbers of the takes whose clip went in this request; an observation about any other take is
    rejected (rule 8), so nothing is claimed as seen in a video the model never had."""
    ctx = _Context(facts, narration, words, clip_takes)
    rejected: list[dict[str, Any]] = []
    doc = parse_answer(answer)
    if doc is None:
        rejected.append({"item": "answer", "rule": None, "reason": "the answer was not a JSON object"})
        doc = {}
    summary = _single(doc, "summary", "summary", ctx, rejected)
    if summary is None:
        summary = fact_summary(facts)
        if "summary" not in doc:
            rejected.append({"item": "summary", "rule": 7, "reason": "no summary in the answer"})
    else:
        summary["source"] = "model"
    kept = {
        "summary": summary,
        "trends": _list(doc, "trends", MAX_TRENDS, "trend", ctx, rejected),
        "focus": _single(doc, "focus", "focus", ctx, rejected),
        "teacher_link": _single(doc, "teacher_link", "teacher_link", ctx, rejected),
        "observations": _list(doc, "observations", MAX_OBSERVATIONS, "observation", ctx, rejected),
    }
    return kept, rejected
