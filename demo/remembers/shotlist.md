# Shot list: "Simon remembers" (segment for TICKET-140)

Status: **written, runs once sign-in is live.** It needs TICKET-176 (a mail provider key in the operator keys folder) and TICKET-177 (the app on its own origin). Until both are live, nothing here can be recorded from the real app. No take, date, score or token count on this page is real until `demo/remembers/facts.json` is filled from TICKET-184's saved report; every `{slot}` below is read from that file at build time.

Form: shot list. Picture and words are bound per numbered shot, so the editor and the voice can work at different hours. One continuous shot of the real UI at 412x915, one student, one movement. Length is set by TICKET-140's owner (the whole video stays under 3 minutes); the shots below total about 40 seconds.

Source tags: UI = recorded from the real app by `demo/remembers/capture.mjs`; CARD = `demo/cards.mjs`. Takes are labelled on screen as stock clips or as the one cleared real take; dates are the recorded ones.

| # | In | Picture | On-screen text | Voice-over | Number and its source |
|---|---|---|---|---|---|
| R1 | 0:00 | UI phone: Me page, signed in, `me-takes` listing the student's takes of one movement. CARD label under it: "Stock clip" or "Cleared real take" per row. | "Your takes of {movement}"; each row's date | "Simon keeps your takes, if you sign in and ask it to." | takes `{takes}`, dates `{dates}`: facts.json, `GET api/me/takes` |
| R2 | 0:06 | UI phone: tap "Your takes over time"; the page with a score per take. | "{takes} takes, {first_date} to {last_date}" | "Here is one movement, practised {takes} times." | `{takes}`, `{first_date}`, `{last_date}`: report |
| R3 | 0:12 | UI phone: the consent line, tap to agree, tap "Compare my takes". The status line shows. | "Compare my takes"; the status line | "Tap compare, and Simon watches your earlier takes next to the teacher's." | none |
| R4 | 0:19 | UI phone: the report appears. The summary, then the first trend card. | the summary line; the first trend | "It tells you what changed between takes, in plain words." | the trend text: report `trends[0]` |
| R5 | 0:27 | UI phone: tap the first cite chip. The player opens on that earlier take, at that second. | "Take {cite_take}, {cite_s} s" | "Every claim points at a take and a second. Tap it, and you see the moment." | `{cite_take}`, `{cite_s}`: report `trends[0].cites[0]` |
| R6 | 0:34 | UI phone: back to the report, the context meter in view. | "{input_tokens} of 1,048,576 tokens, {cached_tokens} cached; watched {clips} of {takes} takes; {checked} claims checked" | "Behind it is a long-context call to Muse Spark. It read the measurements of every take, and watched {clips} of them." | `{input_tokens}`, `{cached_tokens}`, `{clips}`, `{checked}`: report `usage`, guard count |
| R7 | 0:41 | CARD close. | "Muse Spark, long context. Stock clips and one cleared real take stand in for a student's practice." | "Simon remembers your takes, and shows you the proof." | none |

## Rules for this segment

- Every number on screen equals the saved report of TICKET-184 (AC-2 there). A slot that is `null` in `facts.json` stops the build; nothing is typed in by hand.
- No take is described as a different day than its recorded creation time. The word "weeks" appears only if the recorded dates span weeks.
- Stock-clip takes carry the label "Stock clip" in frame (R1 to R5). The cleared real take (job `5277380db1e1`) is labelled as such.
- The observations in the report are shown with their label "model's opinion, not scored" if they appear in frame.
- The voice-over and captions avoid the words coach, coaching, medical and injury, and pass `firm/check-em-dash.sh`.

## Hand-off to TICKET-140

The segment clip is `<out-dir>/remembers.webm` and its caption lines are `<out-dir>/captions.srt`, both written by `demo/remembers/capture.mjs` once the slots are filled. TICKET-140's owner adds the segment to `demo/capture.mjs` and runs `demo/build.sh`.
