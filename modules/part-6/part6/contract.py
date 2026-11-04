"""Catalog entry contract v1: the schemas, the contract document and the follow URL check.

Spec: docs/specs/catalog-contract.md (AC-C01, AC-C03, AC-C04, AC-C14, AC-C15). The document is what
`GET api/contract` returns and `python3 -m part6 contract` prints; the published description for
people is CONTRACT.md at the repo root.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.parse import urlsplit

from . import formats

CONTRACT_VERSION = 1
SCHEMA_DIR = Path(__file__).resolve().parent.parent / "contracts"
SCHEMA_SUFFIX = ".schema.json"

# AC-C03, in the order of the spec's table. Paths are relative to the base path (SIMON6_BASE_PATH).
API = (
    ("GET", "api/health", "200 {ok: true, entries, contract_version: 1}"),
    ("GET", "api/contract", "200 the contract document"),
    ("GET", "api/entries[?q=&category=&source=]",
     "200 {entries} sorted by name; source is a files_source value; unknown category or source is 400"),
    ("GET", "api/entries/<id>", "200 manifest, 404"),
    ("GET", "api/entries/<id>/<file>", "the file the manifest names (Range for a video), 404"),
    ("POST", "api/entries",
     "201 manifest when processing finished within 3 s; 202 {id, status, job} otherwise"),
    ("GET", "api/jobs/<id>", "200 {id, status, entry} (entry is the manifest once done, else null), 404"),
    ("POST", "api/import",
     "201 manifest; 400 {error} in plain words; 408 body too slow; 413 too large; 503 busy"),
)
HANDOFF = {"route": "#/entry/{id}", "event": "simon:follow", "message_type": "simon:follow"}


def schema_names():
    """Every schema name under contracts/, sorted: the file name without .schema.json."""
    return sorted(p.name[:-len(SCHEMA_SUFFIX)] for p in SCHEMA_DIR.glob(f"*{SCHEMA_SUFFIX}"))


def _load(name):
    return json.loads((SCHEMA_DIR / f"{name}{SCHEMA_SUFFIX}").read_text(encoding="utf-8"))


def schemas():
    """{name: parsed schema} for every file under contracts/."""
    return {name: _load(name) for name in schema_names()}


def schema(name):
    """The parsed schema called `name`; KeyError when there is none. The name never builds a path."""
    if name not in schema_names():
        raise KeyError(name)
    return _load(name)


def version_field(format_id):
    """The field that carries a format id: "schema" for /1 ids, "format" for .v1 ids, else None."""
    if format_id.endswith("/1"):
        return "schema"
    if format_id.endswith(".v1"):
        return "format"
    return None


def format_rows():
    return [{"id": fid, "kind": kind, "producer_part": formats.PRODUCER[fid],
             "version_field": version_field(fid)}
            for kind in formats.KINDS for fid in formats.FORMATS[kind]]


def document(follow_url=None):
    """The contract document of AC-C04."""
    every = schemas()
    return {
        "contract_version": CONTRACT_VERSION,
        "schemas": every,
        "formats": format_rows(),
        "files_sources": list(every["manifest"]["properties"]["files_source"]["enum"]),
        "api": [{"method": m, "path": p, "result": r} for m, p, r in API],
        "handoff": dict(HANDOFF, follow_url=follow_url),
    }


def check_follow_url(url):
    """The follow URL template unchanged when it is an http or https URL with a host, else ValueError."""
    if not isinstance(url, str):
        raise ValueError("the follow URL must be text")
    if not url.strip():
        raise ValueError("the follow URL is empty")
    if any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in url):
        raise ValueError("the follow URL must not contain spaces or control characters")
    try:
        parts = urlsplit(url)
        host = parts.hostname
        parts.port  # noqa: B018 (raises ValueError for a bad port)
    except ValueError:
        raise ValueError("the follow URL is not a valid web address") from None
    if parts.scheme.lower() not in ("http", "https"):
        raise ValueError("the follow URL must start with http:// or https://")
    if not host:
        raise ValueError("the follow URL needs a host name")
    return url


def run(schema_name=None, out=sys.stdout):
    """Print the contract document, or one schema, as JSON. Exit code 0; 2 for an unknown schema."""
    if schema_name is None:
        body = document()
    else:
        try:
            body = schema(schema_name)
        except KeyError:
            known = ", ".join(schema_names())
            print(f"contract: no schema named {schema_name!r} (known: {known})", file=sys.stderr)
            return 2
    out.write(json.dumps(body, indent=2) + "\n")
    return 0
