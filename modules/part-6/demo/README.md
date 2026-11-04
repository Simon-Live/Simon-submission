# How this was built

Simon Part 6 (a phone-browser catalog of movements with a rotatable 3D player and a mocked Record flow) was built by Claude Code from one prompt, unattended. The prompt is in [PROMPT.md](PROMPT.md), saved verbatim when the run started. Human turns during the run: 0.

## The run

| | |
|---|---|
| Start (UTC) | 2026-10-27T22:57:20Z (written to `.run/start` at minute 0) |
| End (UTC) | 2026-10-27T23:46:26Z (the time of the last commit before the publish) |
| Wall clock | 0h 49m |
| Human turns | 0 |
| Claude Code | 2.1.312 (Claude Code) |
| Model | claude-opus-5-5 (main session); lanes A, B and C on the sonnet tier; the reviewer agent on the opus tier |
| Commits in the run | 10 before this file's own commit (`git rev-list --count oneshot-start..HEAD`) |
| Prompt SHA-256 | `232f9e585a63118357986f8840b3a56c0ae38611bf5894426b626ab31f088b14` |

One main session planned and integrated; three agents built in parallel on disjoint files: the server and data, the web app and 3D player, and the done-check with this demo capture. One independent reviewer agent read the integrated result against the spec, and its blocking findings were fixed before the publish.

## What it made

Lines of code (`wc -l`):

| Folder | Lines |
|---|---|
| `part6` | 1329 |
| `web` (without `web/vendor`) | 1929 |
| `check` | 1297 |
| `tests/part6` | 2244 |

Tests: `python3 -m pytest tests/part6 -q` reports `536 passed` (exit 0).
Done-check: `make -s check-6` measures 29 metrics, every threshold passes, exit 0. Its output is [metrics.json](metrics.json), unedited.

Local commits, oldest first (`git log --reverse --format='%h %s' oneshot-start..HEAD`):

```
86b111a docs(part6): run start, README output section, lane interface locks
4979d0f feat(part6): web app, 3D player, done-check and demo capture
f0a1576 chore(progress): lanes B and C integrated
990d4da feat(part6): catalog server, API, mock processor and fixture catalog
3bebcac test(part6): read raw socket replies until close
1997727 chore(progress): lane A integrated, first check run
5c00e33 docs(part6): consolidated review verdict, README pytest requirement
7c8ad49 fix(part6): review fix batch 1
bcee9a7 fix(check): wait for the speed button, not the reported speed
5104791 feat(demo): Pixel 7 screenshots, walkthrough video and final metrics
```

## Screens

Pixel 7 emulation (412 px wide, device scale 2.625), from `make -s demo-6`:

- [01-catalog.png](screenshots/01-catalog.png): the catalog with six movements, chips and search
- [02-filter-dances.png](screenshots/02-filter-dances.png): the Dances chip
- [03-search.png](screenshots/03-search.png): search for "lunge"
- [04-player-front.png](screenshots/04-player-front.png): the 3D player, Front view
- [05-player-side.png](screenshots/05-player-side.png): Side view
- [06-player-top.png](screenshots/06-player-top.png): Top view
- [07-record-camera.png](screenshots/07-record-camera.png): the Record screen with the mock camera view and its timer
- [08-record-form.png](screenshots/08-record-form.png): the name and type form after Stop
- [09-processing.png](screenshots/09-processing.png): Processing
- [10-new-entry-player.png](screenshots/10-new-entry-player.png): the new entry playing in 3D, labelled Mock recording
- [11-new-entry-in-catalog.png](screenshots/11-new-entry-in-catalog.png): the new entry in the catalog

[walkthrough.webm](walkthrough.webm): browse, filter, search, open a movement, play, rotate by touch drag, switch speed and views, scrub, then Record, Stop, name and type, Processing and the new entry playing.

## Staging walkthrough

[staging-walkthrough.mp4](staging-walkthrough.mp4) is a screen recording of the app running as a staged service behind a firm gateway, under the `/simon-part-6/` path prefix, in Pixel 7 emulation (headless Chromium, not a phone in hand). It is one recording with no cuts, and nothing is seeded for it.

What it shows, in order:

1. The catalog opens, Dances is tapped, and a search for "side" leaves Side step.
2. Side step is opened and played at 1x, then 0.5x, and a one-finger drag turns the figure.
3. Front, Side and Top snap the camera.
4. Back to the catalog, Record, and Stop after a few seconds; a name is typed ("Cha cha") and Dance is chosen.
5. Save shows Processing, and the new entry opens and plays.
6. Back to the catalog, a search for "cha" finds the entry (labelled Mock recording), and it is opened and played.
7. Back to the catalog, All, a search for "part 4", and Squat (Part 4) is opened and played; its Files panel lists Part 4's key frames, skeleton and animation versions.
8. Import: Part 4's version 1 key frames, skeleton and animation files are chosen, each listed with its format; a name is typed and Import opens the new entry, which plays and lists its files.
9. Back to the catalog and a page reload: the imported entry is still listed.

How it was made: `staging/walkthrough.mjs` (in the firm workspace; `staging/` is local only and not published) loads the same `check/harness.mjs` as `make check-6`, so the browser, launch flags and Pixel 7 context are the same. Playwright `recordVideo` records one page in one context at the Pixel 7 viewport size. A small ring is drawn at each touch so a viewer can see taps and drags. The app is driven only through its screens, and each scene waits for the app's own ready signals before the next step, with short holds for reading. The login for the gateway comes from `STAGING_USER` and `STAGING_PASSWORD` and is not printed. When the run finishes, the script converts the webm with ffmpeg (libx264, yuv420p, `-movflags +faststart`, width and height cropped to even numbers, CRF 23 unless the file would reach 15 MB), checks the result with ffprobe (codec h264, under 90 s, under 15 MB, otherwise exit 1) and removes the entries it made (the recording and the import) with `staging/remove-entry.py`, so the recording leaves no entry behind in the staged catalog.

Measured from ffprobe on the file in this folder:

| | |
|---|---|
| Codec | h264, yuv420p |
| Duration | 61.4 s |
| Size | 1036529 bytes (CRF 23) |
| Dimensions | 412 x 838, 25 fps |

Record it again, from the firm workspace at the repo root:

```bash
# through the gateway: the login is supplied by the firm's staging tool, never typed or printed
staging.sh exec simon-part-6 -- scripts/with-browser-slot.sh node staging/walkthrough.mjs

# against a local server, to a scratch file; stop the server afterwards
STATE=$(mktemp -d) && mkdir "$STATE/catalog"
SIMON6_BASE_PATH=/simon-part-6 python3 -m part6 serve --catalog "$STATE/catalog" --port 8730 &
STAGING_SECRETS_DIR="$STATE" SIMON6_WALKTHROUGH_OUT=/tmp/walk.mp4 \
  scripts/with-browser-slot.sh node staging/walkthrough.mjs http://127.0.0.1:8730/simon-part-6/
```

The script prints one JSON line (file, duration, size, codec, entry id, whether the entry was removed). Without `SIMON6_WALKTHROUGH_OUT` it writes `demo/staging-walkthrough.mp4`. The script exits 2 for a gateway URL when the login is not in the environment.

## Run it

```bash
python3 -m part6 serve        # then open http://127.0.0.1:8726
make check-6                  # needs Node 22+ and pytest; prints the metrics JSON
make demo-6                   # rewrites demo/screenshots and demo/walkthrough.webm
```

Things to try: filter by Dances, search "lunge", open Squat, press Play, drag the figure to turn it, pinch or scroll to zoom, tap Side and Top, switch to 0.5x, scrub. Then Record, stop after a few seconds, name it, choose a type and Save: the new movement plays in 3D and stays in the catalog after a reload.

## Limits

- Checked under Pixel 7 emulation in headless Chromium only, not on a phone in hand.
- Recording's capture and processing are mocked behind `part6/processor.py`. Record shows a mock camera view; the new entry's keyframes, skeleton and animation are synthetic, generated from a seed. The real video to frames to 3D to animation part replaces that one function.
- Every movement in the catalog is synthetic (`fixtures/output/catalog`), and so are the input fixtures.

## Prepared before the run

One prompt plus these prepared inputs; no implementation code existed at the local tag `oneshot-start` (commit `d269a4e`). The specs, ADRs, tickets and brief stay in the local workspace and are not published here.

- the specs, contracts, ADRs, tickets and the execution brief the prompt points to;
- the synthetic input fixtures in `fixtures/input/`;
- three.js 0.186.1, vendored in `web/vendor/three/`;
- the Playwright 1.61.1 pin and its lockfile;
- the publish script that copies this part upstream;
- the locked decisions and the pre-run audit that set them;
- the firm `CLAUDE.md` notice, rules, skills, hooks and agents that Claude Code loads in this repo;
- the `/goal` text itself, which kept the session running until its conditions held.

[provenance.json](provenance.json) holds the same record in machine-readable form.
