param([string]$Job = 'water2')
$ErrorActionPreference = 'Stop'
$edenLocalRoot = 'C:/Users/Rita/Desktop/caleb/voiceimage/qwen-image-2.1'
$edenLocalExecutable = Join-Path $edenLocalRoot 'runtime/sd-cli.exe'
$edenLocalModels = Join-Path $edenLocalRoot 'models'
$edenLocalJob = (Get-Content -LiteralPath (Join-Path $PSScriptRoot 'local_asset_jobs.json') -Raw | ConvertFrom-Json).$Job
if (-not $edenLocalJob) { throw "Unknown job: $Job. Add it to local_asset_jobs.json first." }
$edenLocalOutput = Join-Path (Split-Path $PSScriptRoot -Parent) ('myassets/generated/' + $edenLocalJob.filename)
if (Test-Path -LiteralPath $edenLocalOutput) { throw "Already exists: $edenLocalOutput. Use a new job filename for a new variant." }
if (-not (Test-Path -LiteralPath $edenLocalExecutable)) { throw 'Local Qwen-Image executable is missing.' }
$edenLocalMeta = @{generator='local Qwen-Image 2.1 / stable-diffusion.cpp'; job=$edenLocalJob; source_root=$edenLocalRoot; status='requested'}
$edenLocalMeta | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath ($edenLocalOutput + '.json') -Encoding UTF8
& $edenLocalExecutable --backend cuda0 `
    --diffusion-model (Join-Path $edenLocalModels 'qwen-image-2.1-UC-Q4_K_M.gguf') `
    --vae (Join-Path $edenLocalModels 'qwen_image_2.1_vae_bf16.safetensors') `
    --llm (Join-Path $edenLocalModels 'Qwen3VL-8B-Instruct-Q4_K_M.gguf') `
    --offload-to-cpu --fa --model-args qwen_image_2_1_prefix_cache_type=q8_0 `
    -p $edenLocalJob.prompt -n $edenLocalJob.negative_prompt `
    --cfg-scale 6 --sampling-method euler --steps $edenLocalJob.steps `
    -W $edenLocalJob.width -H $edenLocalJob.height --seed $edenLocalJob.seed -o $edenLocalOutput
if ($LASTEXITCODE -ne 0) {
    $edenLocalMeta.status = 'failed'
    $edenLocalMeta | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath ($edenLocalOutput + '.json') -Encoding UTF8
    throw "Local generator failed with exit code $LASTEXITCODE"
}
$edenLocalMeta.status = 'generated; pending visual evaluation'
$edenLocalMeta | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath ($edenLocalOutput + '.json') -Encoding UTF8
Write-Host "Saved local candidate: $edenLocalOutput"
