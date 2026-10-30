# Simon Part 2: Images to 3D models


Part of **Simon** → hub repo: https://github.com/moalborati/simon (scope and the other parts live there; this repo is only this part).
This repo is **only** Simon Part 2. It is a black box: it reads its input files and writes its output files, and knows nothing about the other parts. Keep it that way: that isolation is what lets agents work here with a small context.

Simon in one line (all you need): a trainer records an expected movement once; a follower performs it to camera; the follower's 3D movement is compared against the expected one and the differences are reported in plain words. This part is one step of that.

Source task: moalborati/simon issue #56. Scope source: `docs/MINI-APPS.md` in moalborati/simon (Part 2).

## Input

Video frames. Two modes: a one-person recording (trainer or single follower) and a multi-person class recording.

## Output

`pose3d.json` per tracked person; multi-person mode also writes `tracks.json` (stable ID, box, mask, confidence per person per frame).

## Shared-file context (only what this part touches)

Canonical 17 joints (subject's left/right): nose, left_eye, right_eye, left_ear, right_ear, left_shoulder, right_shoulder, left_elbow, right_elbow, left_wrist, right_wrist, left_hip, right_hip, left_knee, right_knee, left_ankle, right_ankle. Coordinate frame: origin at the hip midpoint per frame; x = subject's left (horizontal), y = world up, z = anterior (x × y); metres and degrees. `tracks.json` shape: `{frames: [{frame, people: [{id, bbox, mask_rle, confidence}]}]}`. `pose3d.json` shape: `{frames: [{frame, t_ms, people: [{id, joints: {<joint>: {x, y, z, conf}}}]}]}`.

What each field promises downstream, and the check that keeps it in sync with Part 3: `CONTRACT.md`.

## Frontier model

SAM 3D Body (3D); SAM 3.1 (multi-person tracking)

## Definition of done

One-person: on 20 hand-clicked frames including side views, 3D joints reproject within 5% of body height. Multi-person: class clip with ≥5 people, each tracked on ≥95% of frames with ≤1 ID swap per minute, each with a pose3d stream.

Done-check: `make check-2` prints a metrics JSON and exits 0 only when every threshold passes. Write the check as part of this work; until it exists, the stub in the Makefile fails honestly.

## Demos

- **Isolated:** A photo beside its rotatable 3D skeleton; a class clip with coloured, stable per-person skeletons.
- **Integrated:** Parts 3–5 consume this repo's `pose3d.json` unchanged.

The demo files and what each shows: `demos/README.md`.

## Rules

- Work only in this repo. Do not copy or import another part's code; consume other parts only through the shared files above, using fixtures until they exist.
- Every run of the done-check goes through `make check-2`.
- Fixtures of your inputs live in `fixtures/input/`; ship a fixture of your output so the next part can start.

## Development

```
make setup                         # uv sync (Python ≥ 3.11, ffmpeg on PATH)
make test                          # pytest
uv run part2 frames --input clip.mp4 --out out/clip/frames [--fps 30]
make run-single INPUT=clip.mp4     # also run-multi; writes out/<clip>/
```

`part2 frames` writes numbered frames plus `frames.json` (`frame`, `t_ms`, `file`); those `frame`/`t_ms` values are the ones in `pose3d.json` and `tracks.json`. GPU inference runs on the k3s cluster: see `k8s/README.md`. Tasks and progress: issues #2–#16, checklist #17, team chat #18.

## Develop and debug

- `docs/dev/DEVELOPING.md`: setup from a fresh clone (CPU and GPU profiles, weights, keys), the commands, the
  done-checks, debugging, the tests, the contract with Part 7 and known limits.
- `docs/design/README.md`: the specs and ADRs behind each choice.

## Backends

`part2 run --backend gpu|cpu` picks the 3D backend. The flag wins over `PART2_BACKEND`. With neither, the backend is `gpu` when CUDA is available in the running interpreter, else `cpu`. `make run-single` runs in the uv venv, which has no CUDA build of torch, so there it uses `cpu`. Both backends write the same files.

```
make setup-gpu     # venv ~/.local/state/simon-part-2/venvs/gpu-cu128 (torch 2.8.0+cu128); weights checked against k8s/infer_one.py
make smoke-gpu     # one fixture frame on the GPU: device, CUDA capability, peak memory, seconds
make setup-cpu     # CPU extras into the uv venv (envs/cpu/requirements.txt)

~/.local/state/simon-part-2/venvs/gpu-cu128/bin/part2 run --mode single --input clip.mp4 --out out/clip
uv run part2 run --mode single --input clip.mp4 --out out/clip --backend cpu [--lifter fixed-bones|motionbert]
```

| Backend | What runs | Needs |
|---|---|---|
| `gpu` | SAM 3D Body (weights from the `jetjodh/sam-3d-body-dinov3` mirror), ViTDet person boxes, MoGe-2 field of view | CUDA and the gpu-cu128 profile; built and measured on an RTX 5090 (compute capability 12.0) |
| `cpu` | RTMPose-x 2D through rtmlib on ONNX Runtime, then a lifter: `fixed-bones` (default) or `motionbert` (`--lifter`, `PART2_LIFTER`) | any CPU |

The team's torch 2.5.1 profile for the k3s pod and HPC (`k8s/`, `hpc/`) is separate and unchanged. One GPU inference runs at a time on a host: `make outputs` and the app share the lock `~/.local/state/simon-part-2/gpu.lock`.

**The CPU backend's 3D is approximate.** Its 3D bar sits outside the definition of done: on the one-person fixture, the mean joint distance to the GPU output must be at most 0.10 m and the mean bone-length CV at most 0.05. Measured over the fixture's 111 frames:

| Lifter | Mean distance | p95 distance | Bone CV mean | Bone CV max | Bar |
|---|---|---|---|---|---|
| `fixed-bones` (default) | 0.2682 m | 0.8112 m | 0.0117 | 0.0571 | fail |
| `motionbert` | 0.2914 m | 0.5987 m | 0.1400 | 0.4028 | fail |

Neither lifter passes, so the default is the one with the lower mean distance. The GPU output is itself a model output, not ground truth. The CPU backend's 2D reprojection error on the labelled frames of the one-person fixture is mean 3.956% and max 5.721% of body height, with one frame over 5%. `make check-2-cpu` prints the 3D block alone and exits 0 on a pass, 1 on a fail and 2 when an output is missing.

## Trackers

`part2 run --mode multi --tracker <name>` picks the tracker; `PART2_TRACKER` comes second. A tracker named this way never falls back: without its key it exits 1 and names the key file and the open alternative.

| Name | What runs | Key | On the class clip |
|---|---|---|---|
| `api-sam31` | SAM 3.1 through the Meta Model API, prompt "person" | `MODEL_API_KEY` | the scored tracker: every person covered on every labelled frame, no ID swap |
| `local-sam31` | SAM 3.1 weights (`facebook/sam3.1`, gated) on the local GPU, prompt "person" | `HF_TOKEN` | parity with `api-sam31` passed: same id count, matched masks at IoU 0.971 to 0.991, coverage equal; not scored on the labels |
| `local-open` | SAM 2.1 hiera-large, prompted with rtmlib person boxes and re-prompted every 2 s | none | min coverage 0.111, mean 0.873: fail; reported beside the scored tracker, never gated |
| `bytetrack` | ByteTrack association over rtmlib person boxes; the mask is the filled box | none | coverage 1.0, 0 swaps (tracking only, scored without pose3d streams) |

With no tracker named, `part2 run` walks an order (`--tracker-order scored|bulk`) and records in `provenance` which tracker ran and why any step was skipped:

| Order | Steps | Used by |
|---|---|---|
| `scored` | `api-sam31`, then `local-open` | `make outputs` and the done-check |
| `bulk` | `local-sam31` once its parity pass is committed (`fixtures/output/parity/sam31.json`), then `api-sam31` within its cap, then `local-open` | `part2 run` with no tracker named, the staging app |

A step is skipped only when its key file is missing (`no_key`), its budget is spent (`budget`), the parity pass is absent (`no_parity`) or its packages are not installed (`no_env`). Any other error fails the run.

Keys are read from files at the moment of the call, never printed, logged or stored: `MODEL_API_KEY` and `HF_TOKEN` in `~/.config/firm/operator-keys/` (override the directory with `PART2_KEY_DIR`), each file mode 600. An environment variable of the same name is the second channel; the file wins when both exist.

Spend caps for `api-sam31`: `META_BUDGET_USD` caps the ledger `~/.simon/meta_spend.jsonl` (unset or 0 refuses every paid call). The staging app keeps its own ledger (`~/.simon/meta_spend_staging.jsonl`), capped at $10 in total and $0.50 per job; past either cap the job runs the next tracker in the bulk order and its result says so.

## Reproducible outputs and current numbers

`make check-2` scores outputs committed under `fixtures/output/scored/`, so a clean clone needs no GPU, no key and no network. `make outputs` remakes them on a host with the GPU profile.

```
make outputs                  # gpu: single, class, class-local-open, coco-single (TRACKER=, MODES=, SCORED= optional)
make outputs BACKEND=cpu      # cpu-single (LIFTER= optional)
make check-2                  # scores fixtures/output/scored/; SCORED=out scores out/<mode>/ instead
make check-2-cpu              # the CPU 3D block alone
```

`coco-single` reads its images from a local cache; `uv run python -m part2.coco_set images` downloads them and checks each sha256. Each scored dir holds a `stamp.json` (`part2.stamp/2`) that names the backend, tracker, lifter, refinement rungs and models with their weight digests, and the sha256 of the code the run imported, of the input frames, of the environment lock and of each output file. `make check-2` fails a dir whose code, frames or lock changed since it was made, or whose files were edited, and says which. Two GPU runs of the same code on one host differed by at most 1.273 mm per joint (mean 0.057 mm). The dirs and their files: `fixtures/output/README.md`.

Results on the committed outputs (the gpu dirs were made on an RTX 5090):

| Block | Outputs | Result |
|---|---|---|
| `one_person` | `single`: gpu, refinement `focal` then `kp2d-fit` | 0 of 20 labelled frames over 5% of body height (mean 3.839%, p95 4.816%, max 4.877% at frame 29): pass |
| `one_person_coco` | `coco-single`: gpu, one photo run per COCO val2017 image, same refinement | 0 of 20 images over (mean 2.018%, p95 4.092%, max 4.904% on image 229553): pass |
| `multi_person` | `class`: `api-sam31` | 7 people, each covered on all labelled frames, no ID swap, each with a pose3d stream: pass |
| `multi_person_local_open` (never gated) | `class-local-open`: `local-open` | min coverage 0.111, mean 0.873: fail |
| `cpu_backend_3d` (outside the definition of done) | `cpu-single`: `fixed-bones`, against the refined `single` | 0.2656 m, bone CV 0.0117: fail |

`single` and `coco-single` are refined: `make outputs` runs them with `focal` then `kp2d-fit`, `part2 run --mode single --backend gpu --refine focal,kp2d-fit` does the same for one input, and a plain `part2 run` is the unrefined pipeline.

The top-level `pass` needs `one_person`, `one_person_coco` and `multi_person`; on these outputs `make check-2` exits 0 (recorded at `ac242c9`, outputs `f642222`).

Without refinement, SAM 3D Body on this host had 3 seated frames and 1 COCO image over the line (max 5.294% and 5.213%), close to the team's HPC record (3 of 20 over, max 5.29%). Two refinement steps in `part2/refine/` bring both sets under it: `focal` re-runs SAM 3D Body at 0.7 to 2.0 times MoGe-2's focal length and keeps the run that agrees best with RTMPose-x 2D keypoints, then `kp2d-fit` fits each frame to those keypoints while keeping the bone lengths fixed per person. Their parameters were fixed from label-free measures (agreement with RTMPose on unlabelled frames and the dance clip, smoothness, bone length stability) before each scoring, and every scoring is counted. The margins are thin. Thresholds, labels, the body-height rule and the every-frame rule stay as written above.

## Contract

`CONTRACT.md` says what each file promises and which part reads it. Every file Part 2 writes has a JSON Schema in `contracts/`.

```
python -m part2 contract                       # the schemas and the compatibility table (--json; --schema pose3d)
python -m part2 doctor out/clip/pose3d.json    # kind, version and a verdict for Parts 3, 5 and 6 (--for part3 for one)
make check-2-contract                          # every committed output against its schema, Part 3's schema and doctor
```

`doctor` exits 0 when the named consumer accepts (Part 3 without `--for`), 1 when it would reject and 2 when the file is not a Part 2 file. `make check-2-contract` needs no GPU and no network. Part 3's consumer schema is a byte copy in `contracts/consumers/`: `make contract-check` compares it with Part 3's main and `make contract-sync` refreshes it (both need a gh login with access to Part 3).

## Staging app

A standard-library HTTP server (`python -m part2.server --host 127.0.0.1 --port <n> --base /`) serves three pages. Every URL in them is relative, so the app also runs under a path prefix.

- **Browse:** the committed and scored outputs, each frame beside a 3D skeleton you can turn and zoom, with playback, a frame slider and Front, Side and Top views. Class and dance outputs draw every person in their own colour, with a person picker.
- **Contract:** the schemas and the compatibility table from `CONTRACT.md`, with schema downloads.
- **Run:** upload a video, a class clip or a photo, or pick a sample, then choose the backend and the tracker. One worker runs the real `part2 run`. The page shows progress, then the frames beside the 3D skeleton (the class overlay for a class) and downloads of `pose3d.json`, `tracks.json` and `camera.json`, naming the backend and tracker that ran.

Upload limits: a video up to 200 MB and 60 s, sampled at 10 fps (at most 600 frames); a photo up to 20 MB and 8000 px on its longest side. At most 5 jobs wait or run at once, a job stops after 20 minutes, and uploads and results are deleted 24 hours after the job ends. A visitor never names a paid or key-gated tracker: Automatic follows the bulk order, and `local-open` and `bytetrack` can be picked by name. The run page is on main; its checks on staging are still in progress.

## Stock takes for Part 5

`make stock-outputs [CLIP=pexels-5034562]` downloads each Pexels clip into `~/.cache/simon-part-2/stock/`, samples it at 10 fps, runs one-person mode and writes `fixtures/output/stock/pexels-<id>/` with `pose3d.json`, `camera.json` and a `SOURCE.md` (clip, licence, sha256 of the downloaded file, time range, the Part 2 commit that made it). The videos stay out of the repo.

| Take | Angle | Frames |
|---|---|---|
| `pexels-5034562` | side (Part 5's expected take) | 154 |
| `pexels-5034577` | front | 166 |
| `pexels-8837221` | three-quarter | 256 |

All three ran on the gpu backend, and `doctor --for part3` accepts each. The front and three-quarter takes match the side take's mean knee-angle curve per repetition (correlation 0.992 and 0.987), and their deepest knee angle is within 3 degrees of it.

## Models and licences

the team wrote on #46 that non-commercial licences are excluded, because the result is for an app. RTMPose and MotionBERT carry research-only training data, so they sit behind the backend and lifter registries, never as the GPU default, with a caveat in `provenance.licence_notes` of the outputs they touch. Both were accepted with that caveat on 2026-10-28, and a teammate's objection still overrides. Each licence below was re-read from the source in its row on 2026-10-29. A source that refused is marked with its HTTP status; every other source answered HTTP 200. The table records what the texts say and is not a legal opinion.

| Model or data | Used for | Licence, as read | Source |
|---|---|---|---|
| SAM 3D Body (`jetjodh/sam-3d-body-dinov3` mirror at `1f026b2`: `model.ckpt`, `assets/mhr_model.pt`) | `gpu` backend 3D | SAM License (last updated November 19, 2025): use, copy, modify and distribute, with no non-commercial term; redistribution only under the same licence with a copy of it; no activity subject to ITAR and no end use barred by trade controls (military or warfare, nuclear, espionage, guns or illegal weapons). Outputs appear only in the warranty disclaimer and the litigation clause. | mirror `LICENSE`, identical to `facebookresearch/sam-3d-body` `LICENSE`; Hugging Face card metadata `license: other`, `sam-license` |
| SAM 2.1 hiera-large (`facebook/sam2.1-hiera-large`) | `local-open` tracker | Apache-2.0 | Hugging Face card metadata `license: apache-2.0`; `facebookresearch/sam2` `LICENSE` |
| SAM 3 and SAM 3.1 weights (`facebook/sam3`; `facebook/sam3.1` at `daa6319`, `sam3.1_multiplex.pt`) | `local-sam31` tracker | Gated with manual approval; card metadata `license: other`; the access form asks the user to accept "the terms of the license". The weights' own `LICENSE` was not read. The SAM 3 code that loads them, which also carries the SAM 3.1 code, is under the SAM License of November 19, 2025: the SAM 3D Body text without its patent clause. | Hugging Face API for both repos; their `LICENSE` files: HTTP 401 without a token; `facebookresearch/sam3` `LICENSE` and `README.md` |
| SAM 3.1 on the Meta Model API (`sam-3.1`) | `api-sam31` tracker | Meta Model API Terms of Service (last updated October 9, 2026): the user owns Inputs and Outputs (4.1); the services are meant for commercial use (1); SAM 3.1 is a Standard Model (Model Designation and Geographic Use Policy, last updated October 12, 2026), and Meta does not use content sent to Standard Services to train its models (5.1); no access for third parties, API key included, other than end users through your own product (10); Outputs may not train a competing model (10); access is for a limited period (15.1). | `dev.meta.ai/legal/terms-of-service` (reached from `llama.developer.meta.com/legal/terms-of-service`); `dev.meta.ai/legal/geographic-use-policy` |
| ViTDet Cascade Mask R-CNN ViT-H (`model_final_f05665.pkl`) through detectron2 | `gpu` backend person boxes | detectron2 code: Apache-2.0. The ViTDet project page names no licence for its weights. detectron2's `MODEL_ZOO.md` puts the models it lists under CC BY-SA 3.0; this checkpoint is listed on the ViTDet page, not there. | `facebookresearch/detectron2` `LICENSE`, `README.md`, `MODEL_ZOO.md`, `projects/ViTDet/README.md` |
| MoGe-2 (`Ruicheng/moge-2-vitl-normal` at `cb0e8bb`) | `gpu` backend field of view | MIT, except the DINOv2 code in `moge/model/modules/dinov2`, which is Apache-2.0 (both texts in one `LICENSE` file); model card metadata `license: mit` | `microsoft/MoGe` `LICENSE` and `README.md`; Hugging Face API |
| RTMPose-x and its YOLOX person detector, through rtmlib | `cpu` backend 2D; person boxes for `local-open` and `bytetrack` | rtmlib and MMPose code: Apache-2.0. The RTMPose page names no separate weight licence. The weights are trained on body7 (AI Challenger, MS COCO, CrowdPose, MPII, sub-JHMDB, Halpe, PoseTrack18), which, as recorded on #46, includes datasets with research-only terms (the caveat above, written into `cpu` backend outputs). | `Tau-J/rtmlib` `LICENSE`; `open-mmlab/mmpose` `LICENSE` and `projects/rtmpose/README.md` |
| MotionBERT-Lite (`walterzhu/MotionBERT` at `370a919`, `FT_MB_lite_MB_ft_h36m_global_lite`) | `motionbert` lifter | Apache-2.0, the same `LICENSE` in the code repo and the weights repo. The checkpoint name marks a fine-tune on Human3.6M, whose free licence is "limited to academic use only", with commercial licences on request from its authors (the caveat above). | `Walter0807/MotionBERT` `LICENSE`; Hugging Face `LICENSE`; Human3.6M licence page `vision.imar.ro/human3.6m/eula.php` |
| ByteTrack (re-implemented in `part2/trackers/bytetrack.py`) | `bytetrack` tracker | MIT, copyright 2021 Yifu Zhang | `ifzhang/ByteTrack` `LICENSE` |
| COCO val2017 person keypoints | second one-person scored set | Annotations: CC BY 4.0, COCO Consortium. Images: the Consortium does not own them, and their use must follow the Flickr Terms of Use. The selection keeps licence ids 4 to 8 (commercial use allowed); the kept images are Attribution (14), Attribution-ShareAlike (4) and Attribution-NoDerivs (2). The image bytes stay out of the repo. | `cocodataset.org/dataset/termsofuse.htm`; per image `fixtures/input/coco/SOURCE.md`; the rule in `fixtures/input/coco/SELECTION.md` |
| Pexels clips: class fixture 8480627 (Yan Krukau), one-person fixture 6019962, dance 8956007, stock takes 5034562, 5034577 and 8837221 | scored inputs, dance demo, stock takes | Pexels licence. The fixture source files (clips downloaded 2026-10-27) record it as free to use with no attribution required; attribution is given anyway. The licence text was not re-read. | `pexels.com/license` and the clip pages: HTTP 403 (Cloudflare challenge); per clip `fixtures/input/class/SOURCE.md`, `fixtures/input/single/SOURCE.md`, `fixtures/output/stock/*/SOURCE.md` |
| Squat clip by FitnessScape (Wikimedia Commons) | `fixtures/output/single/`, `demos/viewer-squat.html` | CC BY 3.0 | Commons API file metadata (`LicenseShortName`, `UsageTerms`) |
