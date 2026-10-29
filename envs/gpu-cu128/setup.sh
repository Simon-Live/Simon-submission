#!/usr/bin/env bash
# GPU profile gpu-cu128 for Part 2 on this host (RTX 5090, compute capability 12.0, no nvcc). Idempotent.
# Writes nothing inside the repository:
#   venv     ~/.local/state/simon-part-2/venvs/gpu-cu128 (uv-managed CPython 3.12: it ships the C headers
#            the detectron2 build needs)
#   source   ~/.local/state/simon-part-2/src/sam-3d-body at the commit pinned in k8s/setup_env.sh
#   weights  jetjodh/sam-3d-body-dinov3 and MoGe-2 in the Hugging Face cache, ViTDet in the iopath cache;
#            model.ckpt and assets/mhr_model.pt checked against OFFICIAL_SHA256 in k8s/infer_one.py
#   record   <venv>/part2-profile.json (versions, detector, model digests), read by part2.backends.gpu_sam3db
# Spec: docs/specs/backends-gpu-cpu.md (TICKET-011, ADR-0002). Usage: bash envs/gpu-cu128/setup.sh
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
STATE="$HOME/.local/state/simon-part-2"
VENV="$STATE/venvs/gpu-cu128"
SRC="$STATE/src/sam-3d-body"
LOGS="$STATE/logs"
PY="$VENV/bin/python"
PROFILE="$VENV/part2-profile.json"
TORCH_INDEX="https://download.pytorch.org/whl/cu128"
WEIGHTS_REPO="jetjodh/sam-3d-body-dinov3"
WEIGHTS_REVISION="1f026b2cc9076fd460243dae553cff9b0dcd199d"
MOGE_REPO="Ruicheng/moge-2-vitl-normal"
MOGE_REVISION="cb0e8bbd6b1e243589717c78e750b1ba4c093acf"
# Trackers (docs/specs/tracker-registry.md): installed --no-deps in step 3b so they keep this profile's torch,
# numpy 2.1.2 and iopath 0.1.9 (sam3 declares numpy<2 and iopath>=0.1.10; neither is needed at inference).
SAM2_COMMIT="2b90b9f5ceec907a1c18123530e92e794ad901a4"
SAM3_COMMIT="f1647e8d0c1d280991f4d1b7d974c2704537fe66"
TRACKER_WHEELS="rtmlib==0.0.16 onnxruntime==1.31.1"
VITDET_URL="https://dl.fbaipublicfiles.com/detectron2/ViTDet/COCO/cascade_mask_rcnn_vitdet_h/f328730692/model_final_f05665.pkl"
DETECTRON2_TIMEOUT="${DETECTRON2_TIMEOUT:-45m}"
export PATH="$HOME/.local/bin:$PATH"
export PYTHONDONTWRITEBYTECODE=1  # no __pycache__ beside check_weights.py: setup writes nothing in the tree

say() { printf 'setup-gpu: %s\n' "$*"; }
die() { printf 'setup-gpu: %s\n' "$*" >&2; exit 1; }

# Commits pinned by the team profile, read from k8s/setup_env.sh so that file stays the one source.
team_pin() {
  local v
  v="$(sed -n "s/^$1=\([0-9a-f]\{40\}\)$/\1/p" "$REPO/k8s/setup_env.sh")"
  [ -n "$v" ] || die "$1 not found in k8s/setup_env.sh"
  printf '%s' "$v"
}
SAM3D_COMMIT="$(team_pin SAM3D_COMMIT)"
DETECTRON2_COMMIT="$(team_pin DETECTRON2_COMMIT)"
MOGE_COMMIT="$(team_pin MOGE_COMMIT)"
UTILS3D_MOGE_COMMIT="$(team_pin UTILS3D_MOGE_COMMIT)"

command -v uv >/dev/null || die "uv not found (expected in ~/.local/bin)"
command -v git >/dev/null || die "git not found"
mkdir -p "$STATE/src" "$LOGS"

# 1. venv and pinned deps: torch and torchvision from the cu128 index only, everything else from PyPI.
[ -x "$PY" ] || uv venv -q --managed-python --python 3.12 "$VENV"
pip_install() { uv pip install -q --python "$PY" -c "$HERE/constraints.txt" "$@"; }
TORCH_PINS="$(grep -E '^(torch|torchvision)==' "$HERE/requirements.txt")"
# shellcheck disable=SC2086  # one pin per word
uv pip install -q --python "$PY" --index-url "$TORCH_INDEX" $TORCH_PINS
pip_install -r <(grep -vE '^(torch|torchvision)==' "$HERE/requirements.txt")
say "deps installed ($(echo "$TORCH_PINS" | tr '\n' ' '))"

# 2. detectron2 for the ViTDet person detector: C++ ops only (no nvcc here), 45 minute timebox. On failure the
#    profile records the rtmlib detector fallback and later runs skip the build (delete the marker to retry).
D2_FAILED="$VENV/detectron2-build-failed-$DETECTRON2_COMMIT"
D2_STATUS=installed D2_SECONDS=0 DETECTOR=vitdet
if [ -e "$D2_FAILED" ]; then
  D2_STATUS=failed DETECTOR=rtmlib-yolox
elif ! "$PY" -c "import detectron2._C" 2>/dev/null; then
  say "building detectron2 $DETECTRON2_COMMIT without CUDA ops (timebox $DETECTRON2_TIMEOUT, log $LOGS/detectron2-build.log)"
  t0=$SECONDS
  if FORCE_CUDA=0 timeout "$DETECTRON2_TIMEOUT" uv pip install --python "$PY" --no-build-isolation --no-deps \
      "git+https://github.com/facebookresearch/detectron2.git@$DETECTRON2_COMMIT" >"$LOGS/detectron2-build.log" 2>&1; then
    D2_STATUS=built
  else
    D2_STATUS=failed DETECTOR=rtmlib-yolox
    touch "$D2_FAILED"
  fi
  D2_SECONDS=$((SECONDS - t0))
  say "detectron2 $D2_STATUS in ${D2_SECONDS}s; detector $DETECTOR"
fi

# 3. MoGe-2 as k8s/setup_env.sh installs it: utils3d_moge pinned, MoGe itself without its extras.
pip_install "utils3d_moge @ git+https://github.com/EasternJournalist/utils3d-moge.git@$UTILS3D_MOGE_COMMIT"
pip_install --no-deps "git+https://github.com/microsoft/MoGe.git@$MOGE_COMMIT"

# 3b. Trackers: rtmlib YOLOX detector (bytetrack, local-open), SAM 2.1 (local-open), SAM 3 code (local-sam31).
uv pip install -q --python "$PY" --no-deps $TRACKER_WHEELS
SAM2_BUILD_CUDA=0 uv pip install -q --python "$PY" --no-deps --no-build-isolation \
  "SAM-2 @ git+https://github.com/facebookresearch/sam2.git@$SAM2_COMMIT"
uv pip install -q --python "$PY" --no-deps "sam3 @ git+https://github.com/facebookresearch/sam3.git@$SAM3_COMMIT"

# 4. SAM 3D Body source at the pinned commit (no setup.py upstream; used through SAM3D_REPO).
git -C "$SRC" rev-parse --git-dir >/dev/null 2>&1 || git clone -q https://github.com/facebookresearch/sam-3d-body.git "$SRC"
if [ "$(git -C "$SRC" rev-parse HEAD)" != "$SAM3D_COMMIT" ]; then
  git -C "$SRC" fetch -q origin "$SAM3D_COMMIT" 2>/dev/null || true
  git -C "$SRC" checkout -q "$SAM3D_COMMIT"
fi

# 5. This repository, editable, so the venv runs `python -m part2` from any checkout root.
pip_install -e "$REPO"

# 6. Weights into the caches, then the official digest check (exit 1 naming the file on a mismatch).
export HF_HUB_DISABLE_PROGRESS_BARS=1
SAM3D_CKPT="$("$PY" -c 'import sys; from huggingface_hub import snapshot_download as d
print(d(sys.argv[1], revision=sys.argv[2], allow_patterns=["model.ckpt", "assets/mhr_model.pt", "model_config.yaml"]))' \
  "$WEIGHTS_REPO" "$WEIGHTS_REVISION")" || die "could not download sam-3d-body-dinov3 weights from $WEIGHTS_REPO"
DIGESTS="$("$PY" "$HERE/check_weights.py" --infer-one "$REPO/k8s/infer_one.py" --dir "$SAM3D_CKPT" --repo "$WEIGHTS_REPO")" \
  || exit 1
say "weights from $WEIGHTS_REPO match the official checksums"
MOGE_PATH="$("$PY" -c 'import sys; from huggingface_hub import hf_hub_download as d
print(d(sys.argv[1], "model.pt", revision=sys.argv[2]))' "$MOGE_REPO" "$MOGE_REVISION")" \
  || die "could not download moge-2-vitl-normal weights from $MOGE_REPO"
VITDET_PATH=""
if [ "$DETECTOR" = vitdet ]; then
  VITDET_PATH="$("$PY" -c 'import sys; from detectron2.utils.file_io import PathManager as P
print(P.get_local_path(sys.argv[1]))' "$VITDET_URL")" || die "could not download vitdet weights from $VITDET_URL"
fi

# 7. Environment check and the profile record read by part2.backends.gpu_sam3db.
export PROFILE SAM3D_CKPT SAM3D_COMMIT DIGESTS WEIGHTS_REPO WEIGHTS_REVISION MOGE_REPO MOGE_REVISION MOGE_PATH \
  VITDET_URL VITDET_PATH DETECTOR D2_STATUS D2_SECONDS DETECTRON2_COMMIT SRC HERE
"$PY" - <<'EOF'
import datetime, json, os, platform, sys

import torch

sys.path.insert(0, os.environ["HERE"])
from check_weights import sha256  # noqa: E402

e = os.environ
assert torch.cuda.is_available(), "torch sees no CUDA device"
arch = torch.cuda.get_arch_list()
assert "sm_120" in arch, f"torch {torch.__version__} has no sm_120 kernels: {arch}"
import moge.model.v2  # noqa: F401,E402
sys.path.insert(0, e["SRC"])
from sam_3d_body import load_sam_3d_body  # noqa: F401,E402
if e["DETECTOR"] == "vitdet":
    from detectron2.config import LazyConfig  # noqa: F401
digests = json.loads(e["DIGESTS"])
models = [
    {"name": "sam-3d-body-dinov3", "source": f"hf:{e['WEIGHTS_REPO']}@{e['WEIGHTS_REVISION']}/model.ckpt",
     "weights_sha256": digests["model.ckpt"], "licence": "SAM License"},
    {"name": "mhr", "source": f"hf:{e['WEIGHTS_REPO']}@{e['WEIGHTS_REVISION']}/assets/mhr_model.pt",
     "weights_sha256": digests["assets/mhr_model.pt"], "licence": "SAM License"},
    {"name": "moge-2-vitl-normal", "source": f"hf:{e['MOGE_REPO']}@{e['MOGE_REVISION']}/model.pt",
     "weights_sha256": sha256(e["MOGE_PATH"]), "licence": "MIT"},
]
if e["DETECTOR"] == "vitdet":
    models.append({"name": "vitdet-h-cascade-mask-rcnn", "source": e["VITDET_URL"],
                   "weights_sha256": sha256(e["VITDET_PATH"]), "licence": "Apache-2.0"})
cap = torch.cuda.get_device_capability(0)
profile = {
    "profile": "gpu-cu128", "created_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "python": platform.python_version(), "torch": torch.__version__, "torch_cuda": torch.version.cuda,
    "arch_list": arch, "device_name": torch.cuda.get_device_name(0), "capability": f"{cap[0]}.{cap[1]}",
    "sam3d_repo": e["SRC"], "sam3d_commit": e["SAM3D_COMMIT"], "sam3d_ckpt": e["SAM3D_CKPT"],
    "moge_path": e["MOGE_PATH"], "vitdet_path": e["VITDET_PATH"], "detector": e["DETECTOR"],
    "detectron2": {"commit": e["DETECTRON2_COMMIT"], "status": e["D2_STATUS"], "seconds": int(e["D2_SECONDS"])},
    "models": models,
}
if e["D2_STATUS"] == "installed" and os.path.exists(e["PROFILE"]):  # keep the first build's timing
    profile["detectron2"] = json.load(open(e["PROFILE"])).get("detectron2", profile["detectron2"])
with open(e["PROFILE"], "w") as fh:
    json.dump(profile, fh, indent=2)
print(f"setup-gpu: env ok: torch {torch.__version__} (cuda {torch.version.cuda}), {profile['device_name']} "
      f"capability {profile['capability']}, detector {e['DETECTOR']}")
EOF

say "profile -> $PROFILE"
cat <<EOF
export SAM3D_REPO=$SRC
export SAM3D_CKPT=$SAM3D_CKPT
EOF
