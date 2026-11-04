<!--
Drafting notes (removed before the page is served, part7/legal_pages.py _COMMENT).
FORM: reference entry. Reader: a person deciding whether to send a video, or checking what happened to one.
Source: the code at lane/ph-integrate 91accecf, as the prod switches leave it (part7/prod_mode.py, part7/keys.py
OPERATOR_MODEL_KEYS refused in prod, part7/byok_route.py byok_only, part7/licence_gates.py phrasing template).
docs/legal/data-flow-inventory.md names the file behind each fact.
Retention: the data lane's contract (lane/phf-data 8b2350f2), used as given; the Modal token, kept takes and session rows
from the code at 91accecf (part7/modal_creds.py IDLE_TTL_S, part7/history_store.py, part7/identity.py).
Spoken words: the caption producer runs in the operator's Modal workspace in prod (part7/narration_own.py,
deploy/serverless/part2_app.py faster-whisper, docs/specs/serverless-compute.md AC-SC15).
Children and age marks: lane phf-minors (privacy PM-B1, PM-B2, PM-B3, PM-R1, PM-R5): part7/trainer_publish.py,
part7/share_routes.py, part7/challenge_routes.py, part7/notes_routes.py, part7/consent_record.py, part7/identity.py.
Operator acceptance, 3 November 2026: no lawyer reviewed this page. The operator accepted it without one, and the review line
was removed as the record of that acceptance. Names come from part7/legal_pages.py TOKENS.
Lawful bases: GDPR Articles 6(1)(a), (b), (c), (f), 7(3) and 9(2)(a), read at https://gdpr-info.eu/. Consent is used for the body
measurements even where they may not count as special category data, because the consent step already asks for it.
Providers and transfers: https://resend.com/legal/dpa, https://www.cloudflare.com/cloudflare-customer-dpa/,
https://www.cloudflare.com/trust-hub/gdpr/, https://modal.com/legal/dpa. Hosting: a Hetzner server in the EU and Cloudflare R2
in the EU for backups, relayed by the orchestrator on 3 November 2026; this replaces the no outside host decision of claude-template issue 414.
Gateway logs: firm/prod/prod_gateway.py. Backups: decided target and count relayed by the orchestrator on 3 November 2026.
R2: https://developers.cloudflare.com/r2/reference/data-location/ (jurisdiction fixed at bucket creation),
https://developers.cloudflare.com/r2/buckets/bucket-locks/ and https://www.cloudflare.com/cloudflare-customer-dpa/ (its Services
are all Cloudflare cloud solutions; it does not name R2, and the Service-Specific Terms were not read).
Backup contents: prod/statetool.py NOT_BACKED_UP (jobs, uploads, uploads-refused, tmp), docs/specs/prod-data.md "Backups". Still not shown by this
code: the daily run, the bucket and the lock (docs/legal/open-items.md).
Complaints: https://www.edpb.europa.eu/about-edpb/about-edpb/members_en, https://www.gov.uk/data-protection,
https://www.naag.org/find-my-ag/. Change notice: the published pattern at https://www.strava.com/legal/privacy and
https://www.alltrails.com/terms.
Compute: docs/specs/serverless-compute.md, operator-paid Modal with bring-your-own-account paused. Modal facts: "Facts from Modal"
in that spec (Volumes in United States storage whatever the region, no erasure deadline, logs 1 day on Starter). The tracker is
local-open in prod (part7/licence_gates.py, AC-SC5). Real Modal runs were made on the app at d5536a5b (docs/prod/serverless-real-take.md); the Modal deletion claim rests on the fake Modal tests.
Meta and Baseten (docs/specs/muse-prod.md, operator decision 2026-11-04): https://dev.meta.ai/legal/terms-of-service (9 October 2026; 4.4 retention, 5.1 no training on Standard Models, 10.1 minimum age, 10.3 monitoring), https://dev.meta.ai/legal/geographic-use-policy (12 October 2026, Standard Models),
https://www.facebook.com/legal/terms/Meta-Global-Processor-Terms (20 March 2026), https://www.baseten.co/terms-and-conditions/. Whether these pages meet MGPT 2.2 is open for a lawyer (docs/legal/open-items.md).
The consent step and the Me page still name the person's own Modal account (docs/legal/open-items.md).
The prod start check (lane compute, part7/legal_drafts.py) refuses this page while it holds an operator placeholder or
the review banner. Keep every placeholder on one line in its upper case form so the check finds it.
-->
# Privacy policy

Last updated 4 November 2026.

## Who runs Simon

The service is run by {{COMPANY_NAME}}, a New York limited liability company. {{COMPANY_NAME}} decides how and why your data is used. Write to [privacy@simon.live](mailto:privacy@simon.live) about your data.

## Where Simon is offered

Simon is offered to people in the United States only. It is not offered in the EU, the UK or Illinois. Simon limits access
by network location, which can be wrong, so this limit is not complete. If you are in one of those places, do not use Simon.
No EU or UK representative is appointed, because Simon is not offered there. The rights under "Your rights" stay open to
anyone whose data Simon holds.

## How Simon analyses your video

Simon uses AI to analyse your video. Computer vision models find each person in it, the position of their joints
in 2D and 3D, and a 3D body mesh of each person. These models run on graphics processors in a Modal workspace that
{{COMPANY_NAME}} pays for, and so does the model that writes down the speech of a trainer recording for its captions. You need no Modal account. A 3D model made from a photo or picture is made on the same workspace. Simon's server then compares your movement with the trainer's and works out your score and
faults with fixed rules. Your score is never written by AI. Some sentences of your feedback are phrased by an AI model on Baseten. The result labels one where it shows it in a row and carries a note when the take has any; the voice, when on, speaks them without a label. If that model cannot answer they are filled in from fixed text. Some features also use Meta's AI models, as set out under "What goes to Meta".

## What Simon collects

- **Your video.** The video of each take you record or upload.
- **Your body measurements.** From the video Simon works out where each joint of every person it follows is, frame
  by frame, and builds a 3D body mesh of each of them. The joints include points on the face (nose, eyes, ears) and the wrists,
  and the mesh covers the whole body, head, face and hands included. This is biometric data. See
  [Biometric data and retention](biometric).
- **The sound of a trainer recording.** When you allow the microphone, the recording of a movement keeps its sound.
  The movement Simon makes from it keeps that sound when captions were made from the speech; otherwise its video has
  no sound. The speech is written down as text with times in that Modal workspace. From it Simon also makes the
  spoken cues: their text and a short voice clip of each.
- **Your answers before the first take.** Your age answer (whether you are an adult) and your answer to each consent point,
  with the version of the text you saw. They are kept in your browser and with each take. The age band is also kept
  with each movement you record, for as long as the movement exists, and on your account when it is not adult.
- **Your email address.** You sign in to make a take. Simon keeps your email address, a session cookie (`s7_sid`)
  and, when you choose, your profile, your kept takes and your share links.
- **A Modal token saved earlier, if any.** Bringing your own Modal account is paused in this version: Simon takes no
  new token and runs nothing on one. A token already saved stays encrypted on its server until it goes, as listed below.
- **Email addresses you invite, and your own if you are invited.** When you make a challenge for "People I choose", Simon
  keeps each address you type with the challenge, whether that person opened it and whether the invite mail was accepted, and
  mails each address one invitation with your display name and the challenge title. If someone invites you, Simon holds your
  address from them, and keeps a scrambled form of it if you use the stop link in the mail, so it never mails you an invite
  again. Only the person who made the challenge sees the addresses on it. A challenge shows names, never email addresses.
- **A scrambled form of your network address**, to slow repeated sign-in tries and floods of requests.
- **Events from the app in your browser**, such as an error or the camera opening, in the server log.
- **Settings in your browser**, such as your chosen mode or language, stored under names starting with `simon.`.

Simon does not use advertising, tracking pixels or third-party analytics.

All of this comes from you and your browser, and the body measurements are worked out from your video. A video can also
show other people, and Simon measures each person it follows. You do not have to give Simon any of this, but without the age
answer, the consent points and sign-in Simon cannot make a take.

## What Simon uses it for

To compare your movement with the trainer's and show where it differs; to keep your takes and history when you ask;
to send you sign-in codes; to mail a challenge invitation when someone you know invites your address; to keep the service running. Simon does not use your body
measurements to identify you, and does not sell your data.

Fixed rules work out your score with no person involved. The score is feedback on a movement, and Simon decides nothing
else about you from it.

Where the GDPR or the UK GDPR applies, the lawful basis for each purpose is:

| Purpose | Lawful basis |
|---|---|
| Analysing your video, measuring your body and comparing your movement with the trainer's | your consent, given point by point in the consent step; explicit consent if the measurements count as special category data |
| Keeping your takes and history when you opt in, and showing a movement to everyone when you leave the box ticked and tick the second box | your consent |
| Signing you in, your account, your share links and the other features you ask for | performing our agreement with you |
| Rate rules, logs, backups and the security of the service | our legitimate interest in keeping the service running and safe |
| Age answers, and the record of copyright removals | a legal obligation where one applies; otherwise our legitimate interest in protecting children and answering complaints |

You can withdraw your consent at any time: delete the take, stop showing the movement, or use Delete my data. This
does not make earlier processing unlawful.

## Who else receives it

| Recipient | What | When |
|---|---|---|
| Modal, which runs the models for Simon | your video, for the AI models that find the people, their joints and their 3D body; those body measurements as the models make them; the sound of a trainer recording, to write its speech as text for the captions; a photo or picture you send to make a 3D model, and the model made from it; a 3D model file you upload, to convert it or add a skeleton, and the model made from it | every take, each 3D model you make from a photo or picture, and each file you upload that needs converting or a skeleton |
| Hetzner, which hosts Simon's server | everything Simon keeps on that server: videos, body measurements, account data | always |
| Everyone using Simon | a movement you recorded as a trainer: its video (with its sound when captions were made), skeleton and animation, and its spoken cues as text and short voice clips | only when "Show this movement to everyone" is ticked (it starts ticked when you record, and you can untick it) and you tick "Nobody in this video is under 18" |
| Resend | your email address, the sign-in code and the notices we mail you about your account | when you sign in, and when a notice about your account is sent |
| Resend | the email address of a person invited to a challenge, with the inviter's display name and the challenge title | when someone invites that address |
| Cloudflare R2 | Simon's backups of account and catalog data, kept takes of people who opted in and 3D models, encrypted first with a key only {{COMPANY_NAME}} holds | each day |
| Cloudflare | every request and answer as it passes, with your network address, an uploaded video included | always |
| Cloudflare Email Routing, then the mailbox that reads Simon's mail | your message and your address | when you write to a simon.live address |

| Baseten, which runs Meta's Muse Spark Open model | the measured fault (which joint, how far off, when), to phrase your feedback | each take |
| Meta Platforms, Inc., through its Model API | see "What goes to Meta" | only as set out there |

No video, frame or sound goes to any other AI service.

Simon's app and its live data run on a Hetzner server in Falkenstein, Germany, and its backups are in Cloudflare R2 in the European Union.

The full list with the countries and safeguards is at [Who processes your data](sub-processors).
Modal, Resend, Cloudflare, Baseten and Meta Platforms, Inc. are companies in the United States. A transfer of personal data to them from the EU, the
UK or Switzerland relies on the standard contractual clauses in that company's data processing addendum. Resend and
Cloudflare also say they follow the EU-US Data Privacy Framework and its UK extension. To get a copy of those clauses, write
to [privacy@simon.live](mailto:privacy@simon.live).

## What goes to Meta

| Feature | What goes | When |
|---|---|---|
| Key frames of a trainer recording | a smaller, silent copy of the video (SAM 3.1 tracks the person, Muse Spark 1.3 names the poses) | when you record a movement, only if you ticked the Meta box and its age statement |
| Second opinion | your take's video and the trainer's video (Muse Spark) | with each take, only if you ticked the Meta box and its age statement, and that trainer did too |
| Ask about a take | the measurements of that take, as text, and your question (Muse Wonder) | when you ask, for a take you chose to keep |
| Ask about my takes, Compare, patterns, recaps | the measurements of your kept takes, as text, and your question (Muse Spark); the trainer's spoken cues as text, only if that trainer ticked the Meta box and its age statement; up to 5 short clips, and the trainer's clip if that trainer ticked the Meta box and its age statement, only if you turned on "Let Muse Spark watch my takes" | when you press it |
| Progress reel | the measurements of your takes and up to 5 kept clips (Muse Spark) | when you press it, with video allowed |
| You, doing it right | nothing at present: this feature is switched off, so no frame of your video is sent for it | not now; this row changes before the feature is switched on |

The first two rows, which send video while a take or a recording is made, send nothing to Meta unless you tick the Meta box and also tick the statement beside it that everyone who appears in the video is an adult, as defined under "Children" below. Meta's terms set a minimum age for you and the people you send. Simon takes your word for it and cannot check it. The tick belongs to your account: it is cleared when you sign out or another account signs in on the same browser, and Simon's server ignores a tick made for another account.

Video can show your face and body and everyone else in the picture, and Simon treats what it shows as biometric data. A trainer recording is cropped to one person only when you chose one and the crop worked.

Meta's terms say that for these models Meta acts as Simon's service provider and does not use your content to train its models. They say Meta keeps what it receives as needed: to provide the service, to meet the law, when its systems flag a possible policy breach, and for security, safety and abuse review. They also let Meta review use by automated or human means. They give no time limit, so Simon cannot tell you when Meta deletes a copy, and Delete my data does not reach it.

Simon asks Meta to delete each uploaded clip when the call ends, and clips for reports are also set to expire after one hour. **If a run is stopped at its time limit before it finishes, its clip stays at Meta, with no date for its removal.** This is a known gap that Simon has not yet closed.

Meta's terms do not name where it processes this data. Baseten's terms say its services under a zero data retention posture do not save inference inputs or outputs after processing; Simon has not confirmed that this posture applies to its account.

## How long it is kept

| Data | Kept |
|---|---|
| The recording as uploaded, and the take's files (the clip, 3D joint positions, the trainer's skeleton and animation, the analysis) | 7 days, or at once when you delete the take or your data |
| A movement you recorded: its video (with sound only when it has captions), key frames, skeleton and animation | until you delete it, or until your account goes (Delete my data, or the account row below) |
| The captions and spoken cues of a movement (text and voice clips) | as long as the movement; they go sooner, with the sound of its video, when you delete the trainer recording they came from |
| A movement made with no account | as long as a take if never published; 180 days from recording if published |
| Kept takes of a signed-in person who opted in | 90 days, or when you delete them; copies in backups last until those rotate out |
| A friend or crew board | 90 days after its last activity. With Delete my data, your scores leave every board at once; a board you made signed in is deleted if nobody else is on it, and otherwise stays with your name replaced by "A former member" (its title stays). Marking your account 13 to 17 does the same |
| A sponsored board, made by Simon's operator | until the operator removes it; Simon does not delete it for being idle. A deleted take, also one that Simon's clean-up of old takes already removed, takes its entry off any board |
| An address on a challenge's invite list | with the challenge: until the person who made it removes the address or deletes the challenge, when the board is cleared away for inactivity, or at once when the invited person uses Delete my data |
| A scrambled form of an address that used the stop link | kept, so the stop keeps working; it cannot be turned back into the address |
| Account and email address | until you delete your data, or 180 days without signing in |
| Your Modal token | until you remove it, or 24 hours without use |
| Session cookie | 30 days, or two weeks without use |
| Scrambled network address | 3 days (on a board: 3 days after the board was made) |
| Share links | A day, a week or 30 days, as you choose, even once the result itself has gone after a week: a link keeps its own copy of the movement name, score, grade and fixes, with no video and no body data. Anyone holding the link can read that copy, and search engines are told not to list it. It ends early if you stop it, delete the take or delete your data, and is removed a day after it ends |
| Server logs | 14 days. They never hold an account id, only a one-way hash of it, and request lines carry no query text |
| Gateway logs | the same time at most, and less once they reach their size limit. They hold a shortened network address and the path, with no query text or cookies |

While a take is processed, its recording rests in Modal's storage in the United States, whichever region the computers
run in. Simon removes its files from Modal when the job ends or when the take is deleted. A photo or picture sent to make a 3D model takes the same road, and leaves Modal when its job ends or the model is deleted. Modal gives no date by which
removed files are erased from its own systems. Modal keeps its logs for up to 1 day on its Starter plan.

## Your rights

You can delete a take from its result page. Signed in, you can download your data and delete your data from the Me
page, and remove your Modal token there. A movement you record stays private to you unless you leave "Show this movement to
everyone" ticked and tick the second box beside it. A movement already saved keeps its setting. Delete my data overwrites your rows and clears the database journal at once. Copies stay inside the
encrypted backups until those rotate out. Backups hold account and catalog data, kept takes of people who opted in and
3D models. They do not hold recent takes or uploads, so a restore from a backup loses recent takes. Simon makes a
backup each day and keeps the newest 14 off host and fewer on this host, so a deleted record can stay in a backup for up
to two weeks. A lock stops any backup being deleted during its first week. For anything else, or to object,
restrict or correct, write to [privacy@simon.live](mailto:privacy@simon.live). You may complain to the data protection authority where you live or work
(in the EU and the EEA, [the list of authorities](https://www.edpb.europa.eu/about-edpb/about-edpb/members_en); in the UK,
the [Information Commissioner's Office](https://ico.org.uk/global/contact-us/contact-us-public/)) or, in the US, to
[your state's attorney general](https://www.naag.org/find-my-ag/). Simon does not sell or share your data for advertising.
Global Privacy Control: Simon sells nothing and shares nothing for advertising, so the signal has no sale to stop.
Simon treats it as a no to optional sharing and usage events. When your browser sends it, a movement you record
stays private unless "Show this movement to everyone" is ticked for it (it starts unticked then) and you tick the second box beside it, and the app sends the server log only its
error reports, not events such as the camera opening.

## Washington and other state laws

Your body measurements and how you move, which can include your gait, may count as consumer health data under Washington's law. This policy and
[Biometric data and retention](biometric) are Simon's consumer health data privacy policy, and the sections above say what is
collected, why, from where, what is shared and with whom. You can ask Simon to confirm what it holds, give you access and
the list of who received your data, or delete it, and you can withdraw your consent. Write to [privacy@simon.live](mailto:privacy@simon.live). Simon answers
within 45 days, and tells you within that time if it needs a second period of the same length. If Simon refuses, write
again to appeal: Simon answers in writing within 45 days and, if it still refuses, tells you how to complain to the attorney
general. Simon handles the same requests the same way wherever you live in the United States.

The consent step asks for your consent to measure your body before it does so. Sending this data to the companies that run
parts of the service is necessary for the take you ask for: each handles it for Simon as a processor, under the data processing
terms of its agreement with {{COMPANY_NAME}}. Simon shares it with anyone else only with your separate consent, which is the "Show this
movement to everyone" box, which you see before you record and can untick, with your own tick of the second box beside it. You can withdraw by stopping the showing.

Rehab mode is the part of Simon closest to health. Simon asks no health question and gives no medical advice. Choosing Rehab
slows the pace and marks the take as a rehab take. When you keep that take, Simon also stores, in the take's own folder, the number
of repetitions, the peak angle of each measure, the tempo and the follower's joints (no picture), and shows them on a progress
sheet. They go when you delete the take or your data. A rehab take is never put into the across-my-movements report or sent
for a Muse fix. You can share the progress sheet by link, which is a separate step you take; the link and its stored copy go
when you delete the takes or your data.

If a security breach reaches your data, Simon tells you as [Biometric data and retention](biometric) explains.

## Children

Simon is for people 18 or older. Before the first take it asks for your month and year of birth, and in that
browser nobody who gives a younger age can record or upload. Signed in, that answer is kept on your account, so the
account cannot record or upload from any browser. Simon does not check the answer. A movement is shown to everyone only
when the person who recorded it says everyone in its video is an adult.

## If Simon passes to a successor

We may pass the service, these terms and your data to a successor that takes over Simon. We post a notice on this page
at least a month before. The same protections stay in place, and your data is used in the same way.

## Changes

When the words of the consent step change, the app asks for your consent again before the next take.
We post a changed policy on this page, with the date it applies, at least a month before that date, unless a law
requires it sooner.
