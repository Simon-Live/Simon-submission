# Challenge lane, 2026-10-31 (R2, R6, R8)

Branch `lane/challenge`. Spec: `docs/specs/challenges.md`. Tickets: TICKET-072, TICKET-076, TICKET-078.
A "Reel" is a Part 6 catalog entry; a challenge is one Reel plus a board of scores.

## R2 Challenge a friend with a share card (TICKET-072)
**Added.** On a finished result the challenge slot offers "Challenge a friend": it creates a friend challenge titled
"Beat my <movement>", adds this result as the first score (the server reads it), and shows the share step: the card
picture, Share, Copy link and See the board. When the person arrived through "Take the challenge", the same slot offers
"Add my score to <title>" instead of making a new challenge.
- Share card: `web/share-card.js`, a 1080 x 1350 PNG drawn on a canvas (movement, name, score, grade, strongest section,
  "Can you beat it?", title, link text, "Sponsored by" when sponsored). The share sheet gets the file, link and text; with
  no share sheet the PNG downloads and the link is copied.
- Files: `web/challenge-actions.js`, `web/challenge-core.js`, `web/share-card.js`, `part7/challenges.py`,
  `part7/challenge_routes.py`, one dispatch line in `part7/server.py`.
- Routes: `POST api/challenges`, `POST api/challenges/<id>/entries`, `GET api/challenges`, `GET api/challenges/<id>`.
- Test ids: `challenge-actions`, `challenge-name`, `challenge-create`, `challenge-join`, `challenge-error`, `challenge-link`,
  `share-card-preview`, `challenge-share`, `challenge-copy`, `challenge-open`, `share-status`.
- Tests: `tests/part7/test_challenges.py`, `tests/part7/challenge.unit.test.mjs`, `tests/part7/challenge.browser.mjs`.
- Staging: `staging/checks-challenge.mjs` (integrator wires it). Open a finished result and press "Challenge a friend".
- Limits: the link works for anyone who can open the app; the app has no accounts or login. The slot is filled by `web/challenge-actions.js` once the result
  screen mounts it (contract item 1); until then the module is dormant.

## R6 Crew challenge and leaderboard (TICKET-076)
**Added.** `#/challenge/<id>` shows the movement (name and video thumbnail), who started it, the countdown, a row per person
with rank, name, score, grade and a "Strongest: <section>" badge, and "Take the challenge" and "Share this challenge". The
watch screen lists the movement's open challenges. The group result has "Start a crew challenge", which posts every scored
person at once (names from the group labels, cut to 24 characters).
- Strongest section: the best compared window of `score.timeline` (Part 5's number, selected; ties to the earliest);
  no timeline, no badge. Label as `web/timeline.js` writes it.
- Files: `web/challenge.js`, `web/challenge.css`, one line in `web/app.js`, three in `web/watch.js`, a slot and one lazy
  import in `web/group-result.js`.
- Test ids: `leaderboard`, `board-row-<n>`, `board-rank-<n>`, `board-name-<n>`, `board-score-<n>`, `board-grade-<n>`,
  `board-strongest-<n>`, `board-empty`, `challenge-title`, `challenge-movement`, `challenge-thumb`, `challenge-ends`,
  `take-challenge`, `challenge-ended`, `share-link`, `watch-challenges`, `challenge-list`, `challenge-link-<id>`,
  `crew-slot`, `crew-challenge`, `crew-challenge-start`.
- Try on staging: finish a group job, open its result, press "Start a crew challenge".
- Limits: no accounts; names are not identities. A take older than 7 days cannot be added (its job is gone), but the board
  stays. "Take the challenge" keeps the challenge id in `sessionStorage`, since the hash router keeps no query string.

## R8 Brand-sponsored challenges (TICKET-078)
**Added.** The operator creates a sponsored challenge from the command line; the public board shows a sponsor banner
(name, tagline, prize, a link with `rel="noopener sponsored"`), a "Sponsored" label, the countdown and the leaderboard.
The list on the watch screen marks sponsored challenges. There are no payments: the brand's funding is the prize text.
```bash
uv run python -m part7 challenge create --staging --entry <entry-id> --title "Raise the roof" \
  --sponsor-name "Example Sportswear" --sponsor-url https://example.com --prize "A pair of running shoes" --ends 2026-12-01
uv run python -m part7 challenge list --staging
uv run python -m part7 challenge close <id> --staging
```
- Files: `part7/challenge_cli.py`, a subparser and a branch in `part7/cli.py`.
- The public API refuses a sponsor, an end time and the kind `sponsored` (400).
- Tests: the CLI cases in `tests/part7/test_challenges.py`; the banner, label, link and countdown in the browser test; an
  ended challenge hides "Take the challenge" (negative assertion).
- Limits: the operator seeds nothing automatically; prize judging and fulfilment happen outside the app.

## Cross-lane interfaces used
- Contract item 1: `mountChallengeActions(slot, ctx)` with `ctx = { job, pid, analysis, jobRecord }`. It needs
  `jobRecord.entry_id` (or `jobRecord.result.entry_id`); on `#/result/fixture` or without a record the slot stays empty.
- Contract item 5: new `tests/part7/fake_challenges.py` plus three small hooks in `fake_api.py` (challenge routes,
  `__test/challenges` seeding, a `/__harness/` static path).
- Contract item 6: `staging/checks-challenge.mjs` exports `runChecks({ page, baseUrl, runCheck, entryId, followJobId })`.

## Evidence
Filled at acceptance in the lane report: commands, counts and exit codes.
