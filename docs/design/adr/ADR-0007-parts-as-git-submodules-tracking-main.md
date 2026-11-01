# ADR-0007: Parts as git submodules tracking main

> Copy of `docs/adr/ADR-0007-parts-as-git-submodules-tracking-main.md` from the development workspace, edited for publication; the code is the authority where they differ.
Status: Accepted
Date: 2026-10-31
Supersedes: the pin parts of ADR-0002 (`parts.lock.json`, `make repin`, detached clones under the
state directory) and the pin wording of ADR-0006. Black box by process (ADR-0002) stands.
Source: project decision of 2026-10-31.

## Context
Parts 1 to 6 are libraries and modules owned by other repos. ADR-0002 ran each at a commit recorded in
`parts.lock.json`, cloned detached into `~/.local/state/simon-part-7/parts/<n>@<sha12>/`, and moved
the commit with `make repin`. A reconcile command was planned on top to compare the lock with the
upstream mains. The lock, the clone directory and the re-pin ritual were machinery that only existed to
hold a part still, while the project owner wants Part 7 to run what each part currently publishes.

## Options considered
### Option 1: pinned lock plus reconcile (the state before this ADR)
- Pros: reproducible; a check run can be replayed at its recorded shas.
- Cons: a second source of truth that drifts from the parts; private clones with their own
  environments; a command to compare and a command to move; every part fix waits for a re-pin commit.
  Effort: already built, ongoing upkeep.

### Option 2: submodules pinned at a commit, bumped by a command
- Pros: reproducible through Part 7's own history; standard git; no private clone directory.
- Cons: still a bump step and a commit per part change; Part 7 lags the parts by design, which the
  operator does not want.
  Effort: Low.

### Option 3: submodules tracking `main` of each part repo (chosen)
- Pros: Part 7 always runs the latest of every part; no lock, no re-pin, no reconcile; one way to see
  the state (`part7 parts-status`); the part repos are the only place a part's code lives.
  Part 7 can keep no copy of part logic, because the module is the part.
- Cons: no reproducible pin (see trade-off). Effort: Low.

## Decision
- Six submodules at `modules/part-1` to `modules/part-6`, each with `branch = main` and `ignore =
  untracked` in `.gitmodules`, at the the team repo URLs.
- `make parts` runs `git submodule sync --recursive`, `git submodule update --init --remote
  --recursive`, then `part7 setup-parts`. Setup is idempotent per sha: a stamp file in the state
  directory records the sha a part was set up at.
- `part7 parts-status [--check-remote]` prints the checked-out sha, the remote main sha and the URL of
  each part; with `--check-remote` it exits 3 when any part is behind its remote main (4 when a
  checkout or remote cannot be read). Staging uses it to decide whether to run `make parts`.
- Part 7 calls the part's own code and entry points from the module and keeps no copy or
  re-implementation of part logic. Where a part offers no entry point for something, a thin adapter in
  `part7/parts/` stays and is listed in `docs/specs/parts-harness.md`.
- The build stamp, `api/health`, `make chain` and check-7 report the module shas read from the
  checkouts. The check-7 gate `pins_consistent` now means the app path and the direct path ran at the
  same module shas.
- Virtual environments stay inside each module (ignored through `ignore = untracked`), updated in place
  by the part's own setup. Part 2's GPU venv stays outside, under ASM-012.

## Trade-off
There is no reproducible pin. A check-7 result names the shas it ran at, but the same shas are not
restored by checking out the Part 7 commit: the gitlinks in Part 7 are only hints, and `make parts`
moves every module to `main`. A part's broken push breaks Part 7 until that part is fixed. A part
force-pushing `main` moves Part 7 without a record in Part 7.

## Mitigations
- `part7 doctor-parts` checks each part's `contract` or `--help` in its module; `make parts` stops and
  names the part when its setup fails.
- Every step record carries the module sha it ran at; `make chain` and check-7 outputs list the shas;
  the build stamp shows them to a visitor.
- `parts-status --check-remote` makes a stale module visible, and staging can refuse to keep running an
  update it did not intend.
- When a break must be bridged, the module can be checked out at an earlier part commit by hand
  (`git -C modules/part-<n> checkout <sha>`); `parts-status` then reports the exact sha and `--check-remote`
  reports it as behind. This is an escape hatch, not a workflow.
- The part owners are the ones who fix a break; Part 7 does not patch around a part.

## Consequences
- Removed: `parts.lock.json`, `part7/pins.py`, `part7 pin`, `make pin`, `make repin`, `SIMON7_LOCK_PATH`,
  the `<n>@<sha12>` clone directories, `config.PART_REPOS`, `config.PART_WORKSPACES`, `config.parts_dir`.
- Added: `modules/`, `.gitmodules`, `part7/modules.py`, `part7 parts-status`, `make parts`,
  `config.modules_dir()` and `config.part_dir()`, `SIMON7_MODULES_DIR`.
- The Part 5 replay schema fallback (`BUILTIN_SCHEMA`) is removed; the schema comes from the module and
  the check fails closed when it is missing.
- `docs/specs/parts-harness.md` is rewritten around modules.

## Dissent Review
Reviewed by: modules lane (self), 2026-10-31.
- Concern 1: check-7 can no longer be replayed bit for bit. Resolution: accepted by the project owner; the
  result file names the shas, and the tolerance gates (ADR-0005) already compare two runs of the same
  parts rather than a stored output.
- Concern 2: a submodule's `.venv` can go stale when a part changes its requirements. Resolution: setup
  reruns on every new sha (`make .venv/.installed`, `uv sync` and `pip install -r` are incremental).
