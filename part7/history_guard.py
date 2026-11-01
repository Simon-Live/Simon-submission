"""The citation guard for the history report (docs/specs/history-meta.md, TICKET-181 AC-7 to AC-13).

`check(answer, facts, narration, words)` reads the model's `simon.history.v1` answer and keeps only the items that
pass seven deterministic rules against the stored data. Nothing the model says reaches a student unless the fact
table, the stored analyses and the teacher's own narration back it. Each failing item moves to `rejected` with the
rule and a plain reason; the guard never repairs an item.

Rules (the `rule` number in `rejected`):
1. cited: every item cites takes that are in the input set, with `at_s` finite and inside that take's duration.
2. fault claims: a cited `at_s` is inside the take's measured `span` for the same measure and side, or within
   FAULT_SLACK_S of a measured `at_s`.
3. trend `kind` agrees with the fact table's status for that measure and side.
4. numbers: only cited times, the cited takes' exact scores and the cited take labels ("take 2").
5. `focus.cue` is verbatim from the latest take's cues; a teacher quote is verbatim from narration.json.
6. no banned word, no praise, one line of at most MAX_LINE characters.
7. a dropped summary is replaced by the fact-table summary, labelled `source: "fact_table"`.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
import re
from typing import Any

MAX_TRENDS = 5
MAX_OBSERVATIONS = 3
MAX_LINE = 160
FAULT_SLACK_S = 1.0
KINDS = ("improved", "persistent", "fixed", "new")
LABEL = "model_opinion"

# Data, not code: `words` (contracts/student-words.json, TICKET-183) may replace either list. A trailing `*` is a
# prefix match; every other entry is the whole word.
DEFAULT_WORDS: dict[str, list[str]] = {
    "banned": ["coach*", "medic*", "injur*", "pain", "painful", "rehab*", "therap*", "diagnos*", "health*"],
    "praise": ["great", "good", "nice", "well done", "excellent", "perfect", "awesome", "impressive", "fantastic",
               "amazing", "bravo", "congrat*", "proud", "keep it up", "nailed it", "brilliant", "superb"],
}

_NUMBER = re.compile(r"(?<![\w.])\d+(?:\.\d+)?")
_QUOTE = re.compile(r"[\"“]([^\"”]+)[\"”]")
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


class _Context:
    """The facts, indexed once for all the rules."""

    def __init__(self, facts: dict[str, Any], narration: dict[str, Any] | None, words: dict[str, Any] | None):
        self.words = _Words(words)
        self.takes = {t["take"]: t for t in facts.get("takes") or [] if isinstance(t, dict) and "take" in t}
        self.measures = {(m.get("measure"), m.get("side")): m for m in facts.get("measures") or []
                         if isinstance(m, dict)}
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


def _rule3(item: dict[str, Any], ctx: _Context) -> Problem | None:
    entry = ctx.measures.get((item.get("measure"), item.get("side")))
    if entry is None:
        return 3, "the fact table has no such measure and side"
    if item.get("kind") not in KINDS or item["kind"] != entry.get("status"):
        return 3, "the kind does not agree with the fact table"
    return None


def _outside_quotes(text: str) -> str:
    return _QUOTE.sub(" ", text)


def _rule4(text: str, cites: list[dict[str, Any]], ctx: _Context) -> Problem | None:
    cited = {c["take"] for c in cites}
    times = {round(float(c["at_s"]), 3) for c in cites if "at_s" in c}
    scores = {round(float(ctx.takes[t]["score"]), 3) for t in cited if _num(ctx.takes[t].get("score"))}

    def labels(match: re.Match[str]) -> str:
        numbers = [int(n) for n in re.findall(r"\d+", match.group(1))]
        return "take" if all(n in cited for n in numbers) else match.group(0)

    bare = _TAKES.sub(labels, _outside_quotes(text))
    for token in _NUMBER.findall(bare):
        if round(float(token), 3) not in times | scores:
            return 4, "a number that is not a cited time or a cited score"
    return None


def _rule5_quotes(text: str, source: str | None) -> Problem | None:
    quotes = _QUOTE.findall(text)
    if not quotes or source is None:
        return 5, "no quote from the teacher's narration"
    if any(q not in source for q in quotes):
        return 5, "a quote is not verbatim from the teacher's narration"
    return None


def _rule6(text: Any, ctx: _Context) -> Problem | None:
    if not isinstance(text, str) or not text.strip():
        return 6, "empty text"
    if "\n" in text or "\r" in text or len(text) > MAX_LINE:
        return 6, f"not one line of {MAX_LINE} characters or fewer"
    text = clean_text(text, ctx.words.ignored)
    if ctx.words.banned and ctx.words.banned.search(text):
        return 6, "uses a word this product does not use"
    if ctx.words.praise and ctx.words.praise.search(_outside_quotes(text)):
        return 6, "adds praise"
    return None


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
    if kind in ("trend", "focus"):
        problem = _rule2(item, cites, ctx)
        if not problem and kind == "trend":
            problem = _rule3(item, ctx)
    if not problem and kind == "focus":
        cue = item.get("cue")
        problem = None if cue in ctx.latest_cues() else (5, "the cue is not one of the latest take's cues")
        texts.append(cue)
    if not problem and kind == "teacher_link":
        source = ctx.narration.get(item.get("cue_index"))
        problem = (5, "no such narration cue") if source is None else _rule5_quotes(str(item.get("text")), source)
    problem = problem or _text_rules(texts, cites, ctx)
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
    """Rule 7: the summary computed from the fact table, with no model, labelled as such."""
    takes = sorted((t for t in facts.get("takes") or [] if isinstance(t, dict) and "take" in t),
                   key=lambda t: t["take"])
    scores = [t["score"] for t in takes if _num(t.get("score"))]
    if len(scores) >= 2:
        text = f"Your score went from {scores[0]} to {scores[-1]} across {len(takes)} takes."
    elif scores:
        text = f"You have one take so far, scored {scores[0]}."
    else:
        text = "There are no scored takes yet."
    return {"text": text, "cites": [{"take": t["take"]} for t in takes], "source": "fact_table"}


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
          words: dict[str, Any] | None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """C-REPORT: `(kept, rejected)`. `kept` is `{summary, trends, focus, teacher_link, observations}`."""
    ctx = _Context(facts, narration, words)
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
