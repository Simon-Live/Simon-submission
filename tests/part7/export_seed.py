"""Test helper only: SEEDED accounts with kept takes for the download-my-data tests (invented ids, labelled seeded).

Writes the same files `history_store._copy` writes (meta.json, analysis.json from a real fixture) without ffmpeg, so a
state with 300 takes builds in a second. Nothing here is product code.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from part7 import history_store

FIXTURES = Path(__file__).parent / "fixtures" / "history"
ENTRY = "body-squat-19b06562"


def job_id(tag: str, n: int) -> str:
    return hashlib.sha256(f"{tag}:{n}".encode()).hexdigest()[:12]


def seed_takes(state: Path, store: Any, user_id: str, tag: str, count: int, private: set[int] | None = None,
               entry: str = ENTRY, clip: bool = True) -> list[str]:
    """`count` kept follow takes for `user_id`; take numbers in `private` are private-mode takes. Returns the job ids."""
    analysis = (FIXTURES / "cc7cd5469055" / "analysis.json").read_text(encoding="utf-8")
    store.attach_entry(entry, user_id)
    ids = []
    for n in range(count):
        jid = job_id(tag, n)
        folder = history_store.take_dir(state, user_id, entry, jid)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / history_store.ANALYSIS_NAME).write_text(analysis, encoding="utf-8")
        if clip:
            (folder / history_store.CLIP_NAME).write_bytes(b"seeded clip bytes, never exported")
        meta = {"job_id": jid, "entry_id": entry, "at": f"2026-10-{1 + n % 28:02d}T10:{n % 60:02d}:00Z", "duration_s": 4.5,
                "duration_source": "job", "score": 100, "grade": "A", "private": n in (private or set()),
                "section_key": "full", "mode": "fitness", "score_version": "v1:abcd1234", "clip": clip, "kept_ts": 1.0}
        history_store.write_json(folder / history_store.META_NAME, meta)
        store.attach(jid, user_id, "follow", entry, None, "submit")
        ids.append(jid)
    return ids


def seed_report(state: Path, user_id: str, entry: str, job_ids: list[str]) -> None:
    doc = {"format": "simon.history.report.v1", "key": "k1", "entry_id": entry, "status": "ok", "model": "seeded-model",
           "prompt_version": "seeded.v1", "takes": [{"take": i + 1, "job_id": j} for i, j in enumerate(job_ids)],
           "summary": {"text": "Seeded summary."}, "usage": {"input_tokens": 10, "output_tokens": 5}}
    history_store.write_json(history_store.reports_dir(state, user_id, entry) / "k1.json", doc)
