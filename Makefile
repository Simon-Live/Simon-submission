.PHONY: outputs stock-outputs setup-gpu smoke-gpu setup-cpu check-2-cpu contract-sync contract-check check-2-contract hpc-sync hpc-setup hpc-run hpc-status hpc-outputs setup test run-single run-multi check-2 check-feet gpu-outputs gpu-up gpu-sync gpu-setup gpu-smoke gpu-shell gpu-down

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

# CPU profile (RTMPose-x through rtmlib on ONNX Runtime CPU, lifters bones-prior, fixed-bones and motionbert). The PyTorch CPU
# index also carries older tqdm builds, hence the index strategy; every pin in envs/cpu/requirements.txt is exact.
setup-cpu:
	uv sync
	uv pip install --index-strategy unsafe-best-match -r envs/cpu/requirements.txt

# The CPU backend's 3D bar (mean joint distance to the GPU reference, bone length CV); outside the README DoD.
# Prints the cpu_backend_3d block of check-2 (same scored dir, same stamp checks); exit 0 pass, 1 fail, 2 missing.
# CPU_MODE=cpu-sam3db-single scores that CPU mode dir of the scored dir instead of cpu-single (TICKET-044 B1; the
# block then also reports seconds_per_frame from its provenance.timing).
CPU_MODE ?=

check-2-cpu:
	@$(SCORED_ENV)$(if $(CPU_MODE),PART2_CPU_MODE=$(CPU_MODE) )uv run --quiet python -m part2.check --block cpu_backend_3d

# Regenerate the scored outputs on this host with a part2.stamp/2 each (docs/specs/check-2.md, ADR-0006):
#   make outputs [BACKEND=gpu] [TRACKER=name] [MODES=single,class] [SCORED=out]   single, class, class-local-open
#   make outputs BACKEND=gpu MODES=single,coco-single REFINE=kp2d-fit         one-person ladder rungs (part2.refine); default for single and coco-single: focal,kp2d-fit (the ladder's choice); REFINE=none for unrefined
#   make outputs BACKEND=cpu [LIFTER=name]                                       cpu-single
#   make outputs BACKEND=cpu-sam3db [SCORED=out/j3-b1]                           cpu-sam3db-single (TICKET-044 B1)
# Runs in the gpu-cu128 venv when it exists (cpu and cpu-sam3db with no GPU visible), else in the uv venv.
BACKEND ?= gpu
TRACKER ?=
LIFTER ?=
MODES ?=
REFINE ?=
SCORED ?=
SCORED_ENV = $(if $(SCORED),PART2_SCORED_DIR=$(SCORED) )
OUTPUTS_PY ?= $(if $(wildcard $(GPU_PY)),$(GPU_PY),uv run --quiet python)

outputs:
	$(if $(filter cpu cpu-sam3db,$(BACKEND)),CUDA_VISIBLE_DEVICES= )PYTHONPATH=$(CURDIR) $(OUTPUTS_PY) -m part2.outputs --backend $(BACKEND) $(if $(TRACKER),--tracker $(TRACKER)) $(if $(LIFTER),--lifter $(LIFTER)) $(if $(MODES),--modes $(MODES)) $(if $(SCORED),--scored $(SCORED)) $(if $(REFINE),--refine $(REFINE))

# Stock follower takes for Part 5 (docs/specs/stock-takes.md): download each Pexels clip into ~/.cache, frames at
# 10 fps, the one-person run, then fixtures/output/stock/<take>/{pose3d.json, camera.json, SOURCE.md}. A take is a
# whole clip (pexels-<id>) or a cut listed in part2/stock.py CUTS (pexels-5034562-0to7s: 0 to 7 s of 5034562).
#   make stock-outputs [BACKEND=gpu] [CLIP=pexels-5034562-0to7s]      every take without CLIP
CLIP ?=

stock-outputs:
	$(if $(filter cpu,$(BACKEND)),CUDA_VISIBLE_DEVICES= )PYTHONPATH=$(CURDIR) $(OUTPUTS_PY) -m part2 stock --backend $(BACKEND) $(if $(CLIP),--clip $(CLIP))

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
# threshold passes. Scores the committed fixtures/output/scored/ against fixtures/input/ (no GPU needed);
# make check-2 SCORED=out scores out/<mode>/ instead. Refresh the scored outputs with make outputs.
check-2:
	@$(SCORED_ENV)uv run --quiet part2 check

# Foot points (TICKET-043, docs/specs/integration-contract.md AC-C16): coverage, segment-length consistency and
# plausibility of pose3d.json's optional extra_joints in the scored outputs of the gpu backend, the one that writes
# them. Prints a JSON report; reported, never gated: exit 0 whatever the numbers, 2 only when a file cannot be read.
# With no file the module names every expected file of the scored dir (one per gpu mode of part2.outputs.MODES, and one
# coco-single/<image_id> per image of the committed manifest), so a missing file is reported as unreadable, not dropped
# as a wildcard would drop it. The dir is chosen as for make check-2 (part2.check.scored_dir): SCORED=out passes
# --scored out, else PART2_SCORED_DIR, else fixtures/output/scored. make check-2 does not read this.
check-feet:
	@uv run --quiet python -m part2.foot_check $(if $(SCORED),--scored $(SCORED))

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
