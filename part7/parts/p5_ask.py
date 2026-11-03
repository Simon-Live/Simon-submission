"""Part 5 adapter: `part5 ask`, the Muse Wonder agent over one analysed take (TICKET-269; contract: Part 5 `ask-this-take.md`).

Part 7 sends the question and the two files of the take (`analysis.json`, `replay.json`) and reads back one `simon.ask.v1`
document. Part 5 makes the model calls and records the spend in its own ledger (`meta_api.call`, purpose `ask`); this module
makes none and writes none. The question rides after `--` so a question that starts with a dash is never read as a flag.
"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile

from part7 import config, modules, runner
from part7.parts import probe

_ARGV = ["uv", "run", "python", "-m", "part5", "ask"]
FORMAT = "simon.ask.v1"


class AskError(RuntimeError):
    """Part 5 gave no document; `reason` is short and holds no key and no model text."""


def available(lock: modules.Modules | None = None) -> bool:
    """True when the pinned Part 5 has the `ask` command (its help lists `--live`)."""
    try:
        lk = lock or modules.load()
        return probe.has_flag(5, _ARGV, lk.path("5"), "--live", lk)
    except Exception:  # a missing clone or a failed probe means no agent
        return False


def run(question: str, analysis: Path | str, replay: Path | str, work: Path | str, lock: modules.Modules | None = None,
        live: bool = True) -> dict:
    """Run `part5 ask` and return its document. `AskError` when the command is missing, exits non-zero or writes no document."""
    lk = lock or modules.load()
    clone = lk.path("5")
    if not probe.has_flag(5, _ARGV, clone, "--live", lk):
        raise AskError("Part 5 at this pin has no ask command")
    work_p = Path(work)
    with tempfile.TemporaryDirectory(prefix="ask-", dir=work_p if work_p.is_dir() else None) as scratch:
        out = Path(scratch) / "ask.json"
        argv = [*_ARGV, "--out", str(out), *(["--live"] if live else []), "--", str(Path(analysis).resolve()), str(Path(replay).resolve()), question]
        step = runner.run(5, argv, cwd=clone, timeout_s=config.TIMEOUTS["5"], log_path=work_p / "steps" / "part5_ask.log", lock=lk)
        if step["exit"] != 0 or not out.is_file():
            raise AskError(f"part5 ask exited {step['exit']}")
        try:
            doc = json.loads(out.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise AskError("part5 ask wrote no readable document") from None
    if not isinstance(doc, dict) or doc.get("format") != FORMAT:
        raise AskError("part5 ask wrote a document of another format")
    return doc
