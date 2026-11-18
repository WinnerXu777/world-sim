#!/bin/bash
#SBATCH -J sft_ds_generate              # Job name
#SBATCH -A coc                   # Updated to your GT account
#SBATCH -p ice-gpu
#SBATCH -N 1                            # Number of nodes
#SBATCH --gres=gpu:a100:1
#SBATCH --constraint=A100-80GB               # Request 1 A100 GPU
#SBATCH -c 8                           # 12 CPU cores
#SBATCH --mem=80G                       # 80GB of System RAM (Matches A100 VRAM)
#SBATCH -t 8:00:00                      # 8 hours walltime
#SBATCH -q coc-ice                      # Queue name
#SBATCH -o /home/hice1/jxu828/aiagent/logs/job_%j.out
#SBATCH -e /home/hice1/jxu828/aiagent/logs/job_%j.err

# 1. Setup Environment

module load anaconda3

nvidia-smi
# Path to your custom conda environment on scratch
source activate /home/hice1/jxu828/scratch/conda_envs/aiagent_env
export CONDA_ENVS_PATH=/home/hice1/jxu828/scratch/conda_envs
export CONDA_PKGS_DIRS=/home/hice1/jxu828/scratch/conda_pkgs
export PATH=/home/hice1/jxu828/scratch/conda_envs/aiagent_env/bin:$PATH
export PYTHONPATH=""
# 2. Define Scratch-based Caches
export SCRATCH_DIR="/home/hice1/jxu828/scratch"
export HF_HOME="$SCRATCH_DIR/hf_cache"
export VLLM_CACHE="$HF_HOME/vllm"


# Ensure log and cache directories exist
mkdir -p /home/hice1/jxu828/aiagent/logs
mkdir -p $VLLM_CACHE

# 3. Execution
# Start with a 100-pair generation to test the ReAct logic and JSON formatting
echo "Starting SFT Data Generation at $(date)"


python /home/hice1/jxu828/aiagent/models/pure_skill_output_generator.py \
    --input "/home/hice1/jxu828/aiagent/models/15000_prompts.jsonl"\
    --output "/home/hice1/jxu828/aiagent/models/pure_skill_outputs.jsonl"\
    --batch_size 64 

echo "Job finished at $(date)"