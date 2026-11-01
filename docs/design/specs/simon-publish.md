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

Reconcile, never overwrite (operator ruling, moalborati/simon#61, 2026-11-01: "rebase sounds dangerous, make sure
none of our changes are ever destructive and that we take a reconciliation approach to everything we do").
Upstream work is integrated by merge, never by rebase or force push, and the other side is never discarded
or reverted. The publish commit is built from local `main` over upstream `main`, so it would silently undo
any upstream commit local `main` lacks; the publish and `--dry-run` therefore refuse unless local `main`
already contains upstream `main` (AC-P19). `--pull` is the merge that brings it in; after a publish,
upstream `main` is our own publish commit, which `--pull` merges back before the next publish.

Ancestry is not enough: the publish commit copies our whole tree, so a fast-forward push still undoes a
teammate's lines when our `main` changed them after merging (Part 7 undid a client change this way). The
teammate-lines guard (AC-P23) blames every line the candidate removes or changes, and every file it deletes,
at upstream `main`, and refuses when someone outside the firm's authors last wrote one; the only way past is
a `--teammate-override` that names a the team issue or PR comment.

## Why This Is Wrong (Dissent-First)
1. An exception list inside a denylist is where a firm file slips through. Answer: exceptions apply only
   to files directly under `scripts/` that match the named globs; a subdirectory or any other name is
   refused (AC-P13).
2. Upstream and firm tests share `tests/`. Answer: the allowlist names `tests/test_*.py` and the
   denylist refuses `tests/test-*.sh`, `tests/lib/`, `tests/publish/`, `tests/staging/`, `tests/neighbour/`.
3. A wide allowlist line (`docs/**`) would publish specs. Answer: `docs/specs/`, `docs/adr/` and
   `docs/assumptions/` stay denylisted; `docs/schemas.md` and `docs/thresholds.md` pass because `docs/`
   itself is not denylisted.
4. The publish commit is a copy of allowlisted paths over upstream, so a teammate's commit that landed after
   our last `--pull` is overwritten (an edited file) or deleted (an allowlisted file local `main` lacks), and
   the one retry after a rejected push rebuilt the same way over a concurrent push. Answer: the ancestry
   guard (AC-P19, AC-P20): refuse, merge with `--pull`, publish.
5. After the merge, our `main` can still change or delete a teammate's lines, and the copy then undoes them
   on a clean fast-forward. Answer: the teammate-lines guard (AC-P23), with a recorded override as the one
   way past, so a deliberate change leaves a trace in the commit message and on a the team thread.

## User Story
As the team, I publish part changes upstream without ever pushing a firm file.

## Interface
```
scripts/simon-publish.sh [--dry-run] [--pull] [--record] [-m|--message "<subject>"] [--teammate-override <URL>]
```
`--teammate-override <URL>` goes with a publish or `--dry-run` only (`--pull` or `--record` with it is a usage
error, exit 2); a missing value is exit 2; the URL must match
`https://github.com/moalborati/<repo>/(issues|pull)/<n>#issuecomment-<id>` (shape only, no network call) or the
run is refused with exit 1 before any git work, whether or not teammate lines are involved (AC-P23).
| Mode | Effect | Exit |
|---|---|---|
| (none) | fetch, refuse unless local `main` contains upstream `main`, mirror, check lists and content, run `make -s check-5`, run `make -s test`, commit, push | 0 published or nothing to publish; 1 when upstream has commits `main` lacks or the tests fail |
| `--dry-run` | everything except commit and push; prints the file list, the check exit and the test exit | 0; 1 when upstream has commits `main` lacks or the tests fail |
| `--pull` | fetch upstream main and merge into local `main` with a plain `git merge --no-edit` (clean tree, on main); stops on a conflict, never picks a side | 0 or 3 on conflict |
| `--record` | fetch upstream main and, only when that drops no upstream content (AC-P22), record it in local `main` with a keep-our-side merge (`git merge --no-ff -s ours`; clean tree, on main); a no-op when upstream is already an ancestor of `main` | 0; 1 when it would drop content, on a dirty tree or off main |

Exit codes: 1 refused (denylist, secret name or content, not allowlisted, tests failing, upstream `main` has
commits local `main` does not contain, teammate lines without a valid `--teammate-override`, `--record` would
drop upstream content, dirty or wrong branch for `--pull` or `--record`), 2 usage, 3 git or push failure
(a `--pull` merge conflict included). The script prepends `$HOME/.local/bin` to `PATH`
(uv lives there; the Makefile runs `uv run`). A red done-check still publishes with its exit code in the
message; red tests (`make -s test` in the publish worktree) refuse, separately from the done-check.
Environment for tests: `SIMON_PUBLISH_URL`, `SIMON_PUBLISH_PART`, `SIMON_PUBLISH_CHECK_CMD`,
`SIMON_PUBLISH_TEST_CMD` (default `make -s test`), `SIMON_PUBLISH_CHECK_TIMEOUT` (default 1800, also
bounds the tests), `SIMON_PUBLISH_REFS` (default `Refs #17`, the Part 5 checklist), `SIMON_PUBLISH_TRAILER`,
`SIMON_PUBLISH_KEY_FILE` (default: the Baseten key file),
`SIMON_PUBLISH_FIRM_AUTHORS` (the firm's author names, one per line; default the `FIRM_AUTHORS` line in the
script), `SIMON_PUBLISH_TEAMMATE_SHOW` (ranges listed before "and N more", default 20).

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
- Firm authors: the `FIRM_AUTHORS` line in the script, the one place they are named: `mal421499` and
  `MoAlborati` (`git log refs/remotes/upstream/main --format=%an` on 2026-11-01 shows `mal421499` for the
  firm's publish commits and `the team` and `the team` for the teammate; `MoAlborati` is the operator's other git
  name on local `main`). Names are compared exactly, as `git blame --porcelain` prints them.

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
- AC-P19 After fetching, the publish and `--dry-run` require `git merge-base --is-ancestor <upstream main>
  <local main>`. When it does not hold (a teammate commit landed after our last `--pull`, including one that
  edits an allowlisted file or adds an allowlisted file local `main` lacks) they exit 1 with `REFUSED:
  upstream main has commits local main does not contain; run scripts/simon-publish.sh --pull and resolve,
  nothing published`, before anything is built, checked or tested; upstream is unchanged, and no worktree or
  temp file is left. This holds even when nothing of ours is left to publish. After `--pull` merges the
  teammate's commit, the publish proceeds and the teammate's changes (edited file, new file, history) are
  still upstream. After each publish, upstream `main` is our own publish commit, which `--pull` merges back
  before the next publish.
- AC-P20 A teammate push between the build and our push: the push is rejected, the one retry refetches and
  re-checks AC-P19, refuses with exit 1 and the same message instead of rebuilding over the newcomer; the
  teammate's commit stays upstream's tip and our change is not pushed. After `--pull` the publish proceeds
  and keeps it.
- AC-P21 `--pull` is a plain merge: the script holds no rebase, reset, stash, clean, merge strategy or
  `-X` option, side pick (`--ours`, `--theirs`) or forced push. A conflict stops it with exit 3, the merge
  left in progress, both sides in the file and local `main` unmoved; while it is unresolved the publish
  refuses and a second `--pull` refuses (unclean tree). A dirty tree or a branch other than `main` refuses
  with exit 1 and the edit untouched.
- AC-P22 `--record` is the guarded form of the keep-our-side record merge the operator made by hand after
  each publish. After a publish, upstream `main` is our own published copy of `main`; `--pull` would merge
  it back and can stop on the filtered `.gitignore`. `--record` fetches and, with the tree clean and on
  `main`, does nothing (exit 0, "nothing to record") when upstream is already an ancestor of `main`.
  Otherwise it checks that the merge drops no content: every path upstream changed since the common
  ancestor (each merge base, when there are several) must already be identical in `main`, mode and bytes,
  with one exception: upstream's `.gitignore` may differ when it is exactly the publish's filtered copy of
  `main`'s (firm lines dropped). A path the publish never writes (`CLAUDE.md`, firm files) is unchanged
  upstream after our own publish, so it passes; a teammate's edit to one, a teammate commit, a deletion
  upstream, or a published file `main` has changed since the publish all fail the check. On a failure it
  exits 1, names each path (`NOT RECORDED <path>: upstream changed it and local main's copy differs`), says
  to run `--pull`, and leaves `main`, the index and the working tree unchanged. On success it makes one
  merge commit (`--no-ff`, so a fast-forward can never move the working tree) whose tree is `main`'s own,
  whose message starts `Record upstream <sha>` and ends with the trailer, and prints the result; nothing is
  pushed. The next publish then finds upstream in `main`. A dirty tree or a branch other than `main`
  refuses with exit 1, as `--pull` does.
- AC-P23 Teammate lines. After the candidate is built and the file checks pass, and before the done-check
  and the tests run, every line the candidate removes or changes relative to upstream `main` (the old-side
  ranges of `git diff --cached -U0`) and every line of a file it deletes is blamed at the upstream ref with
  `git blame --porcelain`. A line whose last author is outside the firm's authors is a teammate line; the
  publish and `--dry-run` then exit 1 with `REFUSED: settle it with the teammate, or pass
  --teammate-override <URL of the the team issue or PR comment where it was agreed or announced>; nothing
  published`, after listing `file:first-last by Author` for each range (a deleted file adds `(file deleted)`),
  at most 20 ranges (`SIMON_PUBLISH_TEAMMATE_SHOW`) then `... and N more range(s)`, and a total (`N range(s), L
  line(s) in K file(s), by A, B`). Nothing is pushed or left behind. Rules, all tested: a changed or deleted
  teammate line or file refuses; lines the firm wrote pass; a pure insertion into a teammate file passes
  (no old line is touched); a whitespace-only change to a teammate line refuses (the line text changed,
  and indentation can carry meaning); a moved teammate line refuses at its old position (no move
  detection; the new position is an insertion); a changed binary file is one row `file (binary file
  changed) by <last author of the file>`; a mode-only change touches no line. Author names are compared
  exactly (`Tes` does not cover `Tess`). With a well-formed `--teammate-override <URL>` the run proceeds
  (the dry run says so), prints the same list, and the commit message gains a block after the metrics line:
  `Teammate lines removed or changed, accepted under --teammate-override <URL> (agreed or announced there;
  an objection there reverts them)`, one `- file:range by Author` line each (the first 100, then `... and N
  more range(s)`), and `Total: ...`. The URL is where the change was agreed with the teammate or, failing
  that, announced to them with an invitation to object. A notice is not agreement, so the hint and the
  message both say "agreed or announced", and the message adds that an objection there reverts the lines
  (the revert is a new commit that restores them). An override with no teammate line involved is noted as
  not needed and recorded nowhere. A malformed override (wrong host or organisation, `http`, no
  `#issuecomment-<id>`, a non-numeric id, trailing text, empty) is refused with exit 1 before any git work.
  The guard runs on the retry after a rejected push too.

## Error Cases
| Condition | Behavior | Message format | AC |
|---|---|---|---|
| No allowlist | exit 1 | `no .simon-publish allowlist; nothing may be published` | AC-P4 |
| Upstream main has commits local main lacks (also on the retry after a rejected push) | exit 1 | `REFUSED: upstream main has commits local main does not contain; run scripts/simon-publish.sh --pull and resolve, nothing published` | AC-P19, AC-P20 |
| Candidate removes or changes teammate lines or deletes a teammate file, no override | exit 1, nothing pushed | the list (`file:first-last by Author`), `total: <N> range(s), <L> line(s) in <K> file(s), by <authors>`, then `REFUSED: settle it with the teammate, or pass --teammate-override <URL of the the team issue or PR comment where it was agreed or announced>; nothing published` | AC-P23 |
| Malformed `--teammate-override` URL | exit 1 | `REFUSED: --teammate-override must be a the team GitHub issue or PR comment URL (https://github.com/moalborati/<repo>/(issues or pull)/<n>#issuecomment-<id>); nothing published` | AC-P23 |
| `--teammate-override` without a value, or with `--pull` or `--record` | exit 2 | `--teammate-override needs a URL` / `--teammate-override applies to a publish or --dry-run only` | AC-P23 |
| `git merge-base` fails | exit 3 | `cannot compare upstream main with local main (git merge-base exit <n>)` | |
| `--pull` merge conflict | exit 3, merge left in progress | `merge stopped on a conflict; resolve it on main` | AC-P21 |
| `--pull` on a dirty tree or off main | exit 1 | `--pull needs a clean tree` / `--pull runs on main only` | AC-P21 |
| `--record` would drop upstream content | exit 1, nothing changed | `NOT RECORDED <path>: upstream changed it and local main's copy differs`, then `REFUSED: recording would drop upstream content; run scripts/simon-publish.sh --pull and resolve, nothing recorded` | AC-P22 |
| `--record`, no shared history | exit 1 | `REFUSED: upstream main shares no history with local main; run scripts/simon-publish.sh --pull and resolve, nothing recorded` | |
| `--record` on a dirty tree or off main | exit 1 | `--record needs a clean tree` / `--record runs on main only` | AC-P22 |
| `--record` merge fails | exit 3 | `record merge failed` | |
| Denylisted path staged | exit 1 | `REFUSED <path>: firm path <prefix>` | AC-P4 |
| Tests fail on the candidate | exit 1 | `REFUSED: tests fail on the publish candidate; nothing published` | AC-P14 |
| Key-shaped content | exit 1 | `REFUSED <path>: secret-shaped content (sk-, hf_, AKIA or GitHub token prefix)` | AC-P17 |
| The operator's key in a file | exit 1 | `REFUSED <path>: holds the operator's Baseten key` | AC-P18 |
| Fetch fails | exit 3 | `fetch from <url> failed` | |
| Second push rejection | exit 3 | `push failed twice; nothing more is tried` | |

## Policy (stated, not enforced by the script)
- Co-authorship: when a publish lands a teammate's PR content, the publish commit carries a
  `Co-authored-by: <name> <email>` trailer for each PR author, because the publish commit is a copy of
  `main` and git history alone would show only the firm as its author. The trailers go through
  `SIMON_PUBLISH_TRAILER` (several lines are allowed, one trailer per line, the firm's own trailer
  included). The script does not check this; the publisher reads the merged PRs and sets it.

## Edge Cases
- Blame attributes a line to the commit that first put it on upstream. Lines a teammate wrote and that
  reached upstream through a firm publish commit (a merged PR we published) are the firm's lines to blame,
  which is why the Co-authored-by policy matters; lines the teammate pushed or merged there themselves are
  theirs. The guard cannot see authorship that exists only on local `main`.
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
Teammates push to upstream `main` directly, so `--pull` runs before each publish (ADR-0001); since
2026-11-01 the script enforces it (AC-P19). The published `.gitignore` is filtered, so the `--pull` that
merges a publish commit back can stop on a `.gitignore` conflict (for example when the file is new on both
sides); the operator resolves it by hand, keeping the local firm lines, and commits the merge (AC-P11 test).

## Delivery Verification Plan
Setup evidence, 2026-10-28: `bash tests/publish/test-simon-publish.sh` exit 0 (53 passed, 0 failed);
`scripts/simon-publish.sh --dry-run` exit 0 ("nothing to publish: upstream already matches main
a318541", the local main commit; upstream main is `06fd4a2`). After the review fixes (AC-P14 to AC-P17),
2026-10-28: `bash tests/publish/test-simon-publish.sh` exit 0 (75 passed, 0 failed). The first real publish is TICKET-005, after the three PRs land.
Ancestry guard (AC-P19 to AC-P21), 2026-11-01: `bash tests/publish/test-simon-publish.sh` exit 0 (153 passed,
0 failed); the same file against the script before the guard fails 17 checks (all AC-P19, AC-P20 and the
unresolved-conflict publish of AC-P21), and against a copy whose `--pull` used `-X theirs` it fails the
AC-P21 and `.gitignore` conflict checks.
`--record` (AC-P22), 2026-11-01: `bash tests/publish/test-simon-publish.sh` exit 0 (183 passed, 0 failed);
against a copy whose content check is disabled it fails 11 checks (every teammate, CLAUDE.md and
changed-since-publish refusal).
Teammate lines (AC-P23), 2026-11-01: `bash tests/publish/test-simon-publish.sh` exit 0 (231 passed, 0 failed);
against a copy with the teammate check disabled it fails 35 checks.

## Dissent Review
### Concern 1: an allowlist can drift from what the part needs
Kept: the publish runs `make check-5` in a worktree built from the allowlisted files only, and a fresh
clone runs `make check-5` and `make test` after each publish (TICKET-030).
### Concern 2: one script is the only path upstream
Kept: the script is small and tested; a blocked publish is visible, a stray firm push is not reversible.

## Deviations from PRD
None.
