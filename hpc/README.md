# GPU on the HPC cluster

Used while the NAS GPU (`k8s/`) is unavailable. Everything runs in the **personal** home
directory and the **personal account** — never shared directories or partitions.

- Login: `ssh <user>@<cluster-login-host>` (key-based; the cluster is only reachable on the site VPN or local network).
- Root: `~/simon-part-2/` = `part2/` (synced code), `env/` (conda env), `sam-3d-body/`,
  `checkpoints/`, `data/<clip>/frames`, `out/<clip>/`, job logs `<jobname>-<jobid>.out`.
- Quota: home is a 50 GB hard limit (`quota -s`); the env + weights take ~11 GB.
- Jobs: `--account=student --partition=gpu` (V100 32 GB nodes, 2-day limit), job names `simon-*`.

```
make hpc-setup                                              # once: env, pinned deps, weights (~10 min)
rsync -a <clip>/frames <user>@<cluster-login-host>:simon-part-2/data/<clip>/
make hpc-run MODE=single FRAMES=data/<clip>/frames OUT=out/<clip>
make hpc-status
rsync -a <user>@<cluster-login-host>:simon-part-2/out/<clip>/ out/<clip>/
```

`make hpc-sync` overwrites `part2/` with this checkout's tracked files; to run another branch,
sync it into a different folder and point `PYTHONPATH` there. Pins are shared with the pod:
`k8s/requirements-gpu.txt` + `k8s/constraints-gpu.txt` (torch 2.5.1/cu124). The weights come from
the public mirror `jetjodh/sam-3d-body-dinov3`, accepted only if the SHA-256s match the official
gated repo, so no Hugging Face token is needed on HPC.
