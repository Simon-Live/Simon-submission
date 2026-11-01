# Changelog

## 2026-10-31 offline takes

A camera take is saved on the device as soon as it is trimmed, sent by itself when the app is back, and deleted once the
server accepts the job (202). Adds `#/pending`, a header banner, `Idempotency-Key` on uploads and the three job routes, and
an in-tab Try again. Additive; no shared file or other part is affected. Known limits: the app has to be open to send,
Safari may evict stored data, saved takes expire after 7 days. Details: [2026-10-31-offline-takes.md](2026-10-31-offline-takes.md).

## 2026-10-31 video quality feedback (Part 7)

Tips before recording (dark, backlit, washed out, blurry, camera moving, busy background), a "Tips for your next take"
section, a cap line and a "Video quality" board chip on the result, picker hints from Part 2, Part 7's own minor tips
when it writes the analysis, and a check-7 gate on major quality codes and the 59 cap. Additive: with no `quality` in
the shared files every screen is unchanged. Details: [2026-10-31-video-quality.md](2026-10-31-video-quality.md).

## 2026-10-31 product batch

Nine requirements (R1 to R9): coaching tied to the moment, worst-moment replay, the standard-body note,
tempo versus shape, challenges with a share card, crew leaderboards, sponsored challenges, a section
ladder and three modes. Status: built, in final acceptance. What was added per requirement, its spec,
tests, how to try it and its limits: [README.md](README.md).
