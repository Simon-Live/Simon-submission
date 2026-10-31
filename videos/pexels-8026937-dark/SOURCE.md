# pexels-8026937-dark

- Clip title (as fetched): A Man Exercising at Home · Free Stock Video
- Title source: pexels.com clip page URL slug (the clip page itself answers a Cloudflare challenge)
- Page URL: https://www.pexels.com/video/a-man-exercising-at-home-8026937/
- Download URL: https://videos.pexels.com/video-files/8026937/8026937-uhd_1440_2732_25fps.mp4
- Licence: Pexels License (https://www.pexels.com/license/)
- Author: not stated on the page
- Page access: clip page answered HTTP 403 (Cloudflare challenge) to curl and to Chromium; title read from the page URL slug, author not read
- Downloaded (UTC): 2026-10-31T17:09:08Z
- Original file name: pexels-8026937-clip.mp4
- Original size: recorded on generation bytes
- Original resolution: 570x1080
- Original frame rate: 25.0 fps
- Original duration: 12.0 s
- original_sha256: 7630463a4ef1103b02062359939da1a800f10579533f8e79bc5fb584f9e2e29c
- Time range used: 0.0 s to 12.0 s
- Clip: 570x1080, 25.0 fps, 12.0 s
- clip_sha256: pending first local build with make videos
- Role: degraded
- Angle: three-quarter
- Note: Deliberately darkened copy of the frozen good follower. Part 5 must independently establish a major impact; the recipe does not decide impact.

Used by Simon Part 7 as a test video; deliberately degraded using the recipe below.

- Derived from trimmed clip: pexels-8026937
- Source clip sha256: 7630463a4ef1103b02062359939da1a800f10579533f8e79bc5fb584f9e2e29c
- Intended signal: dark
- ffmpeg filter: `eq=brightness=-0.35:gamma=0.6`
- Encoder: libx264, threads 1, preset veryfast, crf 18, yuv420p; audio and metadata removed.
- Quality impact: determined only by Part 5; no major result is presumed from picture appearance.
