#!/bin/bash
# part2 run on a frames dir, on the HPC gpu partition (personal account).
#   sbatch hpc/run.sbatch <single|multi> <frames_dir> <out_dir>   (paths relative to ~/simon-part-2)
#SBATCH --job-name=simon-run
#SBATCH --account=student
#SBATCH --partition=gpu
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=04:00:00
#SBATCH --output=%x-%j.out
set -eo pipefail
ROOT="$HOME/simon-part-2"
MODE="$1"; FRAMES="$2"; OUT="$3"
cd "$ROOT"
module load Anaconda3/2025.12-2 CUDA/12.6.2
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate "$ROOT/env"
export HF_HOME="$ROOT/.cache/huggingface" TORCH_HOME="$ROOT/.cache/torch"
export SAM3D_REPO="$ROOT/sam-3d-body" SAM3D_CKPT="$ROOT/checkpoints/sam-3d-body-dinov3"
export PYTHONPATH="$SAM3D_REPO:$ROOT/part2"
echo "host $(hostname) job ${SLURM_JOB_ID} gpu $(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader)"
cd "$ROOT/part2"
rm -rf "$ROOT/$OUT"
python -m part2.cli run --mode "$MODE" --input "$ROOT/$FRAMES" --out "$ROOT/$OUT"
nvidia-smi --query-gpu=memory.used --format=csv,noheader
