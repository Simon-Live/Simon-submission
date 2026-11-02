#!/usr/bin/env bash
# image3d-cu128: the venv `part2 image3d` runs SAM 3D Objects (and the TRELLIS fallback) in. RTX 5090, compute
# capability 12.0, no system nvcc. Idempotent. Writes nothing inside the repository, everything under
# ~/.local/state/simon-part-2/:
#   venv     venvs/image3d-cu128 (CPython 3.11: spconv has no cp312 wheel), torch 2.8.0+cu128
#   source   src/sam-3d-objects, src/pytorch3d, src/TRELLIS, src/utils3d at pinned commits. No CUDA compiler is
#            needed: spconv and xformers are wheels, pytorch3d is a CPU build, gsplat is import-only
#   weights  image3d-cache/hf (jetjodh/sam-3d-objects and microsoft/TRELLIS-image-large at pinned revisions,
#            downloaded by part2/image3d_worker.py on first use), image3d-cache/torch (DINOv2), image3d-cache/u2net (rembg)
# Not installed on purpose: nvdiffrast and diff-gaussian-rasterization (the models' own texture bake uses them; both
# carry non-commercial licences, ADR-0005). part2/image3d_worker.py bakes the texture itself.
# Not shared with the gpu-cu128 venv (SAM 3D Body, CPython 3.12): the two never import each other.
# Spec: docs/specs/image3d.md. Usage: bash envs/image3d-cu128/setup.sh
set -euo pipefail

STATE="$HOME/.local/state/simon-part-2"
VENV="$STATE/venvs/image3d-cu128"
PY="$VENV/bin/python"
SRC="$STATE/src"
export PATH="$HOME/.local/bin:$PATH"
SAM3DO_COMMIT=f91db411c50efee93d8db7aeb323885650f6f722
PYTORCH3D_COMMIT=75ebeeaea0908c5527e7b1e305fbc7681382db47
GSPLAT_COMMIT=2323de5905d5e90e035f792fe65bad0fedd413e7
MOGE_COMMIT=a8c37341bc0325ca99b9d57981cc3bb2bd3e255b
TRELLIS_COMMIT=193e0502b5cb3eb5997ec457d5340e95d09b158e
UTILS3D_COMMIT=9a4eb15e4021b67b12c460c7057d642626897ec8
TORCH_INDEX="https://download.pytorch.org/whl/cu128"
say() { printf 'setup-image3d: %s\n' "$*"; }
die() { printf 'setup-image3d: %s\n' "$*" >&2; exit 1; }
command -v uv >/dev/null || die "uv not found (expected in ~/.local/bin)"
command -v git >/dev/null || die "git not found"
mkdir -p "$SRC"

# 1. venv: torch, xformers (sparse attention), spconv (sparse convolution), and what the models and the bake import
[ -x "$PY" ] || uv venv -q --managed-python --python 3.11 "$VENV"
uv pip install -q --python "$PY" --index-url "$TORCH_INDEX" torch==2.8.0 torchvision==0.23.0
uv pip install -q --python "$PY" --no-deps --index-url "$TORCH_INDEX" xformers==0.0.32.post2
uv pip install -q --python "$PY" pillow imageio imageio-ffmpeg tqdm easydict opencv-python-headless scipy rembg \
  onnxruntime trimesh open3d xatlas pyvista pymeshfix igraph transformers "numpy<2.3" spconv-cu120 safetensors \
  huggingface_hub pytest omegaconf hydra-core==1.3.2 loguru einops timm roma scikit-image optree rootutils \
  jsonpickle astor fvcore iopath matplotlib seaborn lightning "moge @ git+https://github.com/microsoft/MoGe.git@$MOGE_COMMIT"

# 2. sources at pinned commits
clone() {  # name url commit
  [ -d "$SRC/$1/.git" ] || git clone -q --recurse-submodules "$2" "$SRC/$1"
  git -C "$SRC/$1" checkout -q "$3"
  git -C "$SRC/$1" submodule update -q --init --recursive
}
clone sam-3d-objects https://github.com/facebookresearch/sam-3d-objects "$SAM3DO_COMMIT"
clone pytorch3d https://github.com/facebookresearch/pytorch3d.git "$PYTORCH3D_COMMIT"
clone TRELLIS https://github.com/microsoft/TRELLIS "$TRELLIS_COMMIT"
clone utils3d https://github.com/EasternJournalist/utils3d.git "$UTILS3D_COMMIT"
uv pip install -q --python "$PY" --no-deps "$SRC/utils3d"
# pytorch3d: a CPU-only build is enough (SAM 3D Objects imports its transforms and structures)
"$PY" -I -c "import pytorch3d" 2>/dev/null || FORCE_CUDA=0 uv pip install -q --python "$PY" --no-build-isolation --no-deps "$SRC/pytorch3d"
# gsplat: import only (its layout renderer is not used); skip the CUDA build
"$PY" -I -c "import gsplat" 2>/dev/null || BUILD_NO_CUDA=1 uv pip install -q --python "$PY" --no-deps "gsplat @ git+https://github.com/nerfstudio-project/gsplat.git@$GSPLAT_COMMIT"

"$PY" -I -c "import torch, spconv, xformers, utils3d, xatlas, pyvista, scipy, pytorch3d, gsplat, moge; print('image3d-cu128 ok', torch.__version__)"
say "ready. Weights download on first use: jetjodh/sam-3d-objects at f29e43c (SAM License, about 12 GiB), and for the fallback microsoft/TRELLIS-image-large (MIT)."
