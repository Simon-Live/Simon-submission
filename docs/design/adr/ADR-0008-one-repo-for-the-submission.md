# ADR-0008: One repo for the submission

Status: Accepted, 2026-11-04 (the team). Supersedes the submodule part of [ADR-0007](ADR-0007-parts-as-git-submodules-tracking-main.md).

## Context

The Meta Global AI Developer Hackathon judges a submission from **one public GitHub repo that holds everything needed
to run and verify the demo**. A repo that only links to others is not enough, and a second repo linked from the README
is not treated as part of the submission. The repo must be created on 26 Oct 2026 or later, hold only work done during
the event, and it is frozen at the deadline, Wed 4 Nov 2026, 9:00 PM ET.

Simon was built as seven repos, all created on 26 Oct 2026; this one (Part 7) held Parts 1 to 6 as git submodules.
A submodule is a link to another repo: its files are not in this repo's snapshot or a ZIP download.

## Decision

This repo is the submission. Parts 1 to 6 are merged into it with `git subtree`, each with its full history, at the
commit the demo uses, under the same paths, `modules/part-1` to `modules/part-6`. `modules/PINS.json` names the part
repo and commit each came from. `.gitmodules` is gone; `make parts` only sets the parts up; CI runs the full suite.

## Consequences

- A plain `git clone` holds the whole app, every part, the tests and the docs.
- Every part's commits since 26 Oct 2026 are in this history, so the work's dates can be checked.
- The repo is about 190 MB.
- Part 1's three labelled videos are Git LFS objects, carried into this repo's LFS store.
- A staging build that serves from a module tree of separate checkouts (`SIMON7_MODULES_DIR`) keeps working:
  `part7/modules.py` reads a part with git when it is a checkout of its own, else from `modules/PINS.json`.
