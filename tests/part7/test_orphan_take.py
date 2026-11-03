"""TICKET-331: the job answer of a follow take says when the trainer deleted its movement (docs/specs/orphaned-take-result.md)."""

from __future__ import annotations

from typing import Any

from auth_support import get  # noqa: F401
from part7 import orphan_take
from support import Api

ENTRY = "knee-raise-orphan-take-b6635964"


def make_job(api: Api, entry: str | None = ENTRY) -> str:
    made = api.app.queue.submit("follow", lambda ctx: {"result": {}}, entry_id=entry)
    assert api.app.queue.wait(made["id"], 10)["status"] == "done"
    return made["id"]


def test_a_deleted_entry_is_flagged_and_an_existing_one_is_not(api: Api) -> None:
    job = make_job(api)
    assert get(api, f"api/jobs/{job}")[2]["entry_gone"] is True  # the entry folder is not in the catalog
    (api.app.child.catalog_dir / ENTRY).mkdir(parents=True, exist_ok=True)
    assert get(api, f"api/jobs/{job}")[2]["entry_gone"] is False  # negative: the entry exists


def test_a_take_without_a_usable_entry_id_is_never_called_gone() -> None:
    holder: Any = type("H", (), {"app": type("A", (), {"child": type("C", (), {"catalog_dir": None})()})()})()
    for bad in (None, "", 7, "../x", "A B"):
        assert orphan_take.entry_gone(holder, bad) is False
