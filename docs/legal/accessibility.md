<!--
Drafting notes (removed before the page is served).
Operator acceptance, 3 November 2026: no lawyer reviewed this page. The operator accepted it without one, and the review line
was removed as the record of that acceptance. Names come from part7/legal_pages.py TOKENS.
Status wording and the answer time follow the W3C generator and its example:
https://www.w3.org/WAI/planning/statements/generator/ and https://www.w3.org/WAI/planning/statements/minimal-example/.
Our own checks: docs/prod-verify/a11y-copy.md (axe-core and keyboard runs) and docs/specs/a11y-go-live.md. No outside audit
is in the repo. The answer time is a firm default the operator may change.
B9 (a11y-copy): the contact below is the address the operator chose on 3 November 2026. The prod start check (part7/legal_drafts.py via prod_check.py)
refuses to start prod while any served page holds a square bracket placeholder.
a11y-copy B3, review R4: the caption producer landed (part7/narration_own.py). In prod a trainer movement keeps its
sound only with captions (narration_own.drop_audio, also at the take delete) and is published only after that step
(processor.trainer_job), so the old captions gap is gone from "Known gaps".
Measured contrast and the axe runs of the go-live fix lane: docs/specs/a11y-go-live.md.
-->
# Accessibility

Last updated 4 November 2026.

## Our aim

Simon aims to meet the Web Content Accessibility Guidelines (WCAG) 2.2 at level AA on sign-in, recording and
uploading, and the results. It uses no accessibility overlay.

## What is in place

- The consent and age step uses real tick boxes and labelled fields; nothing is ticked for you.
- A trainer video whose spoken cues Simon has written out has captions. A movement recorded as a trainer keeps its
  sound only when those captions were made; otherwise its video has no sound.
- The result screen shows a caption under the video with the fixed cue for the moment you are looking at, on by default, with a switch. It is not always the sentence the voice speaks.
- The looping clip on the landing page can be paused, and does not play on its own when your device asks for reduced
  motion.
- An AI model phrases some sentences of your feedback. Where the result shows one in a row, it carries the label "Worded by AI". A coaching line without the label is fixed text; second opinions and answers carry their own label. A result with any labelled line shows a note saying so. If that model cannot answer, the sentence is filled in from fixed text and carries no label. Your score is never written by AI.
- Spoken feedback uses your browser's own voice to read the feedback sentences, and that includes the sentences the model worded. The voice does not say they are AI.

## Known gaps

- The 3D views are not yet checked against WCAG 2.2 AA; the fault list beside them carries the same findings.
- No independent audit against that standard has been done yet. Our own checks so far are automated axe-core runs and keyboard
  tests on sign-in, recording and uploading, and the results. So Simon is partially conformant: some parts may not
  fully meet the standard.

## Contact

If something does not work for you, write to [support@simon.live](mailto:support@simon.live). We try to answer within 5 working days. For anything else, write to
[hello@simon.live](mailto:hello@simon.live).
