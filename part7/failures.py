"""`part7 failures`: the last hour's failures per route and per job, from part7.log (docs/specs/observability.md).

Stdlib only and free of other `part7` imports: `prod/failures.sh` runs this file by path with the system python, so it
still works when the app's own environment is what broke. It reads log lines, which are already scrubbed.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import sys
from typing import Any

_LINE = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})Z? (\w+) (.*)$")
_PAIR = re.compile(r'(\w+)=("(?:[^"\\]|\\.)*"|\S+)')
_ANOMALY = re.compile(r"^ANOMALY (\w+)(.*)$")


def _fields(text: str) -> dict[str, str]:
    head, sep, detail = text.partition(" detail=")
    out = {k: v[1:-1].replace('\\"', '"').replace("\\\\", "\\") if v.startswith('"') else v for k, v in _PAIR.findall(head)}
    if sep:
        out["detail"] = detail
    return out


def _bump(table: dict[str, dict[str, Any]], key: str, stamp: str, fields: dict[str, str]) -> None:
    row = table.setdefault(key, {"count": 0, "statuses": Counter()})
    row["count"] += 1
    if fields.get("status"):
        row["statuses"][fields["status"]] += 1
    row.update(last=stamp, rid=fields.get("rid", "-"), reason=fields.get("reason") or fields.get("detail") or "-")


def report(state: Path | str, hours: float = 1.0, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    since = (now - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%S")
    doc: dict[str, Any] = {"since": since + "Z", "routes": {}, "browser": {}, "jobs": [], "other": Counter(),
                           "selfheal": [], "notices": []}
    base = Path(state) / "part7.log"
    for path in (base.with_name("part7.log.1"), base):  # oldest first, so the last row of a table is the newest
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for raw in text.splitlines():
            _take(doc, raw, since)
    return doc


def _take(doc: dict[str, Any], raw: str, since: str) -> None:
    found = _LINE.match(raw)
    if not found or found.group(1) < since:
        return
    stamp, msg = found.group(1) + "Z", found.group(3)
    if msg.startswith("SELFHEAL "):
        doc["selfheal"].append(f"{stamp} {msg[9:]}")
    elif msg.startswith("NOTICE "):
        doc["notices"].append(f"{stamp} {msg[7:]}")
    elif (kind := _ANOMALY.match(msg)) is not None:
        _anomaly(doc, stamp, kind.group(1), _fields(kind.group(2).strip()))


def _anomaly(doc: dict[str, Any], stamp: str, kind: str, fields: dict[str, str]) -> None:
    if kind == "http_5xx":
        _bump(doc["routes"], fields.get("route") or f"{fields.get('method', '?')} {fields.get('path', '?')}", stamp, fields)
    elif kind == "client_error":
        _bump(doc["browser"], f"{fields.get('source', 'script')} {fields.get('route') or fields.get('path') or fields.get('page', '-')}", stamp, fields)
    elif kind == "job_failed":
        doc["jobs"].append({"at": stamp, "job": fields.get("job", "-"), "kind": fields.get("kind", "-"), "stage": fields.get("stage", "-"),
                            "cause": fields.get("cause", "-"), "reason": fields.get("detail", "-")})
    else:
        doc["other"][kind] += 1


def _table(title: str, table: dict[str, dict[str, Any]]) -> list[str]:
    lines = [f"{title}:"]
    for key, row in sorted(table.items(), key=lambda kv: -kv[1]["count"]):
        codes = ",".join(sorted(row["statuses"])) or "-"
        lines.append(f"  {row['count']:>5}  {key}  status {codes}  last {row['last']}  rid {row['rid']}  {row['reason'][:120]}")
    return lines if table else [f"{title}: none"]


def render(doc: dict[str, Any]) -> str:
    lines = [f"failures since {doc['since']}"]
    lines += _table("routes (5xx)", doc["routes"]) + _table("browser reports", doc["browser"])
    lines.append("jobs failed:" if doc["jobs"] else "jobs failed: none")
    lines += [f"  {j['at']}  {j['job']}  {j['kind']}  stage {j['stage']}  cause {j['cause']}  {j['reason'][:120]}" for j in doc["jobs"]]
    lines.append("other anomalies: " + (", ".join(f"{k} {n}" for k, n in doc["other"].most_common()) or "none"))
    for title, key in (("self-heal actions", "selfheal"), ("notices", "notices")):
        lines.append(f"{title}:" if doc[key] else f"{title}: none")
        lines += [f"  {row[:200]}" for row in doc[key]]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="The last hour's failures per route and per job.")
    parser.add_argument("--state", required=True)
    parser.add_argument("--hours", type=float, default=1.0)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    doc = report(args.state, args.hours)
    print(json.dumps(doc, indent=1) if args.json else render(doc))
    return 0


if __name__ == "__main__":
    sys.exit(main())
