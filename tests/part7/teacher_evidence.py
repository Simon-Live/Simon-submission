"""Evidence run: the real server answers `api/teacher/<entry>` over copies of real finished follow jobs.

    uv run python tests/part7/teacher_evidence.py <state-dir> <entry> <out.json>

`<state-dir>` holds `jobs/<id>/job.json` and `jobs/<id>/work/follower/analysis.json` copied (read only) from a real
state folder; Part 6 is the stub of `support.py` with `<entry>` and one empty entry. Writes the answers to `<out.json>`.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import threading

sys.path.insert(0, str(Path(__file__).resolve().parent))

import support  # noqa: E402
from part7 import server  # noqa: E402


def main(state: Path, entry: str, out: Path) -> int:
    child = support.FakeChild(Path(tempfile.mkdtemp(prefix="teacher-catalog-")))
    child.entries = {entry: {"id": entry}, "quiet-move": {"id": "quiet-move"}}
    web = Path(tempfile.mkdtemp(prefix="teacher-web-"))
    app = server.build_app(state, "/", child=child, lock=support.make_lock(), web_dir=web, phrasing="template")
    http = server.make_server(app)
    threading.Thread(target=http.serve_forever, daemon=True).start()
    api = support.Api(app, http)
    answers = {}
    for name, path in (("with_takes", f"api/teacher/{entry}"), ("no_takes", "api/teacher/quiet-move"), ("unknown", "api/teacher/no-such-move"),
                       ("traversal", "api/teacher/..%2f..%2fetc")):
        status, doc = api.json("GET", path)
        answers[name] = {"path": path, "status": status, "body": doc}
    out.write_text(json.dumps(answers, indent=2), encoding="utf-8")
    http.shutdown()
    app.queue.close()
    child.close()
    return 0 if answers["with_takes"]["status"] == 200 and len(answers["with_takes"]["body"]["takes"]) >= 2 else 1


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])))
