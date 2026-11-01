"""Each person's mesh of a finished follow job (docs/specs/result-redesign-additions.md R3; AC-R3a to AC-R3c)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from part7 import jobs, mesh_files
from support import Api

ENTRY = "lateral-raise-0f13199f"
HEADER = b'{"format": "part2.mesh3d/2026-10-31", "bin": "mesh3d.bin"}'
BIN = bytes(range(16))


def put_mesh(folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "mesh3d.json").write_bytes(HEADER)
    (folder / "mesh3d.bin").write_bytes(BIN)


def finished(api: Api, kind: str, fill: Callable[[Path], None]) -> str:
    def fn(ctx: jobs.JobContext) -> dict[str, Any]:
        fill(ctx.dir)
        return {"result": {"entry_id": ENTRY}}

    rec = api.app.queue.submit(kind, fn, entry_id=ENTRY)
    assert api.app.queue.wait(rec["id"], 10)["status"] == "done"
    return rec["id"]


def test_index_and_files_when_both_meshes_exist(api: Api) -> None:
    finished(api, "trainer", lambda d: put_mesh(d / "work" / "trainer" / "part2"))
    jid = finished(api, "follow", lambda d: put_mesh(d / "work" / "follower" / "part2"))
    status, doc = api.json("GET", f"api/results/{jid}/mesh.json")
    assert status == 200
    assert doc == {"trainer": f"api/results/{jid}/mesh/trainer/mesh3d.json", "you": f"api/results/{jid}/mesh/you/mesh3d.json"}
    status, headers, body = api.request("GET", f"api/results/{jid}/mesh/you/mesh3d.json")
    assert status == 200 and body == HEADER and headers["content-type"].startswith("application/json")
    status, headers, body = api.request("GET", f"api/results/{jid}/mesh/trainer/mesh3d.bin")
    assert status == 200 and body == BIN and headers["content-type"] == "application/octet-stream"


def test_index_is_null_without_meshes_and_files_404(api: Api) -> None:
    # the follower has a mesh, the trainer job does not: the view needs both, so the index says none
    finished(api, "trainer", lambda d: None)
    jid = finished(api, "follow", lambda d: put_mesh(d / "work" / "follower" / "part2"))
    assert api.json("GET", f"api/results/{jid}/mesh.json") == (200, {"trainer": None, "you": None})
    assert api.request("GET", f"api/results/{jid}/mesh/trainer/mesh3d.json")[0] == 404
    # the follower's own file still answers: absent is 404, present is 200
    assert api.request("GET", f"api/results/{jid}/mesh/you/mesh3d.bin")[0] == 200


def test_refuses_other_jobs_names_and_people(api: Api) -> None:
    tid = finished(api, "trainer", lambda d: put_mesh(d / "work" / "trainer" / "part2"))
    jid = finished(api, "follow", lambda d: put_mesh(d / "work" / "follower" / "part2"))
    for path in (f"api/results/{tid}/mesh.json", "api/results/ffffffffffff/mesh.json", "api/results/NOTANID/mesh.json",
                 f"api/results/{jid}/mesh/coach/mesh3d.json", f"api/results/{jid}/mesh/you/pose3d.json",
                 f"api/results/{jid}/mesh/you/..%2Fjob.json", f"api/results/{tid}/mesh/trainer/mesh3d.json"):
        assert api.request("GET", path)[0] == 404, path


def test_symlinked_mesh_is_not_served(tmp_path: Path) -> None:
    d = tmp_path / "aaaaaaaaaaa1"
    (d / "work" / "follower" / "part2").mkdir(parents=True)
    (d / "job.json").write_text('{"kind": "follow", "status": "done"}', encoding="utf-8")
    (tmp_path / "secret").write_bytes(b"x")
    (d / "work" / "follower" / "part2" / "mesh3d.json").symlink_to(tmp_path / "secret")
    assert mesh_files.mesh_file(tmp_path, "aaaaaaaaaaa1", "you", "mesh3d.json") is None
    assert mesh_files.index(tmp_path, "aaaaaaaaaaa1") == {"trainer": None, "you": None}


def test_traversal_in_job_id_or_name_is_404(api: Api) -> None:
    jid = finished(api, "follow", lambda d: put_mesh(d / "work" / "follower" / "part2"))
    for path in ("api/results/..%2F..%2Fx/mesh.json", f"api/results/{jid}/mesh/you/..%2F..%2Fjob.json",
                 f"api/results/{jid}/mesh/..%2Fyou/mesh3d.json", f"api/results/{jid}/mesh/you/%2e%2e/mesh3d.bin"):
        assert api.request("GET", path)[0] == 404, path


def test_bin_has_content_length(api: Api) -> None:
    jid = finished(api, "follow", lambda d: put_mesh(d / "work" / "follower" / "part2"))
    status, headers, body = api.request("GET", f"api/results/{jid}/mesh/you/mesh3d.bin")
    assert status == 200 and headers["content-length"] == str(len(BIN)) == str(len(body))


def test_delete_take_removes_its_mesh(api: Api) -> None:
    jid = finished(api, "follow", lambda d: put_mesh(d / "work" / "follower" / "part2"))
    folder = api.app.queue.job_dir(jid) / "work" / "follower" / "part2"
    assert (folder / "mesh3d.bin").is_file()
    assert api.json("POST", f"api/jobs/{jid}/delete", {})[0] == 200
    assert not folder.exists() and api.request("GET", f"api/results/{jid}/mesh/you/mesh3d.bin")[0] == 404


def test_index_reads_the_record_and_looks_up_the_trainer_once(api: Api, monkeypatch: Any) -> None:
    finished(api, "trainer", lambda d: put_mesh(d / "work" / "trainer" / "part2"))
    jid = finished(api, "follow", lambda d: put_mesh(d / "work" / "follower" / "part2"))
    records, lookups = [], []
    real_record, real_lookup = mesh_files._record, mesh_files.models_used.trainer_job
    monkeypatch.setattr(mesh_files, "_record", lambda d: (records.append(d), real_record(d))[1])
    monkeypatch.setattr(mesh_files.models_used, "trainer_job", lambda *a: (lookups.append(a), real_lookup(*a))[1])
    status, doc = api.json("GET", f"api/results/{jid}/mesh.json")
    assert status == 200 and doc["trainer"] and doc["you"]  # unchanged answer
    assert len(records) == 1 and len(lookups) == 1
