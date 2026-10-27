#!/bin/bash
# One-time (idempotent) GPU environment for Part 2 on the HPC cluster, in the personal home dir.
#   make hpc-setup        (syncs code, then: sbatch hpc/setup_env.sbatch)
# Layout under ~/simon-part-2: part2/ code, env/ conda env, sam-3d-body/, checkpoints/.
#SBATCH --job-name=simon-setup
#SBATCH --account=student
#SBATCH --partition=gpu
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=02:00:00
#SBATCH --output=%x-%j.out
set -eo pipefail
ROOT="$HOME/simon-part-2"
cd "$ROOT"
REQ="$ROOT/part2/k8s"   # same pins as the k3s pod

SAM3D_COMMIT=b5c765a0d89d789985e186d396315e7590887b94
DETECTRON2_COMMIT=a1ce2f956a1d2212ad672e3c47d53405c2fe4312
MOGE_COMMIT=74fbce054ebed49800de42d0ad0e83495065719a
UTILS3D_MOGE_COMMIT=62f09d58509485564e24d5d9f6aac9ee9ebc0c37

module load Anaconda3/2025.12-2 CUDA/12.6.2 GCC/12.3.0
source "$(conda info --base)/etc/profile.d/conda.sh"
[ -d env ] || conda create -y -q -p "$ROOT/env" python=3.11
conda activate "$ROOT/env"
export PIP_CACHE_DIR="$ROOT/.cache/pip" HF_HOME="$ROOT/.cache/huggingface" TORCH_HOME="$ROOT/.cache/torch"

PIP="pip install -q -c $REQ/constraints-gpu.txt"
python -c "import torch; assert torch.__version__.startswith('2.5.1')" 2>/dev/null || \
  pip install -q torch==2.5.1 torchvision==0.20.1 torchaudio==2.5.1 --index-url https://download.pytorch.org/whl/cu124
$PIP "setuptools<81" wheel numpy==2.1.2
$PIP -r "$REQ/requirements-gpu.txt"
python -c "import detectron2" 2>/dev/null || \
  TORCH_CUDA_ARCH_LIST="7.0" FORCE_CUDA=1 $PIP --no-build-isolation --no-deps \
    "git+https://github.com/facebookresearch/detectron2.git@$DETECTRON2_COMMIT"
$PIP "utils3d_moge @ git+https://github.com/EasternJournalist/utils3d-moge.git@$UTILS3D_MOGE_COMMIT"
$PIP --no-deps "git+https://github.com/microsoft/MoGe.git@$MOGE_COMMIT"

git -C sam-3d-body rev-parse --git-dir >/dev/null 2>&1 || { rm -rf sam-3d-body; git clone -q https://github.com/facebookresearch/sam-3d-body.git; }
git -C sam-3d-body fetch -q --depth 1 origin "$SAM3D_COMMIT" 2>/dev/null || true
git -C sam-3d-body checkout -q "$SAM3D_COMMIT"

# Weights: the public mirror is byte-identical to the gated official repo (no token needed on
# HPC); infer_one.py-style SHA-256 check below rejects anything else.
python - <<'PY'
import hashlib, os
from huggingface_hub import snapshot_download
d = os.path.expanduser("~/simon-part-2/checkpoints/sam-3d-body-dinov3")
want = {"model.ckpt": "b5a2f9d305dd02626b967aa2e86021fba07065df66ce7a7e00ffb9664f150abf",
        "assets/mhr_model.pt": "352e271a6c42729c68554ceaea0c955e866970160c31e35506d782dc0f7377bc"}
if not all(os.path.exists(f"{d}/{n}") for n in want):
    snapshot_download("jetjodh/sam-3d-body-dinov3", local_dir=d)
for n, sha in want.items():
    h = hashlib.sha256()
    with open(f"{d}/{n}", "rb") as f:
        for chunk in iter(lambda: f.read(1 << 24), b""):
            h.update(chunk)
    assert h.hexdigest() == sha, f"{n}: checksum mismatch"
print("weights ok")
PY

pip check | grep -vE "detectron2 .* requires (black|tensorboard)" || true
PYTHONPATH="$ROOT/sam-3d-body" python - <<'PY'
import torch, detectron2, moge
from detectron2.config import LazyConfig  # noqa: F401
from sam_3d_body import load_sam_3d_body  # noqa: F401
assert torch.__version__.startswith("2.5.1") and torch.cuda.is_available()
print(f"env ok: torch {torch.__version__} (cuda {torch.version.cuda}), {torch.cuda.get_device_name(0)}")
PY
du -sh "$ROOT"
