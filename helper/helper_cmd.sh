salloc -N1 -t3:00:00 --cpus-per-task 8 --ntasks-per-node=1 --gres=gpu:A100:1 --mem-per-gpu=48G

salloc -N1 -t1:00:00 \
--cpus-per-task=8 \
--gres=gpu:a100:1 \
--constraint=A100-80GB \
--mem=80G

export HF_HOME=/home/hice1/jxu828/scratch/hf_cache


python -m vllm.entrypoints.openai.api_server \
    --model Qwen/Qwen2.5-32B-Instruct \
    --tensor-parallel-size 1 \
    --gpu-memory-utilization 0.9 \
    --max-model-len 16384 \
    --trust-remote-code

python -m vllm.entrypoints.openai.api_server \
    --model neuralmagic/Meta-Llama-3.1-70B-Instruct-quantized.w4a16 \
    --gpu-memory-utilization 0.9 \
    --max-model-len 8192 \
    --trust-remote-code 

python /home/hice1/jxu828/aiagent/models/output_generator.py \
    --input "/home/hice1/jxu828/aiagent/models/prompts.jsonl"
    --batch_size 32 \
    --output "/home/hice1/jxu828/aiagent/models/prompts.jsonl"

python /home/hice1/jxu828/aiagent/models/generate_dataset.py \
    --count 20000 \
    --output "/home/hice1/jxu828/aiagent/models/world_agent_sft_1.jsonl"

python /home/hice1/jxu828/aiagent/models/generate_sft_ds.py \
    --count 25000 \
    --batch_size 128 \
    --output "/home/hice1/jxu828/aiagent/models/world_agent_sft_final.jsonl"

export PATH=/home/hice1/jxu828/scratch/conda_envs/aiagent_env/bin:$PATH
export PYTHONPATH=""
export HF_HOME=/home/hice1/jxu828/scratch/hf_cache
export CONDA_ENVS_PATH=/home/hice1/jxu828/scratch/conda_envs
export CONDA_PKGS_DIRS=/home/hice1/jxu828/scratch/conda_pkgs


python /home/hice1/jxu828/aiagent/models/output_generator.py \
    --input "/home/hice1/jxu828/aiagent/models/test_prompts.jsonl"\
    --output "/home/hice1/jxu828/aiagent/models/outputs.jsonl"\
    --batch_size 32 


cd C:\Users\Rita\Desktop\world_simulator\at_the_beginning
..\.venv\Scripts\python.exe initial_test.py


>> .\.venv\Scripts\python.exe -m uvicorn map_test:app --host 127.0.0.1 --port 8003 --app-dir .\at_the_beginning
>>


>> $env:VITE_BACKEND_URL = "http://127.0.0.1:8003"                          
>> npm run dev -- --host=127.0.0.1 --port=5173
>> 