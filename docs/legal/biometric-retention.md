<!--
Drafting notes (removed before the page is served). Register LEG-C4; laws such as the Illinois Biometric Information
Privacy Act may apply. Facts come from the code at lane/ph-integrate 91accecf (docs/legal/data-flow-inventory.md).
Public movements: web/trainer-publish.js PUBLISH_TEXT, the opt-in "Show this movement to everyone" (a11y-copy B6).
Retention: the data lane's contract (lane/phf-data 8b2350f2) for movements and accounts; the code at 91accecf for the rest (
part7/config.py RETENTION_DAYS, part7/delete_routes.py drop_movement and remove_entries, part7/history_store.py,
part7/identity.py ACCOUNT_IDLE_S, part7/model_store.py).
Operator acceptance, 3 November 2026: no lawyer reviewed this page. The operator accepted it without one, and the review line
was removed as the record of that acceptance. Names come from part7/legal_pages.py TOKENS.
Destruction rule, the strictest of: Illinois 740 ILCS 14/15(a) (purpose met, or 3 years after the last interaction,
whichever is first; read at https://codes.findlaw.com/il/chapter-740-civil-liabilities/il-st-sect-740-14-15/ because
ilga.gov refused the fetch), Texas Bus. and Com. Code 503.001(c)(3) (within a reasonable time, at most one year after the
purpose expires; read at https://codes.findlaw.com/tx/business-and-commerce-code/bus-com-sect-503-001/ because the state
site gave no statute text) and Washington RCW 19.375.020(4)(b) (no longer than reasonably necessary;
https://app.leg.wa.gov/RCW/default.aspx?cite=19.375.020). Face copy: on in prod by operator decision; paragraph above.
Compute: docs/specs/serverless-compute.md, operator-paid Modal with bring-your-own-account paused; real runs at d5536a5b, deletion claims rest on fake Modal tests.
Backups: prod/statetool.py NOT_BACKED_UP, docs/specs/prod-data.md "Backups". The two weeks depend on the daily backup, which this
code does not show (docs/legal/open-items.md). A take's 7 days hold because jobs and uploads stay out of backups.
The prod start check (lane compute, part7/legal_drafts.py) refuses this page while it holds an operator placeholder or
the review banner. Keep every placeholder on one line in its upper case form so the check finds it.
-->
# Biometric data and retention

Last updated 4 November 2026.

## What Simon measures

From a video of a take, AI models in a Modal workspace that {{COMPANY_NAME}} pays for measure each person Simon follows:

- the position of each joint, frame by frame, in 2D and in 3D, including points on the face (nose, eyes, ears) and the wrists;
- a 3D body mesh: the shape of the whole body, head, face and hands included, and how it moves, which can include your gait.

The laws of states such as Texas may treat these as a record of hand or face geometry, so Simon tells you and asks for your
consent before it captures them, and handles them under the rules on this page.

From a photo you send to make a 3D model, the same AI models in that workspace measure the body shape of the person in it.

When you send one photo and choose to copy a face, hair and clothing colours, Simon first asks who the photo shows: you, or
someone who agreed. It makes a 3D model that carries that face, hair and those colours, on the same Modal workspace. This is
a likeness of a real person, so you need an account and your answer is kept with the model. The photo shows one side, so the
back of the model is a guess. The model is private to you: only you can see it, and only you can delete it. It is kept until
you delete it or your account goes. If Simon cannot fit a skeleton to the clothes, it makes the plain skin-coloured body instead and
tells you. A picture sent as a character or object keeps its colours and textures, so Simon refuses one you say shows a real
person. Simon cannot check that answer, and it keeps the answer with the model.

## Why

Only to compare your movement with the trainer's and show where it differs. Simon never uses these measurements to
identify a person and never sells, leases or trades them. They go to the services listed in the [privacy policy](privacy), for the
same purpose, and to nobody else, with two exceptions you choose. If you tick the Meta box or press a feature that says so, your video, frames or measurements go to Meta as the privacy policy sets out. And when you record a movement as a trainer, leave
"Show this movement to everyone" ticked (it starts ticked, and you can untick it) and tick "Nobody in this video is under 18", everyone using Simon can watch that movement
(with its sound when captions were made), read and hear its spoken cues (text and short clips of your voice), and follow its skeleton and animation.

## Your written release

Before the first take, the consent step asks you to agree, point by point, that Simon may measure your body shape and
movement. Your answer is kept with the version of its text and with each take. Without it, Simon does not record or
analyse. Sending video to Meta has its own box, which you may leave unticked and still use Simon.

## Other people in your video

Simon measures each person it follows. The consent step asks you to confirm that everyone in the video agreed, and Simon does
not ask them itself. If you are in a video and did not agree, write to [privacy@simon.live](mailto:privacy@simon.live).

## How long it is kept, and when it is destroyed

| What | Destroyed |
|---|---|
| Joint positions, meshes and analysis of a take | 7 days after the take, or when you delete it |
| The same for a kept take of a signed-in person who opted in | 90 days after the take, or when you delete it, then from backups as below |
| The skeleton and animation of a movement you recorded as a trainer | when you delete the movement, or when your account goes (Delete my data, or 180 days without signing in), then from backups as below |
| The captions and voice clips of that movement | with the movement, or sooner, with the sound of its video, when you delete the trainer recording they came from, then from backups as below |
| A 3D model made from a photo | when you delete it, or with your account, then from backups as below |
| Everything of an account | when you delete your data, or 180 days without use, then from backups as below |

While a take is processed, its video rests in Modal's storage in the United States, whichever region the computers run
in. Simon removes it from Modal when the job ends or when the take is deleted. A photo or picture sent to make a 3D model
takes the same road, and leaves Modal when its job ends or the model is deleted. Modal gives no date by which removed files
are erased from its own systems.

Meta keeps what it receives as needed and its terms give no time limit, so the dates on this page do not cover copies at Meta. Simon asks Meta to delete each uploaded clip when the call ends, but a run stopped at its time limit leaves its clip at Meta, with no date for its removal. Simon's three year limit below applies to what Simon holds.

Simon destroys biometric data once the purpose above has been met, and never later than 3 years after your last use
of Simon. A delete does not reach encrypted backups at once. Kept takes, movements, 3D models and account data stay in
each backup made before the delete until it rotates out. Simon keeps the newest 14 backups, one a day, so those copies go
within two weeks of a delete, as the [privacy policy](privacy) explains. Recent takes and uploads are never in a backup.

At least once a year {{COMPANY_NAME}} checks for biometric data that is due for deletion.

## Security

Simon stores and sends these measurements with at least the care it gives its other confidential data. Visitors reach it over
HTTPS, and backups are encrypted before they leave Simon's server. If an incident may have exposed this data, {{COMPANY_NAME}}
works out what happened and what was reached, stops it, and tells the people affected as soon as it can and within 30 days after discovering the breach, as New York's
breach law requires. It also tells the New York Attorney General, Department of State and State Police, and any other
authority a breach notice law names.

## Contact

[privacy@simon.live](mailto:privacy@simon.live)
