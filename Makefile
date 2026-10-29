.PHONY: setup-gpu smoke-gpu setup-cpu check-2-cpu contract-sync contract-check check-2-contract hpc-sync hpc-setup hpc-run hpc-status hpc-outputs setup test run-single run-multi check-2 gpu-outputs gpu-up gpu-sync gpu-setup gpu-smoke gpu-shell gpu-down

POD := user-part2-gpu
INPUT ?=
OUT ?= out/$(basename $(notdir $(INPUT)))

setup:
	uv sync

test:
	uv run pytest -q

# Local GPU profile gpu-cu128 (torch 2.8 cu128 for the RTX 5090; docs/specs/backends-gpu-cpu.md). The team's
# torch 2.5.1 profile for k3s and HPC (k8s/, hpc/) is separate and unchanged.
GPU_PY := $(HOME)/.local/state/simon-part-2/venvs/gpu-cu128/bin/python

setup-gpu:
	bash envs/gpu-cu128/setup.sh

smoke-gpu:
	$(GPU_PY) -m part2.backends gpu --smoke

# CPU profile (RTMPose-x through rtmlib on ONNX Runtime CPU, lifters fixed-bones and motionbert). The PyTorch CPU
# index also carries older tqdm builds, hence the index strategy; every pin in envs/cpu/requirements.txt is exact.
setup-cpu:
	uv sync
	uv pip install --index-strategy unsafe-best-match -r envs/cpu/requirements.txt

# The CPU backend's 3D bar (mean joint distance to the GPU reference, bone length CV); outside the README DoD.
check-2-cpu:
	@uv run --quiet python -m part2.eval_3d

# Downstream contract (CONTRACT.md). contract-sync refreshes contracts/consumers/part3-pose3d.schema.json
# (Part 3's own schema, a byte copy) from Part 3's main and exits 1 when it changed, so drift shows up;
# contract-check compares only. Both need a gh login with access to Part 3's repo.
contract-sync:
	uv run --quiet python -m part2.contract sync

contract-check:
	uv run --quiet python -m part2.contract sync --check

# Every committed output against its schema, the Part 3 copy and `doctor --for part3`; prints a metrics
# JSON (files, valid, failures) and exits 0 only when all pass. Needs no GPU and no network.
check-2-contract:
	@uv run --quiet python -m part2.contract check

# make run-single INPUT=clip.mp4 [OUT=out/clip]
run-single:
	uv run part2 run --mode single --input $(INPUT) --out $(OUT)

run-multi:
	uv run part2 run --mode multi --input $(INPUT) --out $(OUT)

# Done-check for Part 2 (see README.md): prints a metrics JSON, exits 0 only when every
# threshold passes. Scores out/ against fixtures/input/; refresh out/ with make gpu-outputs.
check-2:
	@uv run --quiet part2 check

# Run inference for the fixtures on the GPU pod and bring the outputs back to out/.
gpu-outputs: gpu-sync
	bash k8s/gpu_outputs.sh $(POD)

# --- GPU pod on the k3s cluster (see k8s/README.md) ---
gpu-up:
	kubectl apply -f k8s/pod.yaml
	kubectl wait --for=condition=Ready pod/$(POD) --timeout=600s

# Overlay copy of git-tracked files: files deleted locally stay in the pod until removed there.
gpu-sync:
	git ls-files -z | COPYFILE_DISABLE=1 tar --null -T - -czf - | kubectl exec -i $(POD) -- bash -c 'mkdir -p /workspace/part2 && tar -xzf - -C /workspace/part2'

gpu-setup: gpu-sync
	kubectl exec $(POD) -- bash /workspace/part2/k8s/setup_env.sh

gpu-smoke: gpu-sync
	kubectl exec $(POD) -- python /workspace/part2/k8s/infer_one.py

gpu-shell:
	kubectl exec -it $(POD) -- bash

gpu-down:
	kubectl delete pod $(POD) --ignore-not-found

# --- HPC cluster (personal home dir, user account, gpu partition; see hpc/README.md) ---
HPC := <user>@<cluster-login-host>
HPC_ROOT := simon-part-2

hpc-sync:
	ssh $(HPC) 'mkdir -p $(HPC_ROOT)/part2'
	git ls-files -z | rsync -a --from0 --files-from=- ./ $(HPC):$(HPC_ROOT)/part2/

hpc-setup: hpc-sync
	ssh $(HPC) 'cd $(HPC_ROOT) && sbatch part2/hpc/setup_env.sbatch'

# make hpc-run MODE=single FRAMES=data/squat/frames OUT=out/squat  (paths under ~/$(HPC_ROOT))
hpc-run: hpc-sync
	ssh $(HPC) 'cd $(HPC_ROOT) && sbatch part2/hpc/run.sbatch $(MODE) $(FRAMES) $(OUT)'

# Like gpu-outputs, on HPC: refresh out/ for make check-2.
hpc-outputs: hpc-sync
	bash hpc/hpc_outputs.sh $(HPC)

hpc-status:
	ssh $(HPC) 'squeue -u $USER; ls -t $(HPC_ROOT)/*.out 2>/dev/null | head -3'
