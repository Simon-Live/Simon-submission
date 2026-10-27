# GPU on the k3s cluster

Heavy inference (SAM 3D Body, SAM 3.1) runs in one pod on node `nas`: a single RTX 3090
(24 GB) shared by time-slicing with other workloads (ollama, immich, plex, …), so GPU memory
is not guaranteed. SAM 3D Body peaks at ~11 GB.

Naming: pods are `user-<job>`; the NAS folder is `/opt/tank/Applications/simon-part-2`
(mounted at `/workspace`, persists across pods).

```
make gpu-up       # create pod user-part2-gpu and wait until ready
make gpu-sync     # copy this repo's tracked files to /workspace/part2
make gpu-setup    # one-time, idempotent: venv + pinned deps + sam-3d-body (~10 min first time)
make gpu-smoke    # SAM 3D Body on one sample image; prints a JSON report
make gpu-shell    # interactive shell in the pod
make gpu-down     # delete the pod (the NAS folder and its venv/checkpoints stay)
```

Delete the pod when you're done; it holds one of the 10 GPU slots.

## Environment

- Base image `pytorch/pytorch:2.5.1-cuda12.4-cudnn9-devel`; torch is pinned to it
  (`constraints-gpu.txt`) so detectron2's CUDA extension builds with the image's nvcc.
- Python deps: `requirements-gpu.txt`; git deps and the sam-3d-body commit are pinned in `setup_env.sh`.
- MoGe is installed without its optional extras (they pull a newer torch).

## Weights

`facebook/sam-3d-body-dinov3`, `facebook/sam3.1` and `facebook/sam3` are gated on Hugging Face
(access granted to the `the team` account). Downloads need `HF_TOKEN`, provided to the pod
from the optional Secret `user-hf-token`:

```
set -a; source .env; set +a
kubectl create secret generic user-hf-token --from-literal=HF_TOKEN="$HF_TOKEN"
```

`infer_one.py` verifies the checkpoint's SHA-256 against the official repo before loading, so
`WEIGHTS_REPO` can point at a mirror (e.g. `jetjodh/sam-3d-body-dinov3`, byte-identical).
