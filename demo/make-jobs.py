#!/usr/bin/env python3
"""demo/make-jobs.py: make the fresh trainer entry and follow job for the video through the real API of a LOCAL server.

Usage: demo/make-jobs.py [--base http://127.0.0.1:17391/] [--out DIR]   (server from `DEMO_LIVE=1 demo/local-state.sh start`)
1. POST api/uploads + api/trainer with a stock trainer clip (default Pexels 8026937, licence in videos/pexels-8026937/SOURCE.md).
2. When that job is done, POST api/uploads + api/people (SAM 3.1 finds the person) + api/follow with a stock follower clip that has faults (default Pexels 4224405).
Writes <out>/<tag>.json (default fresh-jobs.json): the two job ids, the entry id, and the job.json of each, so the video cites real ids.
The Part 7 queue and gpu_lock admit the work; this script only waits. It never calls Meta itself.
"""
import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

VIDEOS = Path.home() / ".local/state/simon-part-7/videos"
TRAINER, FOLLOWER = "pexels-8026937", "pexels-4224405"  # a knee-raise trainer and follower; Part 1 finds no person in pexels-6326808


def call(base, method, route, body=None, ctype="application/json"):
    data = body if isinstance(body, bytes) else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(base + route, data=data, method=method, headers={"Content-Type": ctype} if data else {})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def upload(base, clip):
    path = Path(clip) if clip.endswith(".mp4") else VIDEOS / clip / "clip.mp4"  # a frozen clip id, or a file (a labelled derived copy)
    status, doc = call(base, "POST", "api/uploads", path.read_bytes(), "video/mp4")
    if status != 201:
        sys.exit(f"upload {clip}: {status} {doc}")
    return doc["upload_id"]


def wait(base, job, label, limit_s=2400):
    t0 = time.time()
    while time.time() - t0 < limit_s:
        status, doc = call(base, "GET", f"api/jobs/{job}")
        if doc.get("status") in ("done", "failed", "error"):
            print(f"{label} {job}: {doc.get('status')} in {time.time() - t0:.0f} s", flush=True)
            return doc
        time.sleep(10)
    sys.exit(f"{label} {job}: not finished in {limit_s} s")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:17391/")
    ap.add_argument("--out", default="/tmp/simon-demo-r17")
    ap.add_argument("--trainer", default=TRAINER)
    ap.add_argument("--follower", default=FOLLOWER)
    ap.add_argument("--name", default="Standing knee raise")
    ap.add_argument("--tag", default="fresh-jobs")
    ap.add_argument("--trainer-job", default=None)
    a = ap.parse_args()
    base = a.base.rstrip("/") + "/"
    out = Path(a.out)
    if a.trainer_job:  # a trainer job already queued on this server: wait for it instead of making another
        tj = {"job": a.trainer_job}
    else:
        status, tj = call(base, "POST", "api/trainer", {"upload_id": upload(base, a.trainer), "name": a.name, "category": "exercise"})
        if status != 202:
            sys.exit(f"trainer: {status} {tj}")
    print("trainer job", tj["job"], flush=True)
    trainer = wait(base, tj["job"], "trainer")
    entry = trainer.get("entry_id")
    if trainer.get("status") != "done" or not entry:
        sys.exit(f"trainer job did not make an entry: {trainer}")
    up = upload(base, a.follower)
    # The real take flow finds the people first (SAM 3.1 tracking through the Meta Model API), then follows one of them.
    status, pj = call(base, "POST", "api/people", {"upload_id": up})
    if status != 202:
        sys.exit(f"people: {status} {pj}")
    print("people job", pj["job"], flush=True)
    people = wait(base, pj["job"], "people")
    found = ((people.get("result") or {}).get("people") or [])
    if people.get("status") != "done" or not found:
        sys.exit(f"people job found nobody: {people}")
    body = {"upload_id": up, "entry_id": entry, "mode": "fitness", "people_job": pj["job"], "person_id": found[0]["id"]}
    status, fj = call(base, "POST", "api/follow", body)
    if status != 202:
        sys.exit(f"follow: {status} {fj}")
    print("follow job", fj["job"], flush=True)
    follow = wait(base, fj["job"], "follow")
    (out / f"{a.tag}.json").write_text(json.dumps({"trainer_job": tj["job"], "entry": entry, "people_job": pj["job"], "follow_job": fj["job"], "trainer": trainer, "follow": follow}, indent=1))
    print(json.dumps({"entry": entry, "trainer_job": tj["job"], "follow_job": fj["job"], "score": (follow.get("result") or {}).get("score")}))


if __name__ == "__main__":
    main()
