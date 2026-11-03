"""TICKET-284: the owner-only routes over mesh_stream_files (docs/specs/mesh-stream.md "Routes")."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

import pytest

from history_support import OTHER, USER, World, world  # noqa: F401
from part7 import mesh_stream_files as ms
from part7 import mesh_stream_routes as routes
from support import Api

ENTRY = "lateral-raise-0f13199f"


class Running:
    """A follow job held in `running` until `release()`; its stream folder is filled by the test."""

    def __init__(self, api: Api, world: World, owner: str | None = USER, kind: str = "follow") -> None:
        self.gate, self.started = threading.Event(), threading.Event()

        def fn(ctx: Any) -> dict[str, Any]:
            self.started.set()
            self.gate.wait(20)
            return {"result": {"entry_id": ENTRY}}

        self.api = api
        self.id = api.app.queue.submit(kind, fn, entry_id=ENTRY)["id"]
        assert self.started.wait(10)
        if owner:
            world.owners[self.id] = owner
        self.folder = api.app.queue.job_dir(self.id) / "work" / "follower" / "part2" / ms.FOLDER

    def fill(self, chunks: int, done: bool = False, total: int | None = 5) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        (self.folder / "head.bin").write_bytes(b"\0" * 8)
        for i in range(chunks):
            (self.folder / f"chunk-{i:04d}.bin").write_bytes(bytes([i + 1]) * 12)
        doc = {"format": "part2.mesh3d-stream/2026-11-02", "head": {"file": "head.bin", "vertex_count": 2}, "block_bytes": 12,
               "frames_total": total, "done": done,
               "chunks": [{"file": f"chunk-{i:04d}.bin", "first_block": i, "blocks": 1} for i in range(chunks)],
               "frames": [{"frame": i, "t_ms": i * 100.0, "people": [{"id": 0, "block": i}]} for i in range(chunks)]}
        (self.folder / ms.MANIFEST).write_text(json.dumps(doc))

    def snap(self, user: str | None = USER) -> tuple[int, Any]:
        return self.api.json("GET", f"api/jobs/{self.id}/mesh-stream", headers={"X-Test-User": user} if user else {})

    def file(self, name: str, user: str | None = USER) -> tuple[int, dict[str, str], bytes]:
        return self.api.request("GET", f"api/results/{self.id}/mesh-stream/{name}", headers={"X-Test-User": user} if user else {})

    def release(self) -> None:
        self.gate.set()
        assert self.api.app.queue.wait(self.id, 10)["status"] == "done"


@pytest.fixture()
def run(api: Api, world: World):  # noqa: F811
    job = Running(api, world)
    yield job
    job.gate.set()


@pytest.fixture(autouse=True)
def _fresh_limiter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(routes, "_limiter", routes.Limiter(1000, 1.0))


def test_snapshot_grows_while_the_job_runs_and_files_are_served(run: Running) -> None:  # AC-4: the count rises
    assert run.snap()[1]["stream"] is None and run.snap()[1]["closed"] is False  # nothing flushed yet: no error, no stream
    run.fill(2)
    status, doc = run.snap()
    assert status == 200 and doc["closed"] is False and doc["stream"]["frames_done"] == 2 and doc["stream"]["frames_total"] == 5
    run.fill(3)
    assert run.snap()[1]["stream"]["frames_done"] == 3
    status, headers, body = run.file("chunk-0002.bin")
    assert status == 200 and body == bytes([3]) * 12 and headers["content-type"] == "application/octet-stream"
    assert run.file("stream.json")[2].startswith(b"{")


def test_signed_out_is_401_and_a_non_owner_is_404(run: Running, api: Api) -> None:
    run.fill(1)
    assert run.snap(None)[0] == 401 and run.file("head.bin", None)[0] == 401
    assert run.snap(OTHER)[0] == 404 and run.file("head.bin", OTHER)[0] == 404
    assert api.json("GET", "api/jobs/ffffffffffff/mesh-stream", headers={"X-Test-User": USER})[0] == 404
    assert api.json("GET", "api/jobs/NOTANID/mesh-stream", headers={"X-Test-User": USER})[0] == 404


def test_an_unowned_job_and_a_trainer_job_are_not_served(api: Api, world: World) -> None:  # noqa: F811
    for job in (Running(api, world, owner=None), Running(api, world, kind="trainer")):
        try:
            assert job.snap()[0] == 404
        finally:
            job.gate.set()


def test_closed_when_the_job_ends(run: Running) -> None:
    run.fill(2, done=True)
    run.release()
    status, doc = run.snap()
    assert status == 200 and doc["closed"] is True and doc["stream"] is None
    assert run.file("head.bin")[0] == 404


def test_only_the_three_file_shapes_and_no_symlink(run: Running, tmp_path: Path) -> None:
    run.fill(1)
    outside = tmp_path / "secret.bin"
    outside.write_bytes(b"x")
    (run.folder / "chunk-0009.bin").symlink_to(outside)
    for name in ("chunk-0009.bin", "mesh3d.bin", "..%2Fjob.json", "chunk-1.bin"):
        assert run.file(name)[0] == 404, name


def test_big_files_are_not_served_and_the_rate_is_bounded(run: Running, monkeypatch: pytest.MonkeyPatch) -> None:
    run.fill(1)
    monkeypatch.setattr(routes, "MAX_FILE_BYTES", 4)
    assert run.file("chunk-0000.bin")[0] == 404
    monkeypatch.setattr(routes, "_limiter", routes.Limiter(2, 60.0))
    assert [run.snap()[0] for _ in range(3)] == [200, 200, 429]


def test_job_answer_hints_the_stream_only_to_the_owner(run: Running, api: Api) -> None:  # no 401 or 404 for any other page
    owner = api.json("GET", f"api/jobs/{run.id}", headers={"X-Test-User": USER})[1]
    assert owner["mesh_stream"] == {"url": f"api/jobs/{run.id}/mesh-stream", "model": "SAM 3D Body"}
    assert api.json("GET", f"api/jobs/{run.id}", headers={"X-Test-User": OTHER})[1]["mesh_stream"] is None
    assert api.json("GET", f"api/jobs/{run.id}")[1]["mesh_stream"] is None
    run.release()
    assert api.json("GET", f"api/jobs/{run.id}", headers={"X-Test-User": USER})[1]["mesh_stream"] is None


def test_reading_never_writes_the_folder(run: Running) -> None:  # AC-1 (Part 7 part)
    run.fill(2)
    before = sorted((p.name, p.read_bytes()) for p in run.folder.iterdir())
    for _ in range(3):
        run.snap()
        run.file("chunk-0001.bin")
    assert sorted((p.name, p.read_bytes()) for p in run.folder.iterdir()) == before
