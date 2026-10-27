.PHONY: setup test run-single run-multi check-2 gpu-outputs gpu-up gpu-sync gpu-setup gpu-smoke gpu-shell gpu-down

POD := user-part2-gpu
INPUT ?=
OUT ?= out/$(basename $(notdir $(INPUT)))

setup:
	uv sync

test:
	uv run pytest -q

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
