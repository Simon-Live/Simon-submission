"""The follower-clip route (coaching-moments.md "Follower video"): Range, 404s, traversal, group variant."""

from __future__ import annotations

from pathlib import Path
import shutil
from typing import Any

from part7 import jobs, result_media
from support import Api


def finished(api: Api, kind: str, clip: Path, pids: tuple[str, ...] = (), write_clip: bool = True,
             result: dict[str, Any] | None = None) -> str:
    def fn(ctx: jobs.JobContext) -> dict[str, Any]:
        if write_clip:
            shutil.copy(clip, ctx.work / "video.mp4")
        for pid in pids:
            (ctx.work / "person" / pid).mkdir(parents=True)
        return {"result": result or {}}

    owner = {"_people_owner": ""} if kind in ("people", "group") else {}  # made signed out (prod-data.md P-N1)
    job = api.app.queue.submit(kind, fn, **owner)
    assert api.app.queue.wait(job["id"], 10)["status"] == "done"
    return job["id"]


def test_whole_clip_and_range(api: Api, tiny_mp4: Path) -> None:
    job = finished(api, "follow", tiny_mp4)
    data = tiny_mp4.read_bytes()
    status, hdr, body = api.request("GET", f"api/results/{job}/video.mp4")
    assert (status, body, hdr["accept-ranges"], hdr["content-type"]) == (200, data, "bytes", "video/mp4")
    status, hdr, body = api.request("GET", f"api/results/{job}/video.mp4", headers={"Range": "bytes=10-19"})
    assert (status, body, hdr["content-range"]) == (206, data[10:20], f"bytes 10-19/{len(data)}")
    status, hdr, body = api.request("GET", f"api/results/{job}/video.mp4", headers={"Range": "bytes=100-"})
    assert (status, body) == (206, data[100:])
    status, hdr, body = api.request("GET", f"api/results/{job}/video.mp4", headers={"Range": "bytes=-5"})
    assert (status, body) == (206, data[-5:])
    status, hdr, body = api.request("HEAD", f"api/results/{job}/video.mp4")
    assert (status, body, int(hdr["content-length"])) == (200, b"", len(data))


def test_range_past_the_end_is_416(api: Api, tiny_mp4: Path) -> None:
    job = finished(api, "follow", tiny_mp4)
    size = tiny_mp4.stat().st_size
    status, hdr, _ = api.request("GET", f"api/results/{job}/video.mp4", headers={"Range": f"bytes={size}-"})
    assert (status, hdr["content-range"]) == (416, f"bytes */{size}")


def test_malformed_range_serves_the_whole_clip(api: Api, tiny_mp4: Path) -> None:
    job = finished(api, "follow", tiny_mp4)
    status, _, body = api.request("GET", f"api/results/{job}/video.mp4", headers={"Range": "bytes=a-b"})
    assert (status, body) == (200, tiny_mp4.read_bytes())


def test_unknown_unfinished_and_clipless_jobs_are_404(api: Api, tiny_mp4: Path) -> None:
    assert api.request("GET", "api/results/aaaaaaaaaaaa/video.mp4")[0] == 404
    assert api.request("GET", "api/results/not-a-job/video.mp4")[0] == 404
    assert api.request("GET", "api/results/..%2f..%2fetc/video.mp4")[0] == 404
    no_clip = finished(api, "follow", tiny_mp4, write_clip=False)
    assert api.request("GET", f"api/results/{no_clip}/video.mp4")[0] == 404
    trainer = finished(api, "trainer", tiny_mp4)  # a trainer job has no follower clip
    assert api.request("GET", f"api/results/{trainer}/video.mp4")[0] == 404


def test_failed_job_does_not_serve_its_clip(api: Api, tiny_mp4: Path) -> None:
    def fn(ctx: jobs.JobContext) -> None:
        shutil.copy(tiny_mp4, ctx.work / "video.mp4")
        raise jobs.JobFailed("pose", "boom")

    job = api.app.queue.submit("follow", fn)
    assert api.app.queue.wait(job["id"], 10)["status"] == "failed"
    assert api.request("GET", f"api/results/{job['id']}/video.mp4")[0] == 404


def test_group_person_variant(api: Api, tiny_mp4: Path) -> None:
    job = finished(api, "group", tiny_mp4, pids=("2",))
    status, _, body = api.request("GET", f"api/results/{job}/2/video.mp4", headers={"Range": "bytes=0-3"})
    assert (status, body) == (206, tiny_mp4.read_bytes()[:4])
    assert api.request("GET", f"api/results/{job}/7/video.mp4")[0] == 404  # not a person of this group
    assert api.request("GET", f"api/results/{job}/..%2f/video.mp4")[0] == 404
    assert api.request("GET", f"api/results/{job}/video.mp4")[0] == 404  # a group job has no solo clip
    follow = finished(api, "follow", tiny_mp4)
    assert api.request("GET", f"api/results/{follow}/2/video.mp4")[0] == 404


def test_head_and_get_for_a_pid_outside_result_people_are_404(api: Api, tiny_mp4: Path) -> None:
    job = finished(api, "group", tiny_mp4, pids=("2",), result={"people": [{"pid": "2", "name": "A"}]})
    status, hdr, body = api.request("HEAD", f"api/results/{job}/2/video.mp4")
    assert (status, body, int(hdr["content-length"])) == (200, b"", len(tiny_mp4.read_bytes()))
    for method in ("GET", "HEAD"):
        assert api.request(method, f"api/results/{job}/3/video.mp4")[0] == 404  # not in result.people, no person dir


def test_other_result_files_still_route(api: Api, tiny_mp4: Path) -> None:
    job = finished(api, "follow", tiny_mp4)
    assert api.request("GET", f"api/results/{job}/analysis.json")[0] == 404  # missing file, existing route
    assert result_media.byte_range(None, 10) is None
    assert result_media.byte_range("bytes=2-4", 10) == (2, 4)
    assert result_media.byte_range("bytes=2-400", 10) == (2, 9)
    assert result_media.byte_range("bytes=-0", 10) == result_media.UNSATISFIABLE
