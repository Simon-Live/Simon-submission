# Spec: scripts/simon-publish.sh (the only path from this workspace to the team)
> Design copy of a working spec. Host paths and workspace tooling are neutralised; where this text and the code disagree, the code, `CONTRACT.md` and `docs/schemas.md` win. Index: `docs/design/README.md`.
Status: Implemented
Date: 2026-10-28
Request Type: new-feature
Risk Level: medium
ADR: `docs/design/adr/ADR-0001-workspace-and-publish-layout.md`. Tickets: TICKET-005, TICKET-030.
Tests: `tests/publish/test-simon-publish.sh`.

## Overview
Copies the allowlisted part files from the committed tip of local `main` onto `upstream/main` of
`https://github.com/moalborati/simon-part-5-fault-analysis.git` and pushes one commit there. Firm files
(rules, tickets, progress, specs, ADRs, staging, firm scripts, firm tool tests) never leave this
workspace. The script is Part 6's generic one, adapted: upstream owns `scripts/make_*.py` and (from
PR #34) `scripts/sync_contracts.py`, which pass the `scripts/` denylist by name, and upstream keeps its
pytest files at the `tests/` root beside firm tool tests, so `tests/test-*.sh` is refused by glob.

## Why This Is Wrong (Dissent-First)
1. An exception list inside a denylist is where a firm file slips through. Answer: exceptions apply only
   to files directly under `scripts/` that match the named globs; a subdirectory or any other name is
   refused (AC-P13).
2. Upstream and firm tests share `tests/`. Answer: the allowlist names `tests/test_*.py` and the
   denylist refuses `tests/test-*.sh`, `tests/lib/`, `tests/publish/`, `tests/staging/`, `tests/neighbour/`.
3. A wide allowlist line (`docs/**`) would publish specs. Answer: `docs/specs/`, `docs/adr/` and
   `docs/assumptions/` stay denylisted; `docs/schemas.md` and `docs/thresholds.md` pass because `docs/`
   itself is not denylisted.

## User Story
As the team, I publish part changes upstream without ever pushing a firm file.

## Interface
```
scripts/simon-publish.sh [--dry-run] [--pull] [-m|--message "<subject>"]
```
| Mode | Effect | Exit |
|---|---|---|
| (none) | fetch, mirror, check lists and content, run `make -s check-5`, run `make -s test`, commit, push | 0 published or nothing to publish; 1 when the tests fail |
| `--dry-run` | everything except commit and push; prints the file list, the check exit and the test exit | 0; 1 when the tests fail |
| `--pull` | fetch upstream main and merge into local `main` (clean tree, on main) | 0 or 3 on conflict |

Exit codes: 1 refused (denylist, secret name or content, not allowlisted, tests failing, dirty or wrong
branch for `--pull`), 2 usage, 3 git or push failure. The script prepends `$HOME/.local/bin` to `PATH`
(uv lives there; the Makefile runs `uv run`). A red done-check still publishes with its exit code in the
message; red tests (`make -s test` in the publish worktree) refuse, separately from the done-check.
Environment for tests: `SIMON_PUBLISH_URL`, `SIMON_PUBLISH_PART`, `SIMON_PUBLISH_CHECK_CMD`,
`SIMON_PUBLISH_TEST_CMD` (default `make -s test`), `SIMON_PUBLISH_CHECK_TIMEOUT` (default 1800, also
bounds the tests), `SIMON_PUBLISH_REFS` (default `Refs #17`, the Part 5 checklist), `SIMON_PUBLISH_TRAILER`,
`SIMON_PUBLISH_KEY_FILE` (default: the Baseten key file).

## Lists (in the script)
- Allowlist: `.simon-publish` (fail closed; missing or empty publishes nothing).
- Deny prefixes: `.claude/ .agents/ tasks/ progress/ comms/ goals/ qa/ staging/ docs/specs/ docs/adr/
  docs/assumptions/ scripts/ tests/lib/ tests/publish/ tests/staging/ tests/neighbour/ demos/ .run/`.
- Deny files: `AGENTS.md GEMINI.md CHAT.md CLAUDE.md STATUS.md .mcp.json .simon-publish
  .firm-sync-version package.json package-lock.json`.
- Deny globs: `tests/test-*.sh`.
- Exceptions to the `scripts/` prefix: `scripts/make_*.py`, `scripts/sync_contracts.py`, directly under
  `scripts/` only.
- Secret-shaped basenames: `.env`, `.env.*`, `*.pem`, `*.key`, `*secret*`, `*token*`, `*credential*`
  (the case forms listed in the script), `id_rsa*`, and the operator key file names `BASETEN_API_KEY`
  and `MUSE_SPARK_API_KEY`, refused at any depth.
- Secret-shaped content: every staged text file is searched for `sk-` followed by 20 or more key
  characters, `hf_` followed by 30 or more, `AKIA` followed by 16 upper-case letters or digits, and a
  GitHub token prefix (`ghp_`, `gho_`, `ghu_`, `ghs_` or `ghr_` followed by 30 or more letters or digits;
  `github_pat_` followed by 30 or more letters, digits or underscores); a match refuses the publish and
  names the file, never the match.
- The operator's key: when the Baseten key file exists, every staged file (binary ones included) is
  searched for its exact content, whitespace stripped, with `grep -aqF -f` against a temporary pattern
  file that is deleted before the script moves on; a match refuses the publish and names the file, never
  the key. An absent, empty or blank key file scans for nothing (an empty pattern would match every file).
- Published `.gitignore` drops lines naming a denylisted path or a firm-only cache (`.cache/`, `.run/`);
  the local copy keeps them.

## Acceptance Criteria (each is a block in `tests/publish/test-simon-publish.sh`)
- AC-P1 `--dry-run` lists allowlisted changes, reports the check exit code, never lists firm paths, pushes
  nothing.
- AC-P2 A publish mirrors only allowlisted paths; upstream `CLAUDE.md` is unchanged; the message carries
  the check exit code, the metrics JSON, `Refs #17` and ends with the trailer.
- AC-P3 Nothing changed: exit 0, no empty commit.
- AC-P4 A firm path in the allowlist (`STATUS.md`) refuses with exit 1, names it, pushes nothing.
- AC-P5 Secret-shaped files under an allowlisted directory refuse with exit 1, named.
- AC-P6 Deletions inside allowlisted paths propagate; teammate files outside them are kept.
- AC-P7 Uncommitted work is never published.
- AC-P8 A red check still publishes and the message says the exit code.
- AC-P9 `--pull` merges teammate changes into local `main`.
- AC-P10 A plain `git push upstream` fails (push URL disabled).
- AC-P11 The published `.gitignore` keeps only part lines and comments; republishing is a no-op.
- AC-P12 `scripts/make_dummy_followers.py`, `scripts/sync_contracts.py`, `docs/schemas.md`,
  `docs/thresholds.md` and `tests/test_*.py` publish; `scripts/simon-publish.sh` stays local.
- AC-P13 With `scripts/**`, `docs/**` and `tests/**` in the allowlist, every firm file is refused and
  named (`scripts/simon-publish.sh`, `docs/specs/`, `docs/adr/`, `tests/test-*.sh`, `tests/lib/`,
  `tests/publish/`, `scripts/make_dir/nested.py`), the upstream generator is not refused, nothing is
  pushed.
- AC-P14 Red tests on the publish candidate refuse with exit 1 (publish and `--dry-run`), report the test
  exit code, push nothing.
- AC-P15 With a bare `PATH`, the check and the tests see `$HOME/.local/bin`; the default `make -s test`
  passes and publishes.
- AC-P16 `*token*`, `*credential*`, `id_rsa*`, `BASETEN_API_KEY` and `MUSE_SPARK_API_KEY` files refuse with
  exit 1, each named.
- AC-P17 Files holding `sk-`, `hf_`, `AKIA` or GitHub token (`ghp_`, `github_pat_`) key-shaped strings
  refuse with exit 1, each named; ordinary text with those letters passes.
- AC-P18 Files holding the exact content of the key file (`SIMON_PUBLISH_KEY_FILE`) refuse with exit 1,
  each named, whatever the shape of the key; the key is never printed, no pattern file is left behind, a
  near miss passes, and an absent, empty or blank key file refuses nothing.

## Error Cases
| Condition | Behavior | Message format | AC |
|---|---|---|---|
| No allowlist | exit 1 | `no .simon-publish allowlist; nothing may be published` | AC-P4 |
| Denylisted path staged | exit 1 | `REFUSED <path>: firm path <prefix>` | AC-P4 |
| Tests fail on the candidate | exit 1 | `REFUSED: tests fail on the publish candidate; nothing published` | AC-P14 |
| Key-shaped content | exit 1 | `REFUSED <path>: secret-shaped content (sk-, hf_, AKIA or GitHub token prefix)` | AC-P17 |
| The operator's key in a file | exit 1 | `REFUSED <path>: holds the operator's Baseten key` | AC-P18 |
| Fetch fails | exit 3 | `fetch from <url> failed` | |
| Second push rejection | exit 3 | `push failed twice; nothing more is tried` | |

## Edge Cases
- `scripts/sync_contracts.py` does not exist until PR #34 lands (TICKET-004); the exception is harmless
  before then.
- The temporary worktree is removed by `git worktree remove --force` in an EXIT trap.

## Non-Functional Requirements Checklist
| Category | Requirement | Metric | AC |
|---|---|---|---|
| Security | No firm file upstream | denylist after allowlist | AC-P4, AC-P13 |
| Reliability | No network in tests | bare local remotes | all |

## Negative Requirements
- MUST NOT push with the remote name (its push URL is `DISABLED-use-scripts/simon-publish.sh`).
- MUST NOT change upstream `CLAUDE.md`.

## Non-Requirements
- Opening PRs; publishing branches other than `main`.

## Assumptions
Teammates push to upstream `main` directly, so `--pull` runs before each publish (ADR-0001).

## Delivery Verification Plan
Setup evidence, 2026-10-28: `bash tests/publish/test-simon-publish.sh` exit 0 (53 passed, 0 failed);
`scripts/simon-publish.sh --dry-run` exit 0 ("nothing to publish: upstream already matches main
a318541", the local main commit; upstream main is `06fd4a2`). After the review fixes (AC-P14 to AC-P17),
2026-10-28: `bash tests/publish/test-simon-publish.sh` exit 0 (75 passed, 0 failed). The first real publish is TICKET-005, after the three PRs land.

## Dissent Review
### Concern 1: an allowlist can drift from what the part needs
Kept: the publish runs `make check-5` in a worktree built from the allowlisted files only, and a fresh
clone runs `make check-5` and `make test` after each publish (TICKET-030).
### Concern 2: one script is the only path upstream
Kept: the script is small and tested; a blocked publish is visible, a stray firm push is not reversible.

## Deviations from PRD
None.
