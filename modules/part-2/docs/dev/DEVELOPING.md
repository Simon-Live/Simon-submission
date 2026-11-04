# Developing Part 2

How to set up, run, check and debug Part 2 from a fresh clone on any Linux host. The product view (inputs,
outputs, current numbers, licences) is in `README.md`; the file contract is in `CONTRACT.md`; the specs and
ADRs behind each choice are in `docs/design/`.

Paths that start with `~` are under the home directory of whoever runs the command. Nothing here depends on
a particular machine.

## 1. Prerequisites

| Need | For | Notes |
|---|---|---|
| Python 3.11 or later, `uv` | everything | `make setup` runs `uv sync`. `setup-gpu` expects `uv` in `~/.local/bin` or on `PATH`. |
| `ffmpeg` and `ffprobe` on `PATH` | `part2 frames`, `part2 run`, the tests that decode video | Those tests are skipped without them. |
| `git` | `setup-gpu`, stamps | The stamp and `provenance.part2_commit` read the commit. |
| An NVIDIA GPU with CUDA, `nvidia-smi` | the `gpu` backend, `local-sam31`, `local-open` | The gpu-cu128 profile was built and measured on an RTX 5090 (compute capability 12.0); its setup asserts `sm_120` kernels. About 10 GiB of GPU memory per job. |
| Node | `tests/test_viewer_js.py` | Skipped when absent. |

Nothing else is needed to run the tests, `make check-2` or `make check-2-contract`: they read committed
outputs and need no GPU, no key and no network.

## 2. Setup from a fresh clone

```
git clone https://github.com/Simon-Live/Simon-submission.git
cd Simon-submission/modules/part-2
make setup          # uv sync: the base venv in .venv (numpy, pillow, imageio-ffmpeg, pytest)
make test           # the whole suite, no GPU needed
make check-2        # the done-check on the committed scored outputs; exit 0
```

Then add the profile you need.

### CPU backend

```
make setup-cpu      # uv sync, then envs/cpu/requirements.txt into .venv (torch 2.15.0+cpu, rtmlib, onnxruntime)
uv run part2 run --mode single --input clip.mp4 --out out/clip --backend cpu [--lifter bones-prior|fixed-bones|motionbert]
```

The CPU backend runs RTMPose-x 2D through rtmlib on ONNX Runtime, then a lifter: `bones-prior` by default (the
lowest mean joint distance of the three; none passes), `fixed-bones` or `motionbert`. Its 3D is approximate and
fails its own bar with all three lifters (see Known issues). The default is `DEFAULT` in
`part2/lifters/__init__.py`, with the measurements beside it, and `bones-prior` is in that file's registry like the
other two. The rtmlib models download into `$TORCH_HOME`, else
`$XDG_CACHE_HOME/rtmlib`, else `~/.cache/rtmlib`. MotionBERT weights download from `walterzhu/MotionBERT` at a
pinned revision with no login, are checked against pinned SHA-256 digests and live under `~/.cache`
(`MOTIONBERT_DIR` overrides).

The backend `cpu-sam3db` is the `gpu` backend's SAM 3D Body run on the CPU device. It meets the 3D bar (mean joint
distance 0.0363 m, bone CV 0.0408; the reference is the refined `single`, the `cpu-sam3db` run is unrefined) at
31.74 s per frame on 8 threads plus 23.7 s model load (the 2026-10-31 run), and 46.95 s per frame plus 23.4 s model load under host load (the committed set, regenerated 2026-11-01), so it is chosen by name only: the default without CUDA stays
`cpu`. It needs the gpu-cu128 profile and its python, no GPU (`CUDA_VISIBLE_DEVICES=`), and writes the foot points.
`make outputs BACKEND=cpu-sam3db` makes `cpu-sam3db-single`; `make check-2-cpu CPU_MODE=cpu-sam3db-single` scores it.

The 31.74 s per frame (2026-10-31) and the 46.95 s per frame (2026-11-01, under host load) were measured with the threads limited and the cores pinned, and nothing in Part 2 sets either:
torch takes every core it sees. The invocation that gives the figures (about an hour on a quiet host, one and a half hours under load on 2026-11-01, for the 111 frames):

```
OMP_NUM_THREADS=8 MKL_NUM_THREADS=8 OPENBLAS_NUM_THREADS=8 taskset -c 0-7 nice -n 19 make outputs BACKEND=cpu-sam3db
```

Pinning the cores with `taskset` without limiting the threads made the first run thrash, so use the two together.
`provenance.timing.threads` in the run's `pose3d.json` records the thread count torch used. `timing.load_s` is the
model load that run paid for; a request served from an already loaded model (the second request of a warm worker, or
any request after the worker's preload) says `load_s` 0.0 and `warm` true.

### GPU profile gpu-cu128 (local GPU)

```
make setup-gpu      # bash envs/gpu-cu128/setup.sh; idempotent; writes nothing inside the repo
make smoke-gpu      # one fixture frame on the GPU: device, CUDA capability, peak memory, seconds
```

`envs/gpu-cu128/setup.sh` does, in order:

1. Creates the venv `~/.local/state/simon-part-2/venvs/gpu-cu128` (uv-managed CPython 3.12), installs
   `torch==2.8.0+cu128` and `torchvision==0.23.0+cu128` from the PyTorch cu128 index and the rest of
   `envs/gpu-cu128/requirements.txt` under `constraints.txt`.
2. Builds detectron2 (for the ViTDet person detector) without CUDA ops, inside a 45 minute timebox
   (`DETECTRON2_TIMEOUT`). On failure it writes the marker `detectron2-build-failed-<commit>` in the venv and
   records the `rtmlib-yolox` detector instead; delete the marker to retry the build. Log:
   `~/.local/state/simon-part-2/logs/detectron2-build.log`.
3. Installs MoGe-2, then the tracker packages (rtmlib, onnxruntime, SAM 2.1 and the SAM 3 code) with
   `--no-deps` so they keep this profile's torch and numpy.
4. Clones `facebookresearch/sam-3d-body` into `~/.local/state/simon-part-2/src/sam-3d-body` at the commit
   pinned in `k8s/setup_env.sh` (that file is the one source of the pins).
5. Installs this repo into the venv, editable.
6. Downloads the weights and checks them (below).
7. Asserts CUDA and `sm_120`, imports every model, and writes the profile record
   `<venv>/part2-profile.json` (versions, device, detector, model paths and digests). The backend reads model
   paths from that record; `SAM3D_REPO` and `SAM3D_CKPT` override it.

Run the GPU backend from that venv:

```
~/.local/state/simon-part-2/venvs/gpu-cu128/bin/part2 run --mode single --input clip.mp4 --out out/clip
```

`make outputs` and `make stock-outputs` pick that interpreter on their own when it exists.

### Model weights and where they land

| Model | Downloaded from | Lands in | Checked |
|---|---|---|---|
| SAM 3D Body (`model.ckpt`, `assets/mhr_model.pt`) | Hugging Face `jetjodh/sam-3d-body-dinov3` at a pinned revision, no login | Hugging Face cache (`~/.cache/huggingface`) | `envs/gpu-cu128/check_weights.py` compares each file with `OFFICIAL_SHA256` in `k8s/infer_one.py`; exit 1 names the file that differs |
| MoGe-2 (`model.pt`) | `Ruicheng/moge-2-vitl-normal` at a pinned revision | Hugging Face cache | digest recorded in the profile |
| ViTDet Cascade Mask R-CNN ViT-H | `dl.fbaipublicfiles.com` (URL in `setup.sh`) | iopath cache | digest recorded in the profile |
| SAM 2.1 hiera-large (`local-open`) | `facebook/sam2.1-hiera-large` | Hugging Face cache | |
| SAM 3.1 (`local-sam31`) | `facebook/sam3.1`, gated: needs `HF_TOKEN` and approved access | Hugging Face cache | |
| RTMPose-x, YOLOX (rtmlib) | rtmlib's own URLs | `$TORCH_HOME` or `~/.cache/rtmlib` | |
| MotionBERT-Lite | `walterzhu/MotionBERT` at a pinned revision | under `~/.cache` (`MOTIONBERT_DIR`) | pinned SHA-256 |
| COCO val2017 images (`coco-single`) | the COCO URL | `~/.cache/simon-part-2/coco` (`PART2_COCO_DIR`) | `uv run python -m part2.coco_set images` checks each sha256 |
| Pexels stock clips | Pexels | `~/.cache/simon-part-2/stock` (`PART2_STOCK_DIR`) | sha256 written into each take's `SOURCE.md` |

### Team profile: torch 2.5.1 on the k3s pod and on HPC

The team's original profile is separate and unchanged: base image
`pytorch/pytorch:2.5.1-cuda12.4-cudnn9-devel`, pins in `k8s/requirements-gpu.txt` and
`k8s/constraints-gpu.txt`, git commits in `k8s/setup_env.sh`. It runs in one pod on the k3s cluster
(`make gpu-up`, `gpu-setup`, `gpu-smoke`, `gpu-outputs`, `gpu-down`; see `k8s/README.md`) or on the HPC cluster
(`make hpc-setup`, `hpc-run`, `hpc-outputs`, `hpc-status`; see `hpc/README.md`). Its outputs carry a
version 1 stamp, which `make check-2` reports as stale (Debugging, below).

## 3. Keys

Part 2 reads two keys, both by name only. No key is needed for the tests or the done-checks.

| Key | Used by | Read how |
|---|---|---|
| `MODEL_API_KEY` | the `api-sam31` tracker (SAM 3.1 on the Meta Model API) | `part2/keys.py`: the key file first, then the environment variable of the same name |
| `HF_TOKEN` | the `local-sam31` tracker (gated `facebook/sam3.1` weights) | `part2/keys.py`: the key file first, then the environment variable |
| `BASETEN_API_KEY` | nothing in Part 2 | `part2/keys.py` refuses it (`ValueError`, not a key Part 2 reads). ADR-0002 records why the Baseten option was rejected. |

The key file lives in the key directory: `PART2_KEY_DIR`, else the default in `part2/keys.py`. The file is
named after its variable (`MODEL_API_KEY`, `HF_TOKEN`). A file counts only when the directory is mode 700 and
the file is a non-empty regular file of mode 600; otherwise the variable is used. A key is read at the moment
of the call, inside the tracker adapter, and is never printed, logged or written to an output. `local-sam31`
runs its child process with both key variables removed from the environment.

```
mkdir -p -m 700 "$PART2_KEY_DIR"
# put the value in "$PART2_KEY_DIR/MODEL_API_KEY", then:
chmod 600 "$PART2_KEY_DIR/MODEL_API_KEY"
```

Or export the variable in the shell that runs `part2`.

Spend for `api-sam31` goes through a budget guard with a JSONL ledger (`META_SPEND_LEDGER`, default
`~/.simon/meta_spend.jsonl`). `META_BUDGET_USD` sets the cap: unset means $25 for a `part2 run`, `0` refuses
every paid call. `part2.meta_api` also reads these variables from a `.env` at the repo root (git-ignored).
The staging app sets its own ledger (`~/.simon/meta_spend_staging.jsonl`), $10 in total and $0.50 per job
(`PART2_JOB_LEDGER`, `PART2_JOB_BUDGET_USD`).

## 4. Command line

All commands run as `uv run part2 ...` in the base venv or as `<gpu venv>/bin/part2 ...`;
`python -m part2 ...` is the same.

```
part2 frames --input clip.mp4 --out out/clip/frames [--fps 30]
part2 run --mode single --input clip.mp4 --out out/clip [--fps 10] [--backend gpu|cpu|cpu-sam3db] [--mirrored]
part2 run --mode single --input clip.mp4 --out out/clip --backend gpu --refine focal,kp2d-fit
part2 run --mode multi --input class.mp4 --out out/class [--tracker NAME] [--tracker-order scored|bulk]
part2 track --input class.mp4 --out out/pick --fps 10 [--tracker NAME]
part2 run --mode multi --input class.mp4 --out out/two --fps 10 --tracks out/pick/tracks.json --ids 0,3
part2 serve-worker --socket /tmp/part2.sock [--backend gpu]
part2 run --worker /tmp/part2.sock --mode single --input clip.mp4 --out out/clip
part2 contract [--json] [--schema pose3d]
part2 doctor out/clip/pose3d.json [--for part3|part5|part6] [--json]
part2 demo viewer --run out/clip [--embed]
part2 stock [--clip pexels-5034562] [--backend gpu]
part2 annotate joints --frames out/clip/frames --out labels_2d.json
part2 check
```

| Option or variable | Effect |
|---|---|
| `--backend`, `PART2_BACKEND` | `gpu`, `cpu` or `cpu-sam3db`; the flag wins. With neither: `gpu` when the interpreter sees CUDA, else `cpu`; `cpu-sam3db` only by name. `make run-single` runs in `.venv`, which has no CUDA torch, so it uses `cpu`. |
| `--lifter`, `PART2_LIFTER` | cpu backend only: `bones-prior` (default), `fixed-bones` or `motionbert`. |
| `--tracker`, `PART2_TRACKER` | multi mode and `track`: `api-sam31`, `local-sam31`, `local-open`, `bytetrack`. A named tracker never falls back; without its key it exits 1 and names the key and `--tracker local-open`. |
| `--tracker-order` | with no tracker named: `bulk` (default) or `scored` (below). |
| `--refine` | single mode: comma-separated rungs from `part2/refine/`; `focal,kp2d-fit` makes the scored outputs; default `none`. |
| `--tracks FILE` | multi mode: reuse that `tracks.json`; no tracker runs and the ids stay. Pass the same `--input` and `--fps` that made it. |
| `--ids A,B` | multi mode: 3D for those people only. An unknown id is exit 1 and is named. |
| `--worker SOCKET` | send the job to a running `serve-worker`; with none listening, run in this process and say so on stderr. |
| `--mirrored` | the saved video is a mirror image (front camera); writes `"mirrored": true`. |
| `PART2_PROGRESS=1` | prints `progress <stage> <done> <total>` lines on stdout. |

Exit codes for `run` and `track`: 0 written, 1 input, contract or runtime error, 2 bad option (unknown backend,
lifter or tracker, `--tracks` or `--ids` with `--mode single`, `--refine` with `--mode multi`).

### Trackers and their order

With no tracker named, `part2 run --mode multi` and `part2 track` walk an order and record in `provenance`
which tracker ran and why any step was skipped.

| Order | Steps | Used by |
|---|---|---|
| `scored` | `api-sam31`, then `local-open` | `make outputs`, the done-check |
| `bulk` (default) | `local-sam31` once `fixtures/output/parity/sam31.json` exists, then `api-sam31` within its cap, then `local-open` | `part2 run` and `part2 track` with no tracker, the staging app |

A step is skipped only for `no_key`, `budget`, `no_parity` or `no_env` (its packages are not installed); any
other error fails the run. `bytetrack` is never in an order; name it to use it.

### Warm worker

Loading the models costs about 20 to 35 s per `part2 run`. `part2 serve-worker --socket PATH` loads the
backend once and serves `run` and `track` requests on a Unix socket (mode 600), one at a time, with up to 8
waiting. It prints `part2 worker (<backend>) listening on <path>` when ready. Only `PART2_*` variables cross the
socket, relative paths resolve against the client's directory, and a request that raises leaves the worker up.
A worker that dies mid-request gives the client exit 1, never a silent re-run. Restart the worker after a
`git pull`: code and models load once. Protocol: `CONTRACT.md`, "Warm worker".

`part2 serve-worker --mode track --socket PATH` is the warm path for `part2 track --tracker local-sam31`: a
separate process that builds SAM 3.1 once on its own thread, loads no 3D model and serves only that command (exit 2
for anything else). A warm call took 13.1 to 15.0 s against 38.7 s cold on a 10 s clip (2026-11-01). The live
cold-versus-warm check is `tests/test_warm_track_gpu.py --input CLIP --work DIR`, run with the gpu-cu128 python.
Protocol, memory and failures: `CONTRACT.md`, "Warm track worker".

### Make targets

| Target | What it does |
|---|---|
| `make setup`, `setup-cpu`, `setup-gpu` | the base venv, the CPU extras, the gpu-cu128 profile |
| `make test` | `uv run pytest -q` |
| `make smoke-gpu` | one frame on the GPU |
| `make run-single INPUT=clip.mp4`, `run-multi` | `part2 run` into `out/<clip>/` |
| `make outputs [BACKEND=gpu] [TRACKER=] [MODES=] [REFINE=] [SCORED=out]` | remakes the scored outputs with a stamp each (GPU host) |
| `make outputs BACKEND=cpu [LIFTER=]` | remakes `cpu-single` (lifter `bones-prior` unless `LIFTER=` names another) |
| `make outputs BACKEND=cpu-sam3db` | remakes `cpu-sam3db-single` (about an hour on a quiet host, one and a half hours under load on 2026-11-01; with 8 threads on 8 pinned cores; the invocation is in section 2) |
| `make stock-outputs [CLIP=pexels-5034562]` | the stock takes for Part 5 |
| `make check-2`, `check-2-contract`, `check-2-cpu` | the done-checks (below) |
| `make contract-check`, `contract-sync` | compare or refresh the copy of Part 3's schema (needs a `gh` login with access to Part 3) |
| `make gpu-*`, `hpc-*` | the team profile on the k3s pod and on HPC |

The staging app: `uv run python -m part2.server --host 127.0.0.1 --port 8722 --base /` serves the browse,
contract and run pages. Its jobs run `part2 run` with `PART2_JOB_PYTHON`, else the gpu-cu128 python when it
exists, else the current interpreter; job files go under `PART2_JOBS_DIR`.

## 5. Done-checks

| Check | Gates | Needs | Exit |
|---|---|---|---|
| `make check-2` | the definition of done: `one_person` (20 labelled frames, each within 5% of body height), `one_person_coco` (20 COCO images, same rule) and `multi_person` (every person covered on at least 95% of labelled frames, at most one ID swap per minute, each with a pose3d stream). Each scored dir must carry a fresh `part2.stamp/2`. `multi_person_local_open` and `cpu_backend_3d` are reported and never gated. | nothing (scores `fixtures/output/scored/`); `SCORED=out` scores `out/<mode>/` | 0 only when the top-level `pass` is true |
| `make check-2-contract` | every committed output against its schema in `contracts/`, Part 3's consumer schema in `contracts/consumers/` and `doctor --for part3` | nothing | 0 when every file passes |
| `make check-2-cpu` | the CPU backend's 3D bar alone: mean joint distance to the GPU output at most 0.10 m, mean bone-length CV at most 0.05; scores `cpu-single`, or `cpu-sam3db-single` with `CPU_MODE=cpu-sam3db-single` | nothing | 0 pass, 1 fail, 2 an output missing; through make, a non-zero code shows as `Error <n>` and make exits 2 |
| `make contract-check` | Part 3's published schema still equals the copy | `gh` access to Part 3 | 0 same, 1 changed |

All three local checks print a metrics JSON. On a fresh clone of this commit, `make check-2` and
`make check-2-contract` exit 0 and `make check-2-cpu` fails as recorded in `README.md`.

## 6. Debugging

### `make check-2` fails

Read the `status` of the failing block in the JSON. The stamp messages, from `part2/stamp.py`:

| Status | Meaning | Fix |
|---|---|---|
| `missing output <path>; run make outputs` | a scored file is absent | `make outputs` for that mode |
| `<dir> is stale: <what> changed since <created>; run make outputs` | the code the run imported, the input frames or the profile's lock file changed after the outputs were made | revert the change or remake the outputs on a GPU host; the JSON `outputs` block lists the changed files |
| `<path> does not match its stamp (edited after make outputs)` | an output file was edited by hand | restore it from git or remake it |
| `stamp v1 from HPC; run make outputs` | outputs from the team profile scripts | remake with `make outputs` |
| `<dir> was tracked by <x>, not <y>` | `multi_person` needs the outputs of the scored tracker | `make outputs MODES=class` |

Editing `part2/schema.py`, `contract.py`, `doctor.py`, `keys.py`, `provenance.py` or `__init__.py` never stales
an output: those files do not change a number. Any other `part2` module the run imported does.

### Outputs look wrong

- `python -m part2 doctor <file> --for part3` names the kind, the version and what a consumer would reject.
- `provenance` in `pose3d.json` and `tracks.json` names the backend, tracker, lifter, refine rungs, models
  with their weight digests, the Part 2 commit and any tracker fallback (`fallback_from`, `fallback_reason`).
- `stamp.json` in a scored dir adds the sha256 of the imported code, the input frames, the lock file and
  each output.
- A single run with `--refine` keeps the unrefined 3D as `body3d-unrefined.json` beside `body3d.json`.
- `part2 demo viewer --run out/clip` draws the frames beside the rotatable skeleton.

### Common errors

| Message | Cause |
|---|---|
| `tracker <name> needs the key file <KEY> (or the <KEY> variable); use --tracker local-open` | no usable key file and no variable; check the modes 700 and 600 |
| `tracker <name>: the credential was refused` | the API or Hugging Face answered 401 or 403; for `local-sam31`, the account lacks access to the gated repo |
| `tracker <name>: the spend cap of $<n> is reached (ledger <path>)` | `META_BUDGET_USD` against the ledger |
| `another GPU job is running` | the host GPU lock (`PART2_GPU_LOCK`, default `~/.local/state/simon-part-2/gpu.lock`) stayed held for 600 s; `make outputs`, the SAM trackers, the app's worker and `part2 run` share it |
| `tracker <name> needs <module> (the gpu-cu128 venv for SAM trackers)` | a SAM tracker run outside the GPU venv |
| `--tracks <file> has no entry for frame <n> of this input` | `--input` or `--fps` differ from the `track` run that made the file |
| `unknown person id <n> in --ids` | the id is not in `tracks.json`; the message lists the ids it has |
| `output breaks the contract at <path>` | a writer refused before writing; the path names the field |
| `AssertionError: torch sees no CUDA device` or `... has no sm_120 kernels` (from `setup-gpu`) | no GPU visible, or the torch build does not match the GPU |
| `part2: no worker at <socket>; running in this process` | informational: no worker was listening |

## 7. Tests

```
make test                         # uv run pytest -q: tests/test_*.py
uv run pytest -q tests/test_worker.py tests/test_cli_track.py     # one area
uv run pytest -rs                 # shows each skip and its reason
# the real-torch tests of tests/test_cpu_sam3db.py, which `make test` skips (the base venv has no torch):
CUDA_VISIBLE_DEVICES= PYTHONPATH=.:$HOME/.local/state/simon-part-2/pytest-only \
    ~/.local/state/simon-part-2/venvs/gpu-cu128/bin/python -m pytest -q tests/test_cpu_sam3db.py
```

The last command runs the file on the CPU in the gpu-cu128 venv, where torch is installed (AC-B21 of
`docs/specs/backends-gpu-cpu.md`). That venv has no pytest, so install it once on a path of its own with
`uv pip install --target ~/.local/state/simon-part-2/pytest-only pytest`; `PYTHONPATH` adds it and the repo root.
`CUDA_VISIBLE_DEVICES=` hides the GPU: the test that the mode ends when the block raises skips while a GPU is visible,
because a redirected CUDA move and a real one would look alike.

On the development host at this commit, with `ffmpeg` installed: 1793 passed and 5 skipped, in about 140 s. The
skips are the MotionBERT test (needs `make setup-cpu` and its cached weights), the two real-torch tests of
`tests/test_cpu_sam3db.py` (need torch, see the command above), the staging-script test that needs port 7122 free and
the one that needs Playwright and its Chromium. The tests need no GPU, key or network:
GPU, tracker and API paths run against fakes (`PART2_NVIDIA_SMI` points the GPU guard at a fake `nvidia-smi`,
`PART2_KEY_DIR` at a temp dir). Areas: CLI and `track` (`test_cli.py`, `test_cli_track.py`), the worker
(`test_worker.py`), backends, lifters and refine, trackers and parity, keys, stamps and the check, the contract
and `doctor`, the app (`test_server.py`, `test_jobs.py`, `test_runapi.py`) and the viewer JS.

## 8. Contract and Part 7

`CONTRACT.md` is the reference: every file, field, version and rule, plus the compatibility table. Each file
Part 2 writes has a JSON Schema in `contracts/`. Part 3 reads `pose3d.json` unchanged; Parts 4 and 5 read
Part 3's output.

Part 7 calls Part 2 through the command line:

```
part2 run --mode single --input <take> --out <dir> --fps 10 --backend gpu [--mirrored]
part2 track --input <take> --out <dir> --fps 10 [--tracker <name>]
part2 run --mode multi --input <take> --out <dir2> --fps 10 --backend gpu --tracks <dir>/tracks.json --ids <id>,<id>
```

then runs Part 3 on `<dir>/pose3d.json`. It can add `--worker <socket>` to each command and keep one
`serve-worker` per GPU slot.

## 9. Known issues and limits

- The `cpu` backend's 3D fails its bar with all three lifters (mean distance 0.145 m for `bones-prior`, 0.2656 m
  for `fixed-bones`, 0.2914 m for `motionbert`, against 0.10 m; each against its own reference, see `README.md`).
  Use it for a quick look, not for scoring. `cpu-sam3db` meets the bar (0.0363 m, bone CV 0.0408, reference refined
  and the CPU run unrefined) at 31.74 s per frame on 8 threads on 2026-10-31, and 46.95 s per frame under host load on 2026-11-01 (limited and pinned as in section 2), so it is chosen by name only.
- `local-open` misses people (min coverage 0.111 on the class clip) and is never gated.
- `local-sam31` passed parity with `api-sam31` but is not scored on the labels.
- The one-person margins are thin: the max error on the committed scored sets is 4.884% (one person) and 4.903% (COCO) against a 5% line.
- `conf` is not calibrated: 1.0 inside the image, 0.3 outside.
- Up is the camera's up, so a tilted camera tilts every pose; Part 3 takes up from the body.
- Two GPU runs of the same code differ by up to about 1.3 mm per joint, so remade outputs need a new stamp,
  not a byte compare.
- RTMPose and MotionBERT carry research-only training data; outputs that touch them say so in
  `provenance.licence_notes` (ADR-0005).
- The run page's checks on staging are still in progress (`README.md`).
- One GPU job at a time per host, through the lock.
