# Shot list: Simon submission video (first cut)

Form: shot list. Picture and words are bound per numbered shot, so the editor and the voice can work at different hours. Voice-over text is `demo/script.json`; durations are `demo/build-report.json`. Total 2:24, 1920x1080. Captions are burned from `demo/captions.srt`. The positioning is a capability: one teacher records a movement once, anyone follows it, and sees in 3D where their copy differs. Meta models named: SAM 3.1, SAM 3D Body (DINOv3), Muse Spark.

Source tags: UI = recorded from the real app by `demo/capture.mjs` (segment name in brackets); CARD = `demo/cards.mjs`; STOCK = Pexels or Part 2 clip; JOB = job `5277380db1e1`.

| # | In | Picture | On-screen text | Voice-over | Number and its source |
|---|---|---|---|---|---|
| 1 | 0:00 | STOCK: Part 2 overlay of tracked dancers, vertical, left. CARD hook right. | "Learn any movement from one recording." | "Learn any movement from a single recording." | none |
| 2 | 0:06 | STOCK: two followers (Pexels 8026937, 4224405) side by side. CARD problem. | "You follow a video. Nobody tells you what your copy got wrong." | "You follow a video, and nobody tells you what your copy got wrong." | none |
| 3 | 0:13 | The catalog entry's recorded take, 4:3, left. UI [catalog] phone right: list, Fitness filter. | "The teacher's recording"; "Recorded once. It joins the catalog." | "One teacher records a movement once. That recording is all Simon needs." | none |
| 4 | 0:22 | UI [watch] phone: trainer video plays, 3D figure dragged around, Side and Top views. | "Open it. Turn it to any angle." | "It becomes a 3D movement that anyone can open, and turn to any angle." | 3D |
| 5 | 0:33 | JOB follower clip left. UI [follow] phone: upload, trim screen. | "Anyone follows it." plus the job id | "Anyone can follow it. They film their own copy on a phone." | job id, README table |
| 6 | 0:42 | JOB frames of the take as a timelapse, CARD stage list, a running seconds counter and "sped up x17". | stage seconds; "Total 206.7 s, 3 min 27 s" | "Now the wait. The analysis took 3 minutes 27 seconds on the GPU. Here it is, sped up." | 206.7 s, 201.8 s, 0.3 s, 4.5 s from `part7.log`; x17 = 206.7 / 12 |
| 7 | 0:54 | CARD tech: video in, SAM 3.1 tracking (Meta Model API), Muse Spark 1.3 sections, SAM 3D Body pose (GPU), skeleton, compare, Muse Spark phrasing, score. | "One pipeline, built on Meta models" | "Under the hood, SAM 3.1 tracks the person. Muse Spark finds the sections of the movement. SAM 3D Body, built on DINOv3, lifts the pose into 3D. Then Simon compares the two skeletons, and Muse Spark puts the differences into plain words." | 3.1, 1.3 |
| 7b | 1:12 | UI [mesh]: the mesh demo page (lane/rubric-mesh `f3ed547`), SAM 3D Body meshes of trainer and follower on Pexels 6326808 and 8026937, slow rotation. CARD mesh. | "SAM 3D Body: full body meshes, trainer and you"; "A demo page on two stock clips. It is not in the result screen yet." | "Here is SAM 3D Body at work on two stock clips." | fault times 1.0 s and 1.5 s from `web/mesh-demo/faults.json` |
| 8 | 1:20 | UI [result] phone: score card. CARD reveal. | "77/100", grade C chip, "Where the copy differs, in 3D." | "The result: 77 out of 100, grade C." | 77, C from `job.json` |
| 9 | 1:19 | UI [result] phone: the Trainer vs You 3D view, dragged. CARD compare. | "Your copy, over the teacher's. Blue is the teacher. Green is you." | "The 3D view lays the copy over the teacher, so you can turn it and see exactly where the two differ." | none |
| 10 | 1:31 | UI [result] phone: "What to work on", the first cue tapped. CARD tap. | "At 0.9 s, Keep your chest up" | "And the cue is timed. Keep your chest up, at 0.9 seconds." | 0.9 s from `analysis.json` |
| 11 | 1:39 | UI [result] phone: "Replay worst moment", moments list. CARD shape. | "Shape or timing?" | "Simon tells shape from timing, and replays your worst moment on a loop." | none |
| 12 | 1:48 | STOCK: Part 2 overlay of a yoga class, with CARD close. | "Dance, Rehab, Fitness. One capability. Any movement a teacher can show." | "Dance, rehab or fitness: one capability for any movement a teacher can show." | none |
| 13 | 1:58 | CARD end. | Meta models; before the window and in it (first commits 2026-10-26); stand-in footage; clip credits | "This is Simon, built on Meta's SAM 3.1, SAM 3D Body and Muse Spark. The code was written in the hackathon window. This cut uses stock clips and one recorded take as stand-ins for real people." | 2026-10-26, 7 repositories, Pexels ids: `demo/facts.json` |

## Left out on purpose

- A second attempt that scores higher: no such job exists.
- The Record screen with a camera: it needs a live camera, and the test pattern must never appear.
- Challenge, crew and brand cards: off the main arc.

## Re-capture list once the UI lanes land

Shots 3, 4, 5, 8, 9, 10 and 11 are UI captures, and the card colours of shot 9 follow the 3D legend. After the result-screen, catalog and dark-theme changes: `demo/build.sh --recapture`, then look at the six frames in `demos/rubric/140/` again.

## Release 12 cut (final)

Total 2:33. Shots 3 to 5 and 8 to 11 are recorded from the release 12 UI (dark theme). Changes from the first cut: shot 8 shows the score ring, 9 the 3D compare with a white teacher and a lime you, 10 Reference vs You, "What to work on next" and a "Hear this line" tap, 11 the shape and timing breakdown and the replay, and the new shot 11b the export button until its clip is ready and the Meta models card (VO: "A clip to share is one tap away, and a card shows which Meta models made each step."). Shot 13's voice-over ends "The footage is one real, cleared take plus stock clips." Shot 7b stays the labelled demo page.
