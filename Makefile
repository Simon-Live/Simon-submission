.PHONY: check-2 gpu-up gpu-sync gpu-setup gpu-smoke gpu-shell gpu-down

POD := user-part2-gpu

# Done-check for Part 2 (see README.md). Replace the stub with the real check:
# it must print a metrics JSON and exit 0 only when every threshold passes.
check-2:
	@echo "check-2: not implemented yet" && exit 1

# --- GPU pod on the k3s cluster (see k8s/README.md) ---
gpu-up:
	kubectl apply -f k8s/pod.yaml
	kubectl wait --for=condition=Ready pod/$(POD) --timeout=600s

gpu-sync:
	git ls-files -z | tar --null -T - -czf - | kubectl exec -i $(POD) -- bash -c 'mkdir -p /workspace/part2 && tar -xzf - -C /workspace/part2'

gpu-setup: gpu-sync
	kubectl exec $(POD) -- bash /workspace/part2/k8s/setup_env.sh

gpu-smoke: gpu-sync
	kubectl exec $(POD) -- python /workspace/part2/k8s/infer_one.py

gpu-shell:
	kubectl exec -it $(POD) -- bash

gpu-down:
	kubectl delete pod $(POD) --ignore-not-found
