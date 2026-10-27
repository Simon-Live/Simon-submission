#!/bin/bash
# One-time (idempotent) GPU environment for Part 2, inside the pod. Everything lives on the
# hostPath volume so it survives pod restarts:
#   /workspace/venv           virtualenv (inherits the base image's torch)
#   /workspace/sam-3d-body    upstream code, pinned commit, used via PYTHONPATH (no setup.py upstream)
#   /workspace/checkpoints    model weights
set -eo pipefail
cd /workspace

SAM3D_COMMIT=b5c765a0d89d789985e186d396315e7590887b94
DETECTRON2_COMMIT=a1ce2f956a1d2212ad672e3c47d53405c2fe4312
MOGE_COMMIT=74fbce054ebed49800de42d0ad0e83495065719a
UTILS3D_MOGE_COMMIT=62f09d58509485564e24d5d9f6aac9ee9ebc0c37
HERE="$(cd "$(dirname "$0")" && pwd)"

apt-get update -qq && apt-get install -y -qq git ffmpeg libgl1 libglib2.0-0 >/dev/null

[ -d venv ] || python -m venv --system-site-packages venv
source venv/bin/activate
PIP="pip install -q -c $HERE/constraints-gpu.txt"

$PIP "setuptools<81" wheel
$PIP -r "$HERE/requirements-gpu.txt"
python -c "import detectron2" 2>/dev/null || \
  $PIP --no-build-isolation --no-deps "git+https://github.com/facebookresearch/detectron2.git@$DETECTRON2_COMMIT"
# MoGe's optional extras (flex-gemm, gradio, pipeline) pull a newer torch; inference needs only these.
$PIP click matplotlib pillow requests tqdm \
  "utils3d_moge @ git+https://github.com/EasternJournalist/utils3d-moge.git@$UTILS3D_MOGE_COMMIT"
$PIP --no-deps "git+https://github.com/microsoft/MoGe.git@$MOGE_COMMIT"

if [ ! -d sam-3d-body ]; then
  git clone -q https://github.com/facebookresearch/sam-3d-body.git
fi
git -C sam-3d-body fetch -q --depth 1 origin "$SAM3D_COMMIT" 2>/dev/null || true
git -C sam-3d-body checkout -q "$SAM3D_COMMIT"

python - <<'EOF'
import torch, detectron2, moge, sys
from detectron2.config import LazyConfig  # noqa: F401  (pulls detectron2 runtime deps)
sys.path.insert(0, "/workspace/sam-3d-body")
from sam_3d_body import load_sam_3d_body  # noqa: F401
assert torch.cuda.is_available()
print(f"env ok: torch {torch.__version__} (cuda {torch.version.cuda}), {torch.cuda.get_device_name(0)}")
EOF
