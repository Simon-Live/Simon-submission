# Simon Part 6 catalog entry contract, version 1

A catalog entry is one folder: a recorded movement, the three shared files made from it
(`keyframes.json`, `skeleton.json`, `animation.json`), a thumbnail and a manifest. This file is
for whoever reads entries, adds entries or replaces the processor: Part 7 first. The machine
readable form is `contracts/*.schema.json`, and a running server returns it all in one request.

## Integrate in five steps

1. Ask the server what it speaks. `GET <base>/api/contract` returns the contract document. Check
   that `contract_version` is `1`. `<base>` is the server address plus `SIMON6_BASE_PATH` when that
   is set. Offline, `python3 -m part6 contract` prints the same document.
2. List and open. `GET <base>/api/entries` lists manifests, `GET <base>/api/entries/<id>` returns
   one, and each file the manifest names is at `GET <base>/api/entries/<id>/<file>`. From disk,
   read `<catalog>/<id>/manifest.json` and the files beside it.
3. Read each file by its format id. Every file is one of the six formats in the table below. The
   files in `fixtures/conformance/formats/` and their `cases.json` give the exact result each
   reader must produce, so you can check your own reader against them.
4. Put files in or plug the processor in. Catalog files you already have with
   `python3 -m part6 import` or `POST <base>/api/import`. Replace the mock recording flow with
   your chain by starting the server with `--processor <module>:<function>`.
5. Take over "follow this movement". Listen for the `simon:follow` event, or start the server with
   `--follow-url`. Then run `python3 -m part6 doctor <entry>` on any entry you doubt, and
   `make check-6-contract` to run the whole kit.

## The manifest

`<catalog>/<id>/manifest.json`, described by `contracts/manifest.schema.json`.

| Field | Rule |
|---|---|
| `id` | `^[a-z0-9][a-z0-9-]{0,62}$`, equal to the folder name |
| `name` | 1 to 80 characters, no space at either end |
| `video_uri` | `null`, or a plain file name in the folder |
| `keyframes`, `skeleton`, `animation` | a plain file name or `null`; at least one of `skeleton` and `animation` is a name |
| `created_at` | `YYYY-MM-DDTHH:MM:SSZ` |
| `schema_version` | `1` |
| `category` | `exercise` or `dance` |
| `description` | a string, may be empty |
| `thumbnail` | a plain file name |
| `duration_ms` | an integer above 0 |
| `files_source` | `fixture` (shipped samples), `mock` (the mock recording flow), `import` (files put in by import) or `processor` (written by a plugged-in processor) |
| `visitor` | optional boolean, true on entries made through the HTTP API (Record or Import) |
| `provenance` | optional, see below |

A plain file name has letters, digits, dot, underscore or hyphen, does not start with a dot and
has no slash. Extra fields are allowed and ignored. Manifests from before provenance existed stay
valid. The value `pipeline` that an earlier draft listed for `files_source` is now `processor`; no
entry ever used it.

`provenance` is an object keyed by `keyframes`, `skeleton`, `animation` and `video`. Each value:

| Key | Rule |
|---|---|
| `part` | 1 to 7, the part that made the file, or `null` when that is not known |
| `format` | the format id the file was read as; `null` for a video |
| `detected_by` | `version` or `shape`; `file` for a video |
| `sha256` | 64 lowercase hex characters |
| `bytes` | the file size |
| `source`, `original_name` | optional strings: where the file came from, the name it was dropped with |

A key under `provenance` other than these four, and a field inside a record that is not listed
here, is ignored. It never hides the entry, so an entry written by a newer version is still listed
and played by an older reader. The keys a reader knows keep their checks.

`python3 -m part6 doctor` compares `sha256` and `bytes` with the stored file.

## The folder

```
<catalog>/<id>/manifest.json
<catalog>/<id>/keyframes.json    when the manifest names it
<catalog>/<id>/skeleton.json     when the manifest names it
<catalog>/<id>/animation.json    when the manifest names it
<catalog>/<id>/thumbnail.svg
<catalog>/<id>/video.webm        or video.mp4, when there is a video
```

Part 6 writes these fixed names only. A dropped file keeps its own name only as
`provenance.<kind>.original_name`.

## The formats

| Format id | Kind | Usual producer | Version field | Shape that identifies it |
|---|---|---|---|---|
| `simon.animation/1` | animation | Part 6 (provisional, mock and fixtures) | `schema` | `fps` and `frames[0].people` |
| `simon.animation.v1` | animation | Part 4 | `format` | `fps` and `frames[0].joints` |
| `simon.skeleton/1` | skeleton | Part 3 | `schema` | `frames[0].people`, no `fps` |
| `simon.skeleton.v1` | skeleton | Part 4 (input), Part 3 `--view part4` | `format` | `keyframes[0].joints` |
| `simon.keyframes/part1` | keyframes | Part 1, and Part 6 fixtures and mock | none | `people` is a list |
| `simon.keyframes.v1` | keyframes | Part 4 | `format` | `keyframes` is a list without `joints` |

`simon.keyframes/part1` is Part 6's label for Part 1's published shape, which has no version
field. The schemas are `contracts/animation.1.schema.json`, `animation.v1`, `skeleton.1`,
`skeleton.v1`, `keyframes.part1` and `keyframes.v1`.

How Part 6 detects the format of a file of a known kind:

1. `format` is a string and a known id: that id. Otherwise `schema` is a string and a known id:
   that id. Part 4's skeleton carries both `format: simon.skeleton.v1` and `schema:
   simon.skeleton/1`, and `format` wins. A known id of another kind is an error.
2. A `format` or `schema` string that is no known id is an error that names the field, the value
   and the ids Part 6 reads. Part 6 never guesses a reader for an unknown version.
3. Otherwise the shape column decides, and the entry records `detected_by: "shape"`.
4. Nothing matches: an error. Every error is one plain sentence that names the file and the
   field, for example `animation.json: frames: must be a non-empty list`.

For an imported file, the kind comes from a version id first, then from a file name containing
`keyframe`, `skeleton` or `animation`, then from the shape.

What every reader accepts:

- 17 joints, in this order: nose, left_eye, right_eye, left_ear, right_ear, left_shoulder,
  right_shoulder, left_elbow, right_elbow, left_wrist, right_wrist, left_hip, right_hip,
  left_knee, right_knee, left_ankle, right_ankle. A joint is `{x, y, z, ...}` or `[x, y, z, ...]`
  with finite numbers. Extra joints are ignored.
- Where a frame holds `people`, the person with `id` 0, else the first.
- Animation frame times must increase. The player draws
  `frames[clamp(floor(position_s * fps + 0.5), 0, n - 1)]`.
- A skeleton with no animation plays as its own animation at 30 fps. Each pose is held until the
  next one; nothing is blended, and the detail page says it is playing the skeleton.
- Part 1 key frames may sit on the video clock. A mark at frame 120 of a 60 fps video, `t_ms`
  2000, is frame 60 of a 30 fps animation: `floor(t * fps + 0.5)`.
- Every other field is ignored: `bone_lengths_m`, `bones`, `local_rotations` and the rest.
- JSON is read strictly: as `JSON.parse` reads it, after a UTF-8 decode that refuses a bad byte
  (a browser's `response.json()` and `file.text()` do not refuse one). `NaN`, `Infinity` and
  `-Infinity` are not JSON, even in a field Part 6 ignores, so a file that holds one is refused with
  `<file>: is not valid JSON`.
  A number that does not fit a double, such as `1e400` or an integer of 400 digits, is refused the
  same way. A file with a byte that is not valid UTF-8, such as `0xFF` inside a string, is refused
  the same way too: nothing replaces the byte and carries on. A UTF-8 byte order mark at the start
  of a file is ignored. The rule is the same on every side that reads a file: the server, the
  Import screen and the player. A hand-placed `animation.json` holding `1e400`, or a `0xFF` byte,
  shows `animation.json: is not valid JSON` and does not play, as `part6 doctor` reports it.
- Your reader must run that parse before it reads a golden file. `cases.json` holds two cases that
  only the strict parse catches, `invalid-json-number-overflow.json` and
  `invalid-json-bad-utf8.json`: the expected result of each is `<file>: is not valid JSON` and
  neither has an error id, because the refusal comes before any reader.

## The read API

Paths are relative to the base path (`SIMON6_BASE_PATH`). Errors are `{"error": "<reason>"}`.

| Method and path | Result |
|---|---|
| `GET api/health` | 200 `{ok: true, entries, contract_version: 1}` |
| `GET api/contract` | 200 the contract document |
| `GET api/entries[?q=&category=&source=]` | 200 `{entries}` sorted by name; `source` is a `files_source` value; an unknown category or source is 400 |
| `GET api/entries/<id>` | 200 manifest, 404 |
| `GET api/entries/<id>/<file>` | the file the manifest names (`Range` works for a video), 404 |
| `POST api/entries` `{name, category, duration_ms}` | 201 manifest when processing finished within 3 s, else 202 `{id, status, job}` |
| `GET api/jobs/<id>` | 200 `{id, status, entry}`; `entry` is the manifest once done, else null; 404 |
| `POST api/import` | 201 manifest; 400 `{error}` in plain words; 408 body too slow; 413 too large; 503 busy |

## The contract endpoint and the command line

`GET api/contract` and `python3 -m part6 contract` return the same JSON:

```
{contract_version: 1,
 schemas: {<name>: <schema>},
 formats: [{id, kind, producer_part, version_field}],
 files_sources: [...],
 api: [{method, path, result}],
 handoff: {route: "#/entry/{id}", event: "simon:follow", message_type: "simon:follow",
           follow_url: <template or null>}}
```

`schemas` holds every file under `contracts/`, keyed by its name without `.schema.json`:
`manifest`, `keyframes.part1`, `keyframes.v1`, `skeleton.1`, `skeleton.v1`, `animation.1`,
`animation.v1`, `import-request` and `job-status`. `python3 -m part6 contract --schema manifest`
prints one schema; an unknown name exits 2.

`python3 -m part6 doctor <entry folder or file>` says what would fail. For a folder it checks the
manifest against this contract, reads each named file through the readers, compares hashes with
the provenance, checks the thumbnail and the video, and says what the player would do. It prints
one line per file, then one JSON line:

```
ok manifest.json: manifest v1
ok keyframes.json: simon.keyframes.v1 (version), part 4
ok skeleton.json: simon.skeleton.v1 (version), part 4
ok animation.json: simon.animation.v1 (version), part 4
ok thumbnail.svg: thumbnail
{"entry": "part4-squat", "ok": true, "plays": "plays animation", "problems": []}
```

A failing file prints `fail <file>: <reason>`, with the reader's sentence as the reason. `plays` is
`plays animation`, `plays skeleton (no animation)`, `plays skeleton (animation unreadable)` or
`cannot play: <reason>`. A hash that differs from the provenance is a problem
(`sha256 differs from provenance`), and so is an animation that does not read, even when the
skeleton plays. For a single file, doctor prints its kind, its format and the first error. Exit 0
means valid and playable, 1 means not, 2 means the path is missing.

`python3 -m part6 import <folder or files...> --name NAME --category exercise|dance` puts files in
the catalog. Options: `--catalog DIR`, `--id ID`, `--description TEXT`, `--source TEXT` and
`--part N`. From a folder it takes `keyframes.json`, `skeleton.json`, `animation.json` and one
`video.webm` or `video.mp4`; given files, it finds each kind as described above. Every JSON file
goes through its reader. Any error stops the import with the reader's sentence on stderr and exit
1, and nothing is written. The entry gets `files_source: "import"`, provenance per file (`part`
from `--part`, else `null`: the format alone never names a producer), a thumbnail from the playable animation, and a
`duration_ms` from its duration. The command prints the manifest. The shipped fixture catalog is
refused as `--catalog` (exit 2).

`python3 -m part6 validate <catalog>` checks every entry in a catalog and exits 0 only when all
are valid.

### Import over HTTP

`POST api/import` with `Content-Type: application/json` and this body, described by
`contracts/import-request.schema.json`:

```
{"name": "Squat", "category": "exercise",
 "files": [{"name": "skeleton.json", "text": "<the JSON text>"},
           {"name": "clip.webm", "base64": "<the video bytes>"}]}
```

- `text` carries a JSON file, `base64` a video. At most 4 files and one file per kind.
- Caps: the body at most 24 MiB (413 beyond it), a JSON file at most 8 MiB, a video at most
  16 MiB decoded. A video must be WebM (`1A 45 DF A3`) or MP4 (`ftyp` at byte 4).
- File names are labels. The server stores the fixed names and keeps your name only as
  `original_name`. A name is refused (400 `files`) only when it is empty, longer than 255
  characters or holds a control character; spaces and other characters are fine. The Import
  screen removes control characters from the label it sends, so it never meets the rule; another
  client can. A message shows the name as a label: its last path part, without control characters.
- It runs the same importer as the command line and marks the entry `visitor: true`. One import
  runs at a time; another that arrives meanwhile gets 503 `busy, try again`. The files are read
  before the catalog is locked, and the lock is held only to write the entry.
- The whole body must arrive within 60 seconds, else the answer is 408 `body too slow` and the
  connection closes.
- A 400 carries the reader's sentence or one of `name`, `category`, `files`, `too many files`,
  `two <kind> files`, `<name>: is not valid JSON`, `<name>: file too large`,
  `<name>: not a WebM or MP4 video`, `<name>: not valid base64`, `body` (the content type is not
  JSON, the body is not a JSON object, or it nests too deep to read) or
  `nothing to play: add an animation.json or a skeleton.json`.

## The processor plug-in seam

Record sends a recording to a processor, which returns the shared files. The default is the mock
that writes synthetic files. Your chain takes its place without touching Part 6.

```python
def process(recording, report):
    report("processing:pose")
    ...
    return {"skeleton": skeleton_json, "animation": animation_json,
            "parts": {"skeleton": 3, "animation": 4}}    # optional
```

- Selection: `serve --processor <module>:<function>`, else `SIMON6_PROCESSOR`, else
  `part6.processor:process`. The string must match `^[A-Za-z_][\w.]*:[A-Za-z_]\w*$` and is
  imported when the server starts. A bad or missing one stops the server with a plain message and
  exit 2.
- Call: `function(recording, report)`. `recording` is `{id, name, category, duration_ms,
  video_path}`; `video_path` is `None` while capture is mocked. `report(status)` takes
  `processing:<stage>`, where the stage matches `^[a-z0-9][a-z0-9_-]{0,31}$`. Anything else is
  logged and ignored. The mock keeps the signature `process(recording, report=None)`.
- Result: a dict with any of `keyframes`, `skeleton` and `animation` (parsed JSON, at least one of
  `skeleton` and `animation`) means done. `{"status": "failed:<stage>: <reason>"}` means failed.
  An exception means `failed:<last reported stage, else processing>: <first line of the
  exception, at most 200 characters>`. Files the readers reject mean `failed:validate:
  <reader's sentence>`. A failed job writes no entry. The text of a returned `failed:` status is
  kept only when it is exactly `failed:<stage>: <reason>` with a valid stage and a reason. Any
  other, for example `failed: no person`, is served as `failed:<last reported stage, else
  processing>: <the text after "failed:">`, so every status matches the published pattern.
- Visitors read failures. The reason of a `failed:` status and the first line of an exception are
  served by `GET api/jobs/<id>` and shown on the Record screen. A processor must not put secrets,
  tokens, private paths or host names in them; log the detail on your side and return a plain
  reason.
- Status vocabulary, exactly: `queued`, `processing:<stage>`, `failed:<stage>: <reason>`, `done`.
  `contracts/job-status.schema.json` holds it as a pattern. `GET api/jobs/<id>` returns it; the
  Record screen polls every 500 ms and shows the stage.
- Queue: one worker thread runs jobs in order, at most 8 wait (503 `busy, try again` beyond), and
  the last 50 jobs are kept in memory and lost on restart. The entry folder is the durable result.
- Entries from the mock keep `files_source: "mock"`. Any other processor writes `processor`.
- Producer: a result may add `parts`, `{kind: part}` with a whole number from 1 to 7 (or `null`)
  for each kind it returns, for example `"parts": {"skeleton": 3, "animation": 4}`. Provenance
  records each file's format and the part declared for it, else `part: null`, as an import without
  `--part` does: the format alone never names a producer. The mock declares none. A `parts` that
  is not an object, or a part outside 1 to 7, fails the job as `failed:validate: parts...`.
- No timeout. A processor that never returns blocks the worker, and Python cannot stop a thread.
  Your chain should time out its own subprocesses.

Two fake processors exercise the seam, as test data: `fixtures.processors.part4_fake:process`
reports `processing:keyframes`, `processing:skeleton` and `processing:animation`, pausing
`SIMON6_FAKE_STAGE_S` seconds at each (default 1.2), and returns Part 4's v1 files with
`parts` naming Part 4.
`fixtures.processors.part4_fake:fail` reports `processing:pose` and returns
`{"status": "failed:pose: no person found in the video"}`.

## The hand-off to Part 7

Each entry has a page at `#/entry/<id>`. The old `#/movement/<id>` opens the same page. The page
has a Follow button (`data-testid="follow"`). Tapping it builds this object and tries four things
in order, stopping at the first that takes it:

```
detail = {v: 1, id, name, category, link, manifest,
          files: {keyframes, skeleton, animation, video}}
```

`link` is the address of the entry page and `manifest` the address of its manifest. Every value in
`files` is an absolute URL, or null when the entry has no such file.

1. Event. A cancelable `CustomEvent("simon:follow", {detail})` goes to `window`. A listener that
   calls `preventDefault()` owns the action.
2. Message. When the app is framed, it posts `{type: "simon:follow", ...detail}` to
   `window.parent`. Check `event.origin` on your side.
3. URL. When the contract's `handoff.follow_url` is set, Part 6 opens it. Set it with
   `serve --follow-url URL` or `SIMON6_FOLLOW_URL`. `{id}` and `{manifest}` are filled in,
   URL-encoded. Only `http` and `https` are accepted, and a bad value stops the server at start
   (exit 2).
4. Note. Otherwise the page shows a note (`data-testid="follow-note"`).

```js
window.addEventListener("simon:follow", (event) => {
  event.preventDefault();
  openFollowScreen(event.detail.id, event.detail.files.animation);
});
```

## The conformance kit

`make check-6-contract` runs the kit and prints one metrics JSON; it exits 0 only when every
metric passes. The drive uses a phone-sized browser and starts its own servers on temporary
catalogs. A metric that was not measured is null and fails. These are all of them:

| Metric | Passes when | What it checks |
|---|---|---|
| `golden_cases_py_failed` | 0 | cases in `fixtures/conformance/formats/` (`cases.json`) that the Python readers get wrong |
| `golden_cases_js_failed` | 0 | the same cases through `web/formats.js` |
| `golden_cases_total` | at least 20 | cases that ran |
| `entries_doctor_ok` | equals the entry count | entries in `fixtures/conformance/entries/` (eight, two for each `files_source`) that pass `python3 -m part6 doctor` |
| `contract_endpoint_ok` | 1 | `api/contract` equals `python3 -m part6 contract` |
| `entries_play_ok` | equals the entry count | entries that play, with no format error and the skeleton note only on an entry with no animation |
| `files_panel_ok` | equals the entry count | entries whose files panel shows each kind as present or missing, with the right format |
| `skeleton_fallback_ok` | 1 | every entry with no animation plays its skeleton |
| `format_error_shown` | 1 | the broken animation shows its format error and the page plays the skeleton instead |
| `import_screen_ok` | 1 | files dropped on the Import screen are saved as an entry with `files_source: "import"` |
| `import_error_kept_ok` | 1 | a stubbed 400 from import shows the server's sentence and keeps the filled form; a stubbed 413 shows the screen's own sentence (`The files are too large for the server. Remove one and try again.`), not the server's reason; Import again saves without retyping |
| `nan_import_refused` | 1 | `POST api/import` with a file holding `NaN` answers 400 `<file>: is not valid JSON` and stores nothing |
| `nonfinite_entry_refused` | 1 | a hand-placed entry whose `animation.json` holds `1e400` in an ignored field shows `animation.json: is not valid JSON` on the detail page, as `part6 doctor` prints it, and plays nothing |
| `processor_stages_ok` | 1 | with the fake processor the Record screen shows at least two `Processing: <stage>` texts and saves an entry with `files_source: "processor"` |
| `waiting_to_start_shown` | 1 | a second recording shows `Waiting to start` while the first runs, then a stage, then opens its entry |
| `processor_failure_shown` | 1 | a processor failure shows its reason, stores no entry and does not open the detail page |
| `processing_retry_ok` | 1 | Try again after a failure sends the same body as a new job, which fails again and stores nothing |
| `follow_event_ok` | 1 | Follow dispatches a cancelable `simon:follow` event with `v: 1` and the entry id; a listener that calls `preventDefault()` keeps the note hidden |
| `follow_message_ok` | 1 | framed, Follow posts `{type: "simon:follow", v: 1, id, manifest}` to the parent from the frame and the note stays hidden |
| `follow_url_ok` | 1 | with `--follow-url` set, Follow opens the filled URL, which `api/contract` also reports |
| `follow_note_ok` | 1 | with no listener, no frame and no URL, the note shows inside the viewport and the address does not change |
| `console_errors` | 0 | console errors during the whole drive |

The entries and the goldens are plain files, so Part 7 can read them with no server running.

## Version policy

`schema_version` in the manifest and `contract_version` in the contract document are both `1`. An
added field keeps them at 1, so a reader ignores fields it does not know, including a key under
`provenance` that it has not heard of. A breaking change makes them 2. Part 6 reads only the fields
named in the schemas. A new format version is a new reader
and new golden cases, and an entry made with it records its id in `provenance`.
