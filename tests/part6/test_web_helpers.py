"""Small browser helpers checked from Python, on the same names and rules the server uses
(docs/specs/catalog-contract.md AC-C08, review R9 and R15).

- `fileLabel` in web/import.js and `part6.importer.file_label` give the same text for the same name, so a
  message about a long or odd file name reads alike in the browser and in the server's 400.
- `producerOf` in web/api.js answers only for format ids the table holds, never for an inherited key
  such as "constructor" (the table is a plain object).
- `failureText` in web/import.js shows the screen's own sentence for a 408, 413 or 503 from api/import,
  for a 500 and any other 5xx too, and the server's message for a 400 (AC-C08).
- `parseStrictJson` in web/formats.js is the one browser read of a JSON file's bytes. It refuses the
  bytes `part6.validate.parse_json` refuses (invalid UTF-8, `NaN`, a number that does not fit a double)
  and accepts the rest, with the same data (docs/specs/formats.md "Error Cases").
- A dropped JSON file with such bytes is refused by the Import screen's `describe` as "is not valid
  JSON" and carries nothing to send; a file of an entry that the player loads with `loadEntryJson` in
  web/api.js is refused the same way (AC-F11). Every file is handed to node as bytes (hex), and the
  same bytes go to `parse_json`.
- `holdsNonFinite`, the finite-number walk `parseStrictJson` uses, lives in web/formats.js.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from part6 import formats
from part6.importer import LABEL_MAX, file_label
from part6.validate import NotJson, parse_json

ROOT = Path(__file__).resolve().parents[2]
NODE = shutil.which("node")
LABEL_SCRIPT = """
const { fileLabel } = await import(process.argv[1]);
process.stdout.write(JSON.stringify(JSON.parse(process.argv[2]).map(fileLabel)));
"""
PRODUCER_SCRIPT = """
const { producerOf } = await import(process.argv[1]);
process.stdout.write(JSON.stringify(JSON.parse(process.argv[2]).map(producerOf)));
"""
PART_SCRIPT = """
const { provenancePart } = await import(process.argv[1]);
process.stdout.write(JSON.stringify(JSON.parse(process.argv[2]).map(([r, f]) => provenancePart(r, f))));
"""
FAILURE_SCRIPT = """
const { failureText } = await import(process.argv[1]);
const { SERVER_UNREACHABLE } = await import(new URL('api.js', process.argv[1]));
const texts = JSON.parse(process.argv[2]).map(failureText);
process.stdout.write(JSON.stringify({ texts, unreachable: SERVER_UNREACHABLE }));
"""
# Files and bodies go in as hex, so node sees the exact bytes the Python side reads.
DESCRIBE_SCRIPT = """
const { describe } = await import(process.argv[1]);
const items = [];
for (const [name, hex] of JSON.parse(process.argv[2])) {
  const { error, kind, text } = await describe(new File([Buffer.from(hex, 'hex')], name));
  items.push({ error, kind, text });
}
process.stdout.write(JSON.stringify(items));
"""
LOAD_SCRIPT = """
const { loadEntryJson } = await import(process.argv[1]);
const entry = { id: 'e', animation: 'animation.json' };
const out = [];
for (const [status, hex] of JSON.parse(process.argv[2])) {
  globalThis.fetch = async () => new Response(Buffer.from(hex, 'hex'), { status });
  const got = await loadEntryJson(entry, 'animation');
  out.push(got.status === 'ok' ? { status: got.status, data: got.data } : { status: got.status });
}
process.stdout.write(JSON.stringify(out));
"""
STRICT_SCRIPT = """
const { parseStrictJson } = await import(process.argv[1]);
const out = [];
for (const hex of JSON.parse(process.argv[2])) {
  const bytes = new Uint8Array(Buffer.from(hex, 'hex'));
  const got = parseStrictJson(bytes);
  const fromBuffer = parseStrictJson(bytes.buffer);
  out.push({ ...got, sameFromArrayBuffer: JSON.stringify(got) === JSON.stringify(fromBuffer) });
}
const notBytes = [null, undefined, 'text', 7, {}].map((value) => parseStrictJson(value).ok);
process.stdout.write(JSON.stringify({ out, notBytes }));
"""
WALK_SCRIPT = """
const { holdsNonFinite } = await import(process.argv[1]);
const deep = 300000;
const nested = (inner) => JSON.parse('['.repeat(deep) + inner + ']'.repeat(deep));
const triples = Array.from({ length: 250000 }, (_, i) => [i * 0.37, i / 7, -i]);
const started = performance.now();
const big = holdsNonFinite({ frames: triples });
const bigMs = performance.now() - started;
process.stdout.write(JSON.stringify({
  deepBad: holdsNonFinite(nested('1e400')), deepOk: holdsNonFinite(nested('1')), big, bigMs,
  bareBad: holdsNonFinite(JSON.parse('-1e400')), bareOk: holdsNonFinite(JSON.parse('7')), nothing: holdsNonFinite(null),
}));
"""
NAMES = [
    "animation.json",
    "movement/sub/skeleton.json",
    "C:\\Users\\me\\keyframes.json",
    "x" * (LABEL_MAX + 10) + ".json",
    "\u00e9" * (LABEL_MAX + 1),
    "\U0001f600" * (LABEL_MAX + 5),
    "  spaced name.json  ",
    "tab\tinside\u0000nul\u001fus.json",
    "\u0085next-line.json",
    "\u00a0no-break\u00a0",
    "\u2028separators\u2029",
    "\ufeffbom.json",
    "bom.json\ufeff",
    "\u0007\u0008",
    "",
    "/",
    "dir/",
    "a" * LABEL_MAX,
    "a" * (LABEL_MAX + 1),
]
INHERITED_KEYS = ["constructor", "toString", "__proto__", "hasOwnProperty", "valueOf", "", None, 4]


def run_module(script, module, payload):
    url = (ROOT / "web" / module).as_uri()
    done = subprocess.run([NODE, "--input-type=module", "-e", script, url, json.dumps(payload)],
                          capture_output=True, text=True, timeout=60, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_the_screen_and_the_server_label_a_file_alike():
    assert run_module(LABEL_SCRIPT, "import.js", NAMES) == [file_label(name) for name in NAMES]


def test_a_long_name_is_cut_to_the_limit_and_an_empty_one_is_called_file():
    assert len(file_label("x" * (LABEL_MAX + 50))) == LABEL_MAX
    assert file_label("\u0007\u0008") == "file"


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_the_producer_lookup_knows_the_formats_and_nothing_inherited():
    known = [fmt for fmt in formats.PRODUCER]
    got = run_module(PRODUCER_SCRIPT, "api.js", known + INHERITED_KEYS)
    assert got[:len(known)] == [formats.PRODUCER[fmt] for fmt in known]
    assert got[len(known):] == [""] * len(INHERITED_KEYS)


def test_a_null_provenance_part_names_no_part_and_only_a_missing_record_uses_the_usual_one():
    """AC-C08: the files panel never turns a null part (producer not known) into a guess."""
    cases = [[{"part": 3, "format": "simon.skeleton.v1"}, "simon.skeleton.v1"],
             [{"part": None, "format": "simon.skeleton.v1"}, "simon.skeleton.v1"],
             [{"format": "simon.skeleton.v1"}, "simon.skeleton.v1"],
             [None, "simon.skeleton.v1"],
             [None, "unknown.format"]]
    assert run_module(PART_SCRIPT, "api.js", cases) == [3, "", 4, 4, ""]


SERVER_REASONS = {400: "animation.json: is not valid JSON", 408: "body too slow", 413: "body too large",
                  503: "busy, try again"}
SCREEN_SENTENCES = {408: "The upload took too long. Check the connection and try again.",
                    413: "The files are too large for the server. Remove one and try again.",
                    503: "Another import is running. Try again in a moment."}
RETRY = "Could not import. Try again."
SERVER_FAULT = "The server could not import these files. Try again in a moment."
# What part6/server.py really sends for an unhandled error (tests/part6/test_server.py pins it).
REAL_500 = {"error": "internal error"}


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_import_failures_use_the_screens_sentence_except_a_400_which_shows_the_servers_reason():
    results = [{"status": "error", "code": code, "error": reason} for code, reason in SERVER_REASONS.items()]
    results += [{"status": "error", "code": 400, "error": None},
                {"status": "error", "code": 0, "error": None}, {"status": "error", "code": 408, "error": None}]
    got = run_module(FAILURE_SCRIPT, "import.js", results)
    assert got["texts"] == [SERVER_REASONS[400], SCREEN_SENTENCES[408], SCREEN_SENTENCES[413], SCREEN_SENTENCES[503],
                            RETRY, got["unreachable"], SCREEN_SENTENCES[408]]
    for code in (408, 413, 503):
        assert SERVER_REASONS[code] not in SCREEN_SENTENCES[code]


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_a_500_and_any_other_5xx_show_the_screens_own_sentence_never_internal_error():
    # postJson (web/api.js) keeps the body's "error" text, or null when the body is not JSON text.
    results = [{"status": "error", "code": 500, "error": REAL_500["error"]},
               {"status": "error", "code": 500, "error": None},
               {"status": "error", "code": 502, "error": None},
               {"status": "error", "code": 504, "error": "gateway timeout"},
               {"status": "error", "code": 599, "error": "x"}]
    texts = run_module(FAILURE_SCRIPT, "import.js", results)["texts"]
    assert texts == [SERVER_FAULT] * len(results)
    assert all("internal error" not in text and "gateway" not in text for text in texts)


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_a_4xx_that_is_not_one_of_the_screens_own_cases_still_shows_what_the_server_said():
    results = [{"status": "error", "code": 499, "error": "name"}, {"status": "error", "code": 404, "error": None}]
    assert run_module(FAILURE_SCRIPT, "import.js", results)["texts"] == ["name", RETRY]


NUMBER_FILES = [
    ("n1.json", '{"a": 1e400}'),
    ("n2.json", '{"a": [1, {"b": -1e400}]}'),
    ("n3.json", '{"a": 1' + "0" * 400 + "}"),
    ("n4.json", '{"a": -1' + "0" * 400 + "}"),
    ("n5.json", '{"a": 1.5e-400}'),
    ("n6.json", '{"a": 1e308, "b": 1' + "0" * 308 + "}"),
    ("n7.json", '{"a": "1e400"}'),
    ("n8.json", '{"a": NaN}'),
    ("n9.json", '{"a": -Infinity}'),
    ("n10.json", "1e400"),
    ("n11.json", '{"a": 1'),
]


# Files that are not valid UTF-8, as bytes. The last one is the repo's own parse-level golden.
GOLDEN_FORMATS = ROOT / "fixtures" / "conformance" / "formats"
GOLDEN_BAD_UTF8 = GOLDEN_FORMATS / "invalid-json-bad-utf8.json"
BAD_BYTE_FILES = [
    ("b1.json", b'{"a": "caf\xff"}'),                  # 0xFF inside a string
    ("b2.json", b'\xff{"a": 1}'),                      # 0xFF before the object
    ("b3.json", b'{"a": "\xc0\xaf"}'),                 # an overlong sequence
    ("b4.json", b'{"a": "\xe2\x82"}'),                 # a sequence cut short
    ("b5.json", b'{"a": "\xed\xa0\x80"}'),             # an encoded surrogate
    ("b6.json", b'{"a": "\xf4\x90\x80\x80"}'),         # beyond U+10FFFF
    ("b7.json", GOLDEN_BAD_UTF8.read_bytes()),         # an otherwise valid animation
]
# Valid UTF-8 the strict parse accepts: plain, with a byte order mark, with an astral character, with
# an escaped surrogate pair.
GOOD_BYTE_FILES = [
    ("g1.json", b'{"a": 1}'),
    ("g2.json", b'\xef\xbb\xbf{"a": [1, 2.5, "caf\xc3\xa9"]}'),
    ("g3.json", '{"a": "\U0001f600", "b": null}'.encode("utf-8")),
    ("g4.json", b'{"a": "\\ud83d\\ude00"}'),
]
# Refused by both sides although the bytes are valid UTF-8 (or empty).
ODD_BYTE_FILES = [
    ("o1.json", b'\xef\xbb\xbf\xef\xbb\xbf{"a": 1}'),  # two byte order marks
    ("o2.json", b""),
    ("o3.json", b'{"a": 1} x'),
]
ALL_BYTE_FILES = ([(name, text.encode("utf-8")) for name, text in NUMBER_FILES]
                  + BAD_BYTE_FILES + GOOD_BYTE_FILES + ODD_BYTE_FILES)


def server_refuses(raw):
    """True when part6.validate.parse_json refuses these bytes (or this text)."""
    try:
        parse_json(raw)
    except NotJson:
        return True
    return False


def hexed(files):
    return [[name, raw.hex()] for name, raw in files]


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_parse_strict_json_reads_a_valid_file_and_returns_what_json_parse_gives():
    files = [raw for _, raw in GOOD_BYTE_FILES]
    got = run_module(STRICT_SCRIPT, "formats.js", [raw.hex() for raw in files])["out"]
    for raw, result in zip(files, got):
        assert result["ok"] is True and result["sameFromArrayBuffer"] is True
        assert result["data"] == parse_json(raw)
        assert result["data"] == json.loads(raw.decode("utf-8-sig"))
    assert got[1]["data"] == {"a": [1, 2.5, "café"]}


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_parse_strict_json_drops_one_leading_byte_order_mark_and_returns_the_text_it_checked():
    got = run_module(STRICT_SCRIPT, "formats.js", [GOOD_BYTE_FILES[1][1].hex()])["out"][0]
    assert got["ok"] is True and got["text"] == '{"a": [1, 2.5, "café"]}'
    assert parse_json(got["text"]) == got["data"]


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_parse_strict_json_refuses_a_byte_that_is_not_valid_utf8():
    got = run_module(STRICT_SCRIPT, "formats.js", [raw.hex() for _, raw in BAD_BYTE_FILES])["out"]
    assert [result["ok"] for result in got] == [False] * len(BAD_BYTE_FILES)
    assert all(server_refuses(raw) for _, raw in BAD_BYTE_FILES)
    assert all("data" not in result and "text" not in result for result in got)


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_parse_strict_json_refuses_a_number_beyond_a_double_and_nan_text():
    named = dict(NUMBER_FILES)
    refused = [named["n1.json"], named["n10.json"], named["n3.json"], named["n8.json"], named["n9.json"]]
    assert "1e400" in refused[1] and "NaN" in refused[3]
    got = run_module(STRICT_SCRIPT, "formats.js", [text.encode("utf-8").hex() for text in refused])["out"]
    assert [result["ok"] for result in got] == [False] * len(refused)


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_parse_strict_json_answers_as_parse_json_does_for_the_same_bytes_and_never_throws():
    got = run_module(STRICT_SCRIPT, "formats.js", [raw.hex() for _, raw in ALL_BYTE_FILES])
    for (name, raw), result in zip(ALL_BYTE_FILES, got["out"]):
        assert result["ok"] is (not server_refuses(raw)), name
        if result["ok"]:
            assert result["data"] == parse_json(raw), name
    assert got["notBytes"] == [False] * 5


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_a_dropped_file_is_refused_as_the_server_refuses_it():
    items = run_module(DESCRIBE_SCRIPT, "import.js", hexed(ALL_BYTE_FILES))
    for (name, raw), item in zip(ALL_BYTE_FILES, items):
        assert (item["error"] == f"{name}: is not valid JSON") == server_refuses(raw), (name, item["error"])
    errors = {name: item["error"] for (name, _), item in zip(ALL_BYTE_FILES, items)}
    assert errors["n1.json"] == "n1.json: is not valid JSON"
    assert errors["n5.json"] != "n5.json: is not valid JSON" and errors["n7.json"] != "n7.json: is not valid JSON"


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_a_dropped_file_with_a_bad_byte_shows_not_valid_json_under_its_label_and_is_not_sent():
    name = "movement/sub/invalid-json-bad-utf8.json"
    raw = GOLDEN_BAD_UTF8.read_bytes()
    item = run_module(DESCRIBE_SCRIPT, "import.js", [[name, raw.hex()]])[0]
    assert item["error"] == f"{file_label(name)}: is not valid JSON"
    assert item["error"] == "invalid-json-bad-utf8.json: is not valid JSON"
    # The screen sends {name, text} for a usable JSON file (bodyOf in web/import.js) and keeps Import
    # off while any chosen file has an error (saveAllowed): this one has no text and no kind to send.
    assert item["kind"] == "" and "text" not in item
    assert server_refuses(raw)


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_the_import_screen_sends_the_text_it_checked_without_the_byte_order_mark():
    animation = (GOLDEN_FORMATS / "animation-v1-bare.json").read_bytes()  # small: it travels in argv
    bom = b"\xef\xbb\xbf"
    files = [["plain.json", animation.hex()], ["bom.json", (bom + animation).hex()]]
    plain, with_bom = run_module(DESCRIBE_SCRIPT, "import.js", files)
    assert plain["error"] == "" and with_bom["error"] == ""
    assert plain["kind"] == with_bom["kind"] == "animation"
    assert plain["text"] == with_bom["text"] == animation.decode("utf-8")
    assert parse_json(with_bom["text"]) == parse_json(bom + animation)


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_the_player_refuses_the_entry_files_the_server_refuses():
    served = [(200, raw.hex()) for _, raw in ALL_BYTE_FILES]
    served += [(200, b'{"frames": []}'.hex()), (404, ""), (500, b"oops".hex())]
    got = run_module(LOAD_SCRIPT, "api.js", served)
    refused = ["invalid" if server_refuses(raw) else "ok" for _, raw in ALL_BYTE_FILES]
    assert [item["status"] for item in got] == refused + ["ok", "missing", "error"]
    state = {name: status for (name, _), status in zip(ALL_BYTE_FILES, refused)}
    assert state["n1.json"] == "invalid" and state["n5.json"] == "ok" and state["n6.json"] == "ok"
    assert state["b1.json"] == "invalid" and state["b7.json"] == "invalid" and state["g2.json"] == "ok"
    assert got[len(ALL_BYTE_FILES)]["data"] == {"frames": []}


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_the_finite_walk_is_iterative_and_fast_on_a_large_file():
    got = run_module(WALK_SCRIPT, "formats.js", None)
    assert got["deepBad"] is True and got["deepOk"] is False
    assert got["big"] is False and got["bigMs"] < 5000
    assert got["bareBad"] is True and got["bareOk"] is False and got["nothing"] is False
