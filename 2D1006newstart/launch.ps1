param([string]$Backend = '')
$ErrorActionPreference = 'Stop'
$eden2dRoot = $PSScriptRoot
$eden2dPython = Join-Path (Split-Path $eden2dRoot -Parent) '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $eden2dPython)) {
    throw 'The repository Python environment is missing. See README.md for setup.'
}
if ($Backend) {
    & $eden2dPython (Join-Path $eden2dRoot 'main.py') --backend $Backend
} else {
    & $eden2dPython (Join-Path $eden2dRoot 'main.py')
}
