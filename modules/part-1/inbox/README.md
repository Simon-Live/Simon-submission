# Part 1 labelled videos (not in this repo)

Part 1's labelled check (`make check-1`) reads three trainer videos into this folder:
`13749263_3840_2160_24fps.mp4`, `15079883_1080_1920_30fps.mp4` and `7480487-uhd_2160_3840_25fps.mp4`, with their labels
in `../fixtures/labels/`. In Part 1's own repo they were Git LFS objects. Their source and licence are not recorded,
so they are not part of this public repo (ADR-0008). The demo and the rest of the suite do not need them; `make check-1`
also needs paid Meta Model API calls.
