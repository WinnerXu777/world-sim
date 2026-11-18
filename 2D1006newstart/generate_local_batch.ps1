param([string[]]$Jobs = @('water2','sand'))
$ErrorActionPreference = 'Stop'
$edenBatchJobs = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'local_asset_jobs.json') -Raw | ConvertFrom-Json
foreach ($edenBatchName in $Jobs) {
    $edenBatchJob = $edenBatchJobs.$edenBatchName
    if (-not $edenBatchJob) { throw "Unknown job: $edenBatchName" }
    $edenBatchOutput = Join-Path (Split-Path $PSScriptRoot -Parent) ('myassets/generated/' + $edenBatchJob.filename)
    if (Test-Path -LiteralPath $edenBatchOutput) {
        Write-Host "Skipping existing candidate: $edenBatchName"
        continue
    }
    & (Join-Path $PSScriptRoot 'generate_local.ps1') -Job $edenBatchName
}
