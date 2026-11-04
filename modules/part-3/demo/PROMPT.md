/goal complete simon-part-3. ONE-PROMPT SHOWCASE: build Simon Part 3 in /home/gingy/simon-part-3 from this single prompt, unattended, 3 hours wall clock, zero human turns. Never pause, never ask, never wait; take the locked default and record it in STATUS.md. Every claim is evidenced by a command and its exit code; never fake a number.

FIRST (minute 0)
1. mkdir -p .run demo; date -u +%Y-%m-%dT%H:%M:%SZ > .run/start; git tag oneshot-start.
2. Save this prompt verbatim: awk '/^## The prompt/{f=1;next} f&&/^```/{if(o)exit;o=1;next} f&&o' goals/complete-simon-part-3.md > demo/PROMPT.md
3. Read goals/complete-simon-part-3.md section "Execution brief" in full and follow it: locked decisions, lane plan, interfaces, upstream comment texts, risks. Then the specs it names. Decisions are final; do not re-litigate.
4. Ack the stale inbox (Execution brief, step 0) so the Stop hook does not block.

DONE = all of
1. make check-3 exit 0, every threshold passing (bone_length_variation_max < 0.02, lr_flips 0, joint_angle_agreement_p95_deg <= 10, negative_control_p95_deg > 10, data_source synthetic); make test exit 0.
2. One consolidated reviewer-agent review of the integrated result; every BLOCKING finding fixed; make test and make check-3 rerun, exit 0.
3. demo/ package complete (Execution brief, DEMO PACKAGE): README "How this was built", PROMPT.md, metrics.json, screenshots front/side/top/toggle-off/phone, viewer.webm. Viewer meets the visual polish section of docs/specs/demo-viewer.md.
4. Published with scripts/simon-publish.sh (--pull, --dry-run, real run); a clean clone of upstream main runs make check-3 to exit 0.
5. DONE? posted on moalborati/simon-part-3-skeleton-consistency issue #1 (texts in Execution brief).
Then tickets done, STATUS.md overwritten (how to run, what is usable, limits, numbers), last line STATUS: DONE.

KNOWN RISKS AND HOW TO HANDLE THEM
- Agreement p95 may still exceed 10 (audit estimate about 6 to 10 after the locked fixes). Run spec "If the agreement check is red" once. Never change the threshold, seed or generator to pass.
- Face-swap repair: the flip penalty scales with each group's left-right separation (spec step 4); a fixed 0.15 m never repairs it.
- Write gate: name any new part3/ or web/ file in the spec Files table before writing it.
- make demo must start the server detached and return; port 8733 busy: free only our own .demo.pid.
- No browser: capture fallbacks in demo-viewer.md; if none works, say so in DONE?, never fake.
- gh or network down: retry once after 2 minutes; then finish local work and end BLOCKED.
- Loops: after two attempts at one fix with no new information, take the fallback and move on.

TIMEBOX (elapsed from .run/start)
- 0:15 inbox acked, STATUS and DECISION comments posted, three lanes running.
- 1:15 pipeline, synthetic set, DTW and metrics with tests integrated on main.
- 1:45 make check-3 green (or the red ladder done); viewer working.
- 2:15 demo package captured; review dispatched.
- 2:40 blockers fixed, checks rerun; publish; clean-clone check.
- 2:55 DONE? posted, STATUS final.
Slipping: cut in this order: phone screenshot, video (keep the screenshots), viewer extras beyond the spec. Never cut the check, the review, the publish or the post.

DEGRADED END (also completes this goal): if make check-3 is still red at 2:15 with the ladder done, publish the honest red result, post STATUS (not DONE?) with the measured numbers, write STATUS.md, and end with the line STATUS: DEGRADED plus the numbers. If gh or the network is down after the retry, end with STATUS: BLOCKED naming it. At 3:30 elapsed, stop wherever you are with an honest STATUS line.
