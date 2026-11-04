/goal complete simon-part-6. ONE-PROMPT SHOWCASE: build Simon Part 6 (phone-browser movement catalog, rotatable 3D player, mocked Record flow) in /home/gingy/simon-part-6 from this single prompt, unattended, 3 hours wall clock, zero human turns. Never pause, never ask, never wait; take the locked value and record it in STATUS.md Decisions. Every claim is evidenced by a command and its exit code, a file or a commit; never fake a number.

FIRST (minute 0)
1. mkdir -p .run demo; date -u +%Y-%m-%dT%H:%M:%SZ > .run/start; git tag oneshot-start.
2. Save this prompt verbatim: awk '/^## The prompt/{f=1;next} f&&/^```/{if(o)exit;o=1;next} f&&o' goals/complete-simon-part-6.md > demo/PROMPT.md
3. Add one line under the firm notice in CLAUDE.md: "One-prompt run: task demo/PROMPT.md, state STATUS.md and progress/oneshot.md, detail goals/complete-simon-part-6.md Execution brief; after any compaction re-read all four."
4. Ack each requires_ack message the Stop hook names: scripts/comms.sh ack simon-part-6 <id>.
5. Read goals/complete-simon-part-6.md section "Execution brief" in full and follow it, then the files in its READ ORDER. Decisions are final; do not re-litigate.

AS YOU GO
Lanes A, B and C in parallel per the brief. After each milestone append to progress/oneshot.md (done, verified by which command and exit code, next) and commit each green step with explicit paths.

DONE = all of
1. scripts/with-browser-slot.sh make -s check-6 exit 0, every Done-check threshold passing, each metric measured; the pytest suite exit 0.
2. One consolidated reviewer-agent review saved to progress/review/; every BLOCKING finding fixed; check-6 rerun green.
3. demo/ package (brief, DEMO PACKAGE): PROMPT.md, README "How this was built", provenance.json, metrics.json, eleven Pixel 7 screenshots, walkthrough.webm; AC-014 polish done; committed before the publish.
4. Published with scripts/simon-publish.sh: dry run stderr says make check-6 exit 0, then the real run lands on the team main.
5. DONE? posted on moalborati/simon-part-6-recording-catalog issue #1 (brief, UPSTREAM PROTOCOL).
Then git tag oneshot-end, tickets done, STATUS.md overwritten (how to run, what is usable, limits, numbers), final message per brief FINISH, last line STATUS: DONE.

Read KNOWN RISKS and TIMEBOX in the brief before dispatching lanes; check elapsed time from .run/start at every TIMEBOX checkpoint.

DEGRADED END (also completes this goal): if check-6 is still red at 2:40, build the demo package from that run, publish the honest red result, post STATUS (not DONE?) with the failing metrics and measured values, set STATUS.md Blockers, tag oneshot-end, end with STATUS: DEGRADED plus the numbers. Never change a threshold or a measurement rule and never hardcode a value to get green. If gh and git over https both fail after one retry, finish local work and end STATUS: DEGRADED naming it. At 3:30 elapsed, stop wherever you are with an honest STATUS line.
